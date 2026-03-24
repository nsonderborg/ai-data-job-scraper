"""The Hub (thehub.io) scraper — Nordic startup job board.

thehub.io is a Nuxt.js SSR app. Job data is pre-rendered in the HTML but the
<a> overlay link is empty — content lives in sibling elements inside each
card div.

Location scoping:
  countryCode=DK     — Denmark on-site (CPH + all DK; location filter trims later)
  countryCode=REMOTE — remote listings
"""

import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "The Hub"
BASE_URL = "https://thehub.io/jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}

MAX_PAGES = 3

KEYWORDS = [
    "AI",
    "machine learning",
    "data scientist",
    "data engineer",
    "data analyst",
    "MLOps",
    "NLP",
    "deep learning",
    "Python",
    "business intelligence",
]

_COUNTRY_CODES = ["DK", "REMOTE"]


def scrape() -> list[JobPosting]:
    seen_urls: set[str] = set()
    postings: list[JobPosting] = []

    for keyword in KEYWORDS:
        logger.info("The Hub — keyword: %r", keyword)
        try:
            kw_postings = _scrape_keyword(keyword, seen_urls)
            postings.extend(kw_postings)
            logger.info("  → %d new results", len(kw_postings))
        except Exception as exc:
            logger.warning("The Hub keyword %r failed: %s", keyword, exc)
        time.sleep(1.5)

    logger.info("The Hub total: %d unique postings", len(postings))
    return postings


def _scrape_keyword(keyword: str, seen_urls: set[str]) -> list[JobPosting]:
    postings: list[JobPosting] = []
    for country_code in _COUNTRY_CODES:
        for page in range(1, MAX_PAGES + 1):
            found, has_more = _fetch_page(keyword, country_code, page, seen_urls)
            postings.extend(found)
            if not has_more:
                break
            time.sleep(1.0)
    return postings


def _fetch_page(
    keyword: str, country_code: str, page: int, seen_urls: set[str]
) -> tuple[list[JobPosting], bool]:
    params = urlencode([
        ("keyword", keyword),
        ("countryCode", country_code),
        ("page", str(page)),
    ])
    url = f"{BASE_URL}?{params}"

    try:
        r = get_session().get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("The Hub HTTP error (%s p%d): %s", country_code, page, exc)
        return [], False

    return _parse_page(r.text, page, seen_urls)


def _parse_page(
    html: str, page: int, seen_urls: set[str]
) -> tuple[list[JobPosting], bool]:
    soup = BeautifulSoup(html, "html.parser")
    postings: list[JobPosting] = []

    # Each job is a div whose class list contains "card-job-find-list"
    for card in soup.find_all("div", class_="card-job-find-list"):
        posting = _parse_card(card)
        if posting is None:
            continue
        if posting.url in seen_urls:
            continue
        seen_urls.add(posting.url)
        postings.append(posting)

    has_more = _has_next_page(soup, page)
    return postings, has_more


def _parse_card(card) -> JobPosting | None:
    # URL: the empty overlay link
    link = card.find("a", class_="card-job-find-list__link")
    if not link:
        return None
    href = (link.get("href") or "").strip()
    if not href.startswith("/jobs/"):
        return None
    url = "https://thehub.io" + href

    # Title
    pos_span = card.find("span", class_="card-job-find-list__position")
    title = pos_span.get_text(" ", strip=True) if pos_span else ""
    if not title:
        return None

    # Company + location: first two <span> children of .bullet-inline-list
    company = ""
    location = ""
    bullet_div = card.find("div", class_="bullet-inline-list")
    if bullet_div:
        spans = [s.get_text(strip=True) for s in bullet_div.find_all("span") if s.get_text(strip=True)]
        if spans:
            company = spans[0]
        if len(spans) > 1:
            location = spans[1]

    return JobPosting(
        title=title,
        company=company,
        url=url,
        source=SOURCE,
        description="",
        location=location,
    )


def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
    """Check if a link to the next page number exists in the pagination."""
    next_str = f"page={current_page + 1}"
    return any(next_str in (a.get("href") or "") for a in soup.find_all("a", href=True))
