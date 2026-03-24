"""PensionsJob.dk scraper — pensionsjob.dk (no trailing 's'), Next.js/MUI grid.

The site renders a grid of job cards on the homepage. Each card contains a title
(h3), company name (from logo alt text), and a link. We keyword-filter on the
client side since the site has no search API.
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "PensionsJob"
BASE_URL = "https://pensionsjob.dk"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# AI & data-focused keywords — postings must match at least one
KEYWORDS = [
    "data",
    "AI",
    "machine learning",
    "analytiker",
    "analyst",
    "BI",
    "intelligence",
    "digital",
    "automation",
    "automatisering",
    "teknologi",
    "IT",
    "developer",
    "engineer",
]

_KW_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(kw)}" for kw in KEYWORDS),
    re.IGNORECASE,
)


def scrape() -> list[JobPosting]:
    logger.info("PensionsJob — fetching homepage")
    try:
        r = get_session().get(BASE_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("PensionsJob HTTP error: %s", exc)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    postings: list[JobPosting] = []
    seen_urls: set[str] = set()

    # Cards are rendered as MUI grid items with an h3 title and a link
    for card in soup.find_all("div", class_=re.compile(r"MuiGrid-item|MuiCard-root")):
        posting = _parse_card(card)
        if posting is None:
            continue
        if posting.url in seen_urls:
            continue
        # Client-side keyword filter
        text = f"{posting.title} {posting.description}"
        if not _KW_PATTERN.search(text):
            continue
        seen_urls.add(posting.url)
        postings.append(posting)

    logger.info("PensionsJob: %d postings after keyword filter", len(postings))
    return postings


def _parse_card(card) -> Optional[JobPosting]:
    # Title from h3
    h3 = card.find("h3")
    if not h3:
        return None
    title = h3.get_text(" ", strip=True)
    if not title:
        return None

    # URL from first <a> with href
    link = card.find("a", href=True)
    if not link:
        return None
    href = link["href"]
    url = href if href.startswith("http") else BASE_URL + href

    # Company from logo alt text or nearby element
    img = card.find("img", alt=True)
    company = (img["alt"] if img else "").strip()

    # Description from category/level tags
    tags = card.find_all("span")
    description = " ".join(t.get_text(strip=True) for t in tags if t.get_text(strip=True))[:500]

    return JobPosting(
        title=title,
        company=company,
        url=url,
        source=SOURCE,
        description=description,
    )
