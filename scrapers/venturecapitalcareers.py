"""Venture Capital Careers scraper.

Uses two pre-filtered location URLs that already restrict to Copenhagen
and Malmö, eliminating non-European results at the source:

  https://venturecapitalcareers.com/jobs/locations/copenhagen-84-denmark
    ?seniority=entry_level,associate,mid_level
  https://venturecapitalcareers.com/jobs/locations/malmo-m-sweden
    ?seniority=entry_level,associate,mid_level

Both endpoints are paginated via &page=N.
"""
import time
import requests
from bs4 import BeautifulSoup

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "VC Careers Jobs"
BASE_URL = "https://venturecapitalcareers.com"

_LOCATION_URLS = [
    BASE_URL + "/jobs/locations/copenhagen-84-denmark?seniority=entry_level%2Cassociate%2Cmid_level",
    BASE_URL + "/jobs/locations/malmo-m-sweden?seniority=entry_level%2Cassociate%2Cmid_level",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
MAX_PAGES = 20  # Safety cap


def scrape() -> list[JobPosting]:
    all_postings: list[JobPosting] = []
    seen_urls: set[str] = set()

    for base_url in _LOCATION_URLS:
        _scrape_location(base_url, all_postings, seen_urls)

    logger.info("VC Careers: %d total postings", len(all_postings))
    return all_postings


def _scrape_location(base_url: str, all_postings: list, seen_urls: set) -> None:
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        try:
            r = get_session().get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("VC Careers: fetch failed (%s): %s", url, exc)
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all(
            "div",
            class_=lambda c: c and "shadow-elevation-card-rest" in c,
        )
        if not cards:
            logger.debug("VC Careers: no cards on page %d of %s — stopping", page, url)
            break

        for card in cards:
            posting = _parse_card(card)
            if posting is None or posting.url in seen_urls:
                continue
            seen_urls.add(posting.url)
            all_postings.append(posting)

        # Check for "Next" page link
        has_next = any(
            "next" in a.get_text(strip=True).lower()
            for a in soup.find_all("a", href=lambda h: h and "page=" in h)
        )
        if not has_next:
            break

        time.sleep(1.0)


def _parse_card(card) -> JobPosting | None:
    # Job URL
    link = card.find("a", href=lambda h: h and "/companies/" in h and "/jobs/" in h)
    if not link:
        return None
    href = link["href"]
    url = href if href.startswith("http") else BASE_URL + href

    # Title
    h3 = card.find("h3")
    if not h3:
        return None
    title = h3.get_text(strip=True)
    if not title:
        return None

    # Company
    co_span = card.find(
        "span",
        class_=lambda c: c and "shrink-0" in c and "whitespace-nowrap" in c,
    )
    company = co_span.get_text(strip=True) if co_span else ""

    # Location
    loc_span = card.find("span", class_=lambda c: c and "truncate" in c)
    raw_location = loc_span.get_text(strip=True) if loc_span else ""

    city = raw_location.split(",")[0].strip() if raw_location else ""
    description = raw_location

    return JobPosting(
        title=title,
        company=company,
        url=url,
        source=SOURCE,
        description=description,
        location=city,
    )
