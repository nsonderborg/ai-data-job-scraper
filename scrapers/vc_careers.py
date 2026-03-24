"""Danish VC career page scraper — config-driven, ATS-aware.

Strategy per VC:
  1. Workable public API: POST https://apply.workable.com/api/v3/accounts/{slug}/jobs
  2. Lever public API: GET https://api.lever.co/v0/postings/{slug}?mode=json
  3. Greenhouse public API:
     GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  4. Teamtailor HTML: Teamtailor-specific CSS selectors on the careers page.
  5. HTML generic: find all <a> tags whose href matches job-path patterns.

ATS type is pre-declared per VC where known. For unknown/html entries the
generic HTML strategy runs first; if it also detects a known ATS marker in
the page, it switches automatically.

Source field: "VC Careers"  (displayed in Notion)
Company field: the VC firm's name.
"""

import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.http import get_session

logger = get_logger(__name__)

SOURCE = "VC Careers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}

# ─────────────────────────────────────────────────────────────────────────────
# VC configuration
# ─────────────────────────────────────────────────────────────────────────────

VC_CONFIGS: list[dict] = [
    {
        "name": "Heartcore Capital",
        "career_url": "https://www.heartcore.vc/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Seed Capital",
        "career_url": "https://www.seedcapital.dk/jobs",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "PreSeed Ventures",
        "career_url": "https://preseed.dk/team",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Novo Holdings",
        "career_url": "https://apply.workable.com/novoholdings/",
        "ats": "workable",
        "ats_slug": "novoholdings",
    },
    {
        "name": "Lundbeckfond Ventures",
        "career_url": "https://www.lundbeckfonden.com/en/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Nordic Eye",
        "career_url": "https://www.nordiceye.com/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Accelerace",
        "career_url": "https://accelerace.io/about/careers/",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "EIFO",
        "career_url": "https://job.eifo.dk/ledige-stillinger",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Climentum Capital",
        "career_url": "https://climentum.vc/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Futuristic.vc",
        "career_url": "https://futuristic.vc/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Damgaard Company",
        "career_url": "https://damgaard.company/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Scale Capital",
        "career_url": "https://scalecapital.dk/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Lehrmann Ventures",
        "career_url": "https://lehrmann.vc/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "IDC Ventures",
        "career_url": "https://idcventures.dk/careers",
        "ats": "html",
        "ats_slug": "",
    },
    {
        "name": "Investo Capital",
        "career_url": "https://investocapital.dk/careers",
        "ats": "html",
        "ats_slug": "",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def scrape() -> list[JobPosting]:
    postings: list[JobPosting] = []

    for vc in VC_CONFIGS:
        name = vc["name"]
        logger.info("VC Careers — scraping: %s", name)
        try:
            found = _scrape_vc(vc)
            logger.info("  %s → %d postings", name, len(found))
            postings.extend(found)
        except Exception as exc:
            logger.warning("VC Careers — %s failed: %s", name, exc)
        time.sleep(1.5)

    logger.info("VC Careers total: %d postings", len(postings))
    return postings


def _scrape_vc(vc: dict) -> list[JobPosting]:
    ats = vc.get("ats", "html")
    slug = vc.get("ats_slug", "")

    if ats == "workable" and slug:
        return _scrape_workable(vc["name"], slug)
    if ats == "lever" and slug:
        return _scrape_lever(vc["name"], slug)
    if ats == "greenhouse" and slug:
        return _scrape_greenhouse(vc["name"], slug)

    # Teamtailor and HTML both start with fetching the page HTML
    html, final_url = _fetch_html(vc["career_url"])
    if html is None:
        return []

    # Auto-detect ATS from page content if declared as "html"
    if ats == "html":
        ats = _detect_ats(html, final_url)
        logger.debug("  ATS detected: %s", ats)

    if ats == "lever":
        detected_slug = _extract_lever_slug(html)
        if detected_slug:
            return _scrape_lever(vc["name"], detected_slug)
    if ats == "greenhouse":
        detected_slug = _extract_greenhouse_slug(html)
        if detected_slug:
            return _scrape_greenhouse(vc["name"], detected_slug)

    # Teamtailor or generic HTML
    return _parse_career_html(vc["name"], html, final_url)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_html(url: str) -> tuple[Optional[str], str]:
    """Fetch URL, following redirects. Returns (html, final_url) or (None, url)."""
    try:
        r = get_session().get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        return r.text, r.url
    except requests.RequestException as exc:
        logger.warning("  HTTP error fetching %s: %s", url, exc)
        return None, url


# ─────────────────────────────────────────────────────────────────────────────
# ATS detection
# ─────────────────────────────────────────────────────────────────────────────

_TEAMTAILOR_SIGNALS = re.compile(
    r"teamtailor|careers\.teamtailor\.com|\.teamtailor\.com", re.IGNORECASE
)
_LEVER_SIGNALS = re.compile(r"jobs\.lever\.co|api\.lever\.co", re.IGNORECASE)
_GREENHOUSE_SIGNALS = re.compile(
    r"boards\.greenhouse\.io|greenhouse\.io/embed", re.IGNORECASE
)


def _detect_ats(html: str, final_url: str) -> str:
    combined = html[:8000] + final_url
    if _TEAMTAILOR_SIGNALS.search(combined):
        return "teamtailor"
    if _LEVER_SIGNALS.search(combined):
        return "lever"
    if _GREENHOUSE_SIGNALS.search(combined):
        return "greenhouse"
    return "html"


def _extract_lever_slug(html: str) -> Optional[str]:
    m = re.search(r"jobs\.lever\.co/([a-z0-9\-_]+)", html, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_greenhouse_slug(html: str) -> Optional[str]:
    m = re.search(
        r"boards(?:-api)?\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9\-_]+)",
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Lever public API
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_lever(company_name: str, slug: str) -> list[JobPosting]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=100"
    try:
        r = get_session().get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        items = r.json()
    except Exception as exc:
        logger.warning("  Lever API failed for %s: %s", company_name, exc)
        return []

    postings: list[JobPosting] = []
    for item in items:
        title = (item.get("text") or "").strip()
        posting_url = (item.get("hostedUrl") or item.get("applyUrl") or "").strip()
        if not title or not posting_url:
            continue
        categories = item.get("categories") or {}
        location = (categories.get("location") or categories.get("allLocations") or "").strip()
        description = _strip_html(item.get("descriptionPlain") or item.get("description") or "")[:1000]
        postings.append(
            JobPosting(
                title=title,
                company=company_name,
                url=posting_url,
                source=SOURCE,
                description=description,
                location=location,
            )
        )
    return postings


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse public API
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_greenhouse(company_name: str, slug: str) -> list[JobPosting]:
    url = (
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    try:
        r = get_session().get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("  Greenhouse API failed for %s: %s", company_name, exc)
        return []

    postings: list[JobPosting] = []
    for item in data.get("jobs", []):
        title = (item.get("title") or "").strip()
        posting_url = (item.get("absolute_url") or "").strip()
        if not title or not posting_url:
            continue
        location_node = item.get("location") or {}
        location = (location_node.get("name") or "").strip()
        description = _strip_html(item.get("content") or "")[:1000]
        postings.append(
            JobPosting(
                title=title,
                company=company_name,
                url=posting_url,
                source=SOURCE,
                description=description,
                location=location,
            )
        )
    return postings


# ─────────────────────────────────────────────────────────────────────────────
# Workable public API
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_workable(company_name: str, slug: str) -> list[JobPosting]:
    """POST https://apply.workable.com/api/v3/accounts/{slug}/jobs"""
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    payload = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
    api_headers = {**HEADERS, "Content-Type": "application/json", "Accept": "application/json"}
    try:
        r = get_session().post(url, json=payload, headers=api_headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("  Workable API failed for %s: %s", company_name, exc)
        return []

    postings: list[JobPosting] = []
    for item in data.get("results", []):
        title = (item.get("title") or "").strip()
        shortcode = (item.get("shortcode") or "").strip()
        if not title or not shortcode:
            continue
        posting_url = f"https://apply.workable.com/{slug}/j/{shortcode}/"
        loc = item.get("location") or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
        postings.append(JobPosting(
            title=title,
            company=company_name,
            url=posting_url,
            source=SOURCE,
            description="",
            location=location,
        ))
    return postings


# ─────────────────────────────────────────────────────────────────────────────
# Generic HTML + Teamtailor HTML parser
# ─────────────────────────────────────────────────────────────────────────────

_JOB_PATH_RE = re.compile(
    r"(?:/jobs?/|/careers?/|/positions?/|/openings?/|/stillings?|"
    r"ledige-stillinger|/ledige-jobs?|/arbejde/)",
    re.IGNORECASE,
)

_NAV_NOISE_RE = re.compile(
    r"(?:/about|/kontakt|/team|/portfolio|/funds?|/press|/news|/blog|"
    r"/privacy|/cookies|/terms|/events?|/subscribe|/newsletter|mailto:|#)",
    re.IGNORECASE,
)

_MIN_TITLE_LEN = 8
_MAX_TITLE_LEN = 150


def _parse_career_html(
    company_name: str, html: str, base_url: str
) -> list[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")
    origin = _base_origin(base_url)

    postings: list[JobPosting] = []
    seen_urls: set[str] = set()

    # Teamtailor selectors
    for selector in (
        "a[href*='/jobs/']",
        "[data-job-id] a",
        ".jobs-list a",
        ".job-list a",
        ".positions a",
        ".vacancies a",
    ):
        candidates = soup.select(selector)
        if not candidates:
            continue
        for a in candidates:
            _try_add_link(a, origin, company_name, postings, seen_urls)
        if postings:
            break

    # Generic job-path link detection
    if not postings:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if _JOB_PATH_RE.search(href) and not _NAV_NOISE_RE.search(href):
                _try_add_link(a, origin, company_name, postings, seen_urls)

    # List-item fallback
    if not postings:
        main_content = soup.find("main") or soup.find(id=re.compile(r"content|main|jobs", re.I)) or soup
        for li in main_content.find_all("li"):
            links = li.find_all("a", href=True)
            if len(links) != 1:
                continue
            a = links[0]
            href = a["href"]
            if _NAV_NOISE_RE.search(href):
                continue
            _try_add_link(a, origin, company_name, postings, seen_urls)

    if not postings:
        logger.debug("  %s: no job listings extracted from HTML", company_name)

    return postings


def _try_add_link(
    a_tag,
    origin: str,
    company_name: str,
    postings: list[JobPosting],
    seen_urls: set[str],
) -> None:
    href = (a_tag.get("href") or "").strip()
    if not href:
        return

    if href.startswith("/"):
        href = origin + href
    elif not href.startswith("http"):
        return

    if href in seen_urls:
        return

    title = (
        a_tag.get("aria-label")
        or a_tag.get("title")
        or ""
    ).strip()

    if not title:
        heading = a_tag.find(re.compile(r"^h[1-5]$"))
        if heading:
            title = heading.get_text(" ", strip=True)

    if not title:
        title = a_tag.get_text(" ", strip=True)

    title = re.sub(r"\s+", " ", title).strip()[:_MAX_TITLE_LEN]
    if len(title) < _MIN_TITLE_LEN:
        return

    if re.search(
        r"^(?:see all|view all|learn more|read more|apply|about|contact|"
        r"home|menu|back|next|previous|more|alle stillinger|se alle)$",
        title,
        re.IGNORECASE,
    ):
        return

    seen_urls.add(href)
    location = _extract_nearby_location(a_tag)

    postings.append(
        JobPosting(
            title=title,
            company=company_name,
            url=href,
            source=SOURCE,
            description="",
            location=location,
        )
    )


def _extract_nearby_location(a_tag) -> str:
    parent = a_tag.parent
    if parent is None:
        return ""

    for sibling in parent.find_all(
        True,
        {"class": re.compile(r"location|city|place|sted", re.IGNORECASE)},
    ):
        text = sibling.get_text(" ", strip=True)
        if text and len(text) < 60:
            return text

    grandparent = parent.parent
    if grandparent:
        for elem in grandparent.find_all(
            True,
            {"class": re.compile(r"location|city|place|sted", re.IGNORECASE)},
        ):
            text = elem.get_text(" ", strip=True)
            if text and len(text) < 60:
                return text

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _base_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text).strip()
