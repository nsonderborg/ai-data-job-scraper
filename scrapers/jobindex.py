"""Jobindex.dk scraper — parses embedded Stash JSON, no browser required."""
import json
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "Jobindex"
BASE_URL = "https://www.jobindex.dk/jobsoegning"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Max pages to fetch per keyword (20 results/page). Cap prevents runaway
# requests on very broad keywords.
MAX_PAGES = 3

KEYWORDS = [
    # AI / ML
    "AI",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "NLP",
    "LLM",
    "generative AI",
    "computer vision",
    "MLOps",
    "agentic",
    "applied AI",
    # Data engineering & analytics
    "data engineer",
    "data scientist",
    "data analyst",
    "dataanalytiker",
    "data platform",
    "analytics engineer",
    "ETL",
    "data warehouse",
    "dbt",
    # BI & reporting
    "business intelligence",
    "BI analytiker",
    "Power BI",
    # Software / infra (data-adjacent)
    "Python developer",
    "backend developer",
    "cloud engineer",
    "DevOps",
    "software engineer",
    # Danish terms
    "maskinlæring",
    "kunstig intelligens",
]


def scrape() -> list[JobPosting]:
    seen_urls: set[str] = set()
    postings: list[JobPosting] = []

    for keyword in KEYWORDS:
        logger.info("Jobindex — keyword: %r", keyword)
        try:
            kw_postings = _scrape_keyword(keyword, seen_urls)
            postings.extend(kw_postings)
            logger.info("  → %d new results", len(kw_postings))
        except Exception as exc:
            logger.warning("Jobindex keyword %r failed: %s", keyword, exc)
        time.sleep(1.5)

    logger.info("Jobindex total: %d unique postings", len(postings))
    return postings


# Area codes to query simultaneously. Covers Region Hovedstaden, Nordsjælland,
# and Skåne (southern Sweden). Remote jobs have no area and surface regardless.
_AREAS = ["storkbh", "nordsj", "skaane"]


def _scrape_keyword(keyword: str, seen_urls: set[str]) -> list[JobPosting]:
    postings: list[JobPosting] = []
    page = 1

    while page <= MAX_PAGES:
        params: list[tuple[str, str | int]] = (
            [("q", keyword), ("jobage", 1), ("page", page)]
            + [("area", a) for a in _AREAS]
        )
        data = _fetch_stash(params)
        if data is None:
            break

        search_response = data["jobsearch/result_app"]["storeData"]["searchResponse"]
        results = search_response.get("results", [])
        total_pages = search_response.get("total_pages", 1)

        for item in results:
            posting = _parse_result(item)
            if posting is None:
                continue
            if posting.url in seen_urls:
                continue
            seen_urls.add(posting.url)
            postings.append(posting)

        if page >= total_pages:
            break

        page += 1
        time.sleep(1.0)

    return postings


def _fetch_stash(params) -> Optional[dict]:
    try:
        r = get_session().get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Jobindex HTTP error: %s", exc)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"var Stash\s*=\s*(\{.*?\});\s*//\]\]>", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError as exc:
                logger.warning("Jobindex Stash JSON parse error: %s", exc)
                return None

    logger.warning("Jobindex: Stash variable not found in page")
    return None


def _parse_result(item: dict) -> Optional[JobPosting]:
    title = (item.get("headline") or "").strip()
    if not title:
        return None

    # Canonical share_url is cleaner than the tracking URL in `url`
    url = item.get("share_url") or item.get("url") or ""
    if not url:
        return None

    company = (item.get("companytext") or "").strip()

    # Description: pull <p> tags from .PaidJob-inner for clean snippet text
    raw_html = item.get("html", "")
    description = ""
    if raw_html:
        snippet = BeautifulSoup(raw_html, "html.parser")
        inner = snippet.select_one(".PaidJob-inner")
        if inner:
            paragraphs = inner.find_all("p")
            if paragraphs:
                description = " ".join(p.get_text(" ", strip=True) for p in paragraphs)[:1000]
            else:
                description = inner.get_text(" ", strip=True)[:1000]
        else:
            description = snippet.get_text(" ", strip=True)[:1000]

    deadline = item.get("lastdate")  # ISO date string or None

    # City list from addresses; "Remote" appended when home_workplace flag is set
    cities = [a.get("city", "") for a in (item.get("addresses") or []) if a.get("city")]
    if item.get("home_workplace"):
        cities.append("Remote")
    location = ", ".join(cities)

    return JobPosting(
        title=title,
        company=company,
        url=url,
        source=SOURCE,
        description=description,
        deadline=deadline,
        location=location,
    )
