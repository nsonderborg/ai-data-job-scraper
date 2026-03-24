"""Politiet career portal scraper — parses XML sitemap, no browser required.

The site renders job descriptions with JavaScript, but the sitemap at
/sitemap.xml contains all job posting URLs with structured slugs:

  /LedigStilling/City-Title-PostalCode

We extract title and postal code from the URL slug, then filter by postal code
to keep only Region Hovedstaden + Nordsjælland (1000–3699).
"""

import re
import time
from typing import Optional
from xml.etree import ElementTree

import requests

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "Politi"
SITEMAP_URL = "https://politi.dk/sitemap.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Postal codes 1000–3699 cover Region Hovedstaden + Nordsjælland
_MIN_POSTAL = 1000
_MAX_POSTAL = 3699

# Slug pattern: /LedigStilling/City-Title-PostalCode
_SLUG_RE = re.compile(
    r"/LedigStilling/([A-Za-zÆØÅæøå\-]+)-(\d{4})(?:/|$)", re.IGNORECASE
)


def scrape() -> list[JobPosting]:
    logger.info("Politi — fetching sitemap")
    try:
        r = get_session().get(SITEMAP_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Politi sitemap fetch failed: %s", exc)
        return []

    try:
        root = ElementTree.fromstring(r.content)
    except ElementTree.ParseError as exc:
        logger.warning("Politi sitemap XML parse error: %s", exc)
        return []

    # Namespace handling — sitemap XML uses a default namespace
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [
        loc.text
        for loc in root.findall(".//sm:url/sm:loc", ns)
        if loc.text and "/LedigStilling/" in loc.text
    ]

    logger.info("Politi: %d job URLs in sitemap", len(urls))

    postings: list[JobPosting] = []
    for url in urls:
        posting = _parse_url(url)
        if posting:
            postings.append(posting)

    logger.info("Politi: %d postings after postal filter", len(postings))
    return postings


def _parse_url(url: str) -> Optional[JobPosting]:
    m = _SLUG_RE.search(url)
    if not m:
        return None

    slug_text = m.group(1)
    postal = int(m.group(2))

    # Filter by postal code range
    if not (_MIN_POSTAL <= postal <= _MAX_POSTAL):
        return None

    # Reconstruct title from slug: "Koebenhavn-Some-Job-Title" → "Some Job Title"
    parts = slug_text.split("-")
    # First part is typically the city name
    city = parts[0].replace("oe", "ø").replace("ae", "æ").replace("aa", "å") if parts else ""
    title = " ".join(parts[1:]) if len(parts) > 1 else slug_text
    title = title.replace("-", " ").strip()

    if not title:
        return None

    location = f"{postal} {city}" if city else str(postal)

    return JobPosting(
        title=title,
        company="Politiet",
        url=url,
        source=SOURCE,
        description="",
        location=location,
    )
