"""Karriere.forsvaret.dk scraper — decodes Next.js JSON payloads.

The site is a Next.js app that embeds vacancy data in self.__next_f.push()
calls within <script> tags. We extract these JSON payloads and parse the
vacancies array.
"""

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

SOURCE = "Forsvaret"
CAREER_URL = "https://karriere.forsvaret.dk/stillinger/"
BASE_URL = "https://karriere.forsvaret.dk"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Allowed workplace areas — Region Hovedstaden + Nordsjælland
_ALLOWED_WORKPLACES = {
    "københavn by",
    "københavns omegn",
    "nordsjælland",
    "østsjælland",
}

# Excluded workplace areas — everything else
_EXCLUDED_WORKPLACES = {
    "vestsjælland",
    "sydjylland",
    "fyn",
    "nordjylland",
    "østjylland",
    "vestjylland",
    "sydsjælland",
    "bornholm",
}


def scrape() -> list[JobPosting]:
    logger.info("Forsvaret — fetching career page")
    try:
        r = get_session().get(CAREER_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Forsvaret HTTP error: %s", exc)
        return []

    vacancies = _extract_vacancies(r.text)
    if not vacancies:
        logger.info("Forsvaret: no vacancies extracted from Next.js data")
        return []

    postings: list[JobPosting] = []
    for v in vacancies:
        posting = _parse_vacancy(v)
        if posting:
            postings.append(posting)

    logger.info("Forsvaret: %d postings after workplace filter", len(postings))
    return postings


def _extract_vacancies(html: str) -> list[dict]:
    """Extract vacancy dicts from Next.js self.__next_f.push() payloads."""
    soup = BeautifulSoup(html, "html.parser")
    vacancies = []

    for script in soup.find_all("script"):
        text = script.string or ""
        if "self.__next_f.push" not in text:
            continue

        # Find JSON strings within push() calls
        for m in re.finditer(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', text, re.DOTALL):
            payload = m.group(1)
            # Unescape the JSON string
            try:
                payload = payload.encode().decode("unicode_escape")
            except (UnicodeDecodeError, ValueError):
                continue

            # Look for arrays of vacancy-like objects with brace matching
            for arr_match in re.finditer(r'\[(\{.*?\}(?:,\s*\{.*?\})*)\]', payload, re.DOTALL):
                try:
                    items = json.loads("[" + arr_match.group(1) + "]")
                    # Check if these look like vacancies
                    if items and isinstance(items[0], dict) and "title" in items[0]:
                        vacancies.extend(items)
                except (json.JSONDecodeError, IndexError):
                    continue

    return vacancies


def _parse_vacancy(v: dict) -> Optional[JobPosting]:
    title = (v.get("title") or "").strip()
    if not title:
        return None

    # URL from slug or path
    slug = v.get("slug") or v.get("url") or ""
    if slug.startswith("http"):
        url = slug
    elif slug.startswith("/"):
        url = BASE_URL + slug
    else:
        url = f"{CAREER_URL}{slug}"

    # Workplace filter
    workplaces = v.get("workplaces") or v.get("workplace") or []
    if isinstance(workplaces, str):
        workplaces = [workplaces]

    workplace_names = {w.lower().strip() for w in workplaces if isinstance(w, str)}

    # If all workplaces are excluded, skip
    if workplace_names and workplace_names.issubset(_EXCLUDED_WORKPLACES):
        return None

    # If workplaces specified but none are allowed, skip
    if workplace_names and not workplace_names.intersection(_ALLOWED_WORKPLACES):
        # Only skip if we have a clear signal — unknown workplaces get benefit of doubt
        if workplace_names.issubset(_EXCLUDED_WORKPLACES | _ALLOWED_WORKPLACES):
            return None

    location = ", ".join(workplaces) if workplaces else ""

    # Description from category/branch
    category = v.get("category") or v.get("branch") or ""
    if isinstance(category, list):
        category = ", ".join(str(c) for c in category)
    description = str(category)[:500]

    deadline = v.get("deadline") or v.get("applicationDeadline") or None

    return JobPosting(
        title=title,
        company="Forsvaret",
        url=url,
        source=SOURCE,
        description=description,
        location=location,
        deadline=deadline,
    )
