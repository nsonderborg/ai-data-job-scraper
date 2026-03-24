"""LinkedIn jobs scraper via Apify — curious_coder/linkedin-jobs-scraper.

Runs a single Apify actor call with all search URLs batched together,
waits for completion, then parses the dataset into JobPosting objects.

Actor:    hKByXkMQaC5Qt9UMN  (curious_coder/linkedin-jobs-scraper)
Input:    urls (list of LinkedIn search URLs), maxItems
Output:   link, title, companyName, location, postedAt, descriptionText,
          employmentType, workplaceTypes, workRemoteAllowed, country
"""
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse

from apify_client import ApifyClient

from config.settings import APIFY_API_TOKEN
from config.logging_config import get_logger
from scrapers import JobPosting

logger = get_logger(__name__)

SOURCE = "LinkedIn"
ACTOR_ID = "hKByXkMQaC5Qt9UMN"  # curious_coder/linkedin-jobs-scraper

# Maximum items to fetch per search URL. 25 is enough for daily runs on
# each keyword since we use the 24h filter.
MAX_ITEMS_PER_URL = 25

# How long to wait for the actor run to finish (seconds)
ACTOR_TIMEOUT_SECS = 300

# LinkedIn time filter: r86400 = last 24 h
_TIME_FILTER = "r86400"

# Build search URLs: (keyword, location, remote_only)
# Copenhagen on-site + hybrid, then Denmark-wide remote
_SEARCHES: list[tuple[str, str, bool]] = [
    # on-site / hybrid in Copenhagen — AI & data focused
    ("data scientist", "Copenhagen, Denmark", False),
    ("data engineer", "Copenhagen, Denmark", False),
    ("machine learning engineer", "Copenhagen, Denmark", False),
    ("AI engineer", "Copenhagen, Denmark", False),
    ("data analyst", "Copenhagen, Denmark", False),
    ("MLOps", "Copenhagen, Denmark", False),
    ("analytics engineer", "Copenhagen, Denmark", False),
    ("NLP engineer", "Copenhagen, Denmark", False),
    ("business intelligence", "Copenhagen, Denmark", False),
    ("Power BI", "Copenhagen, Denmark", False),
    ("Python developer", "Copenhagen, Denmark", False),
    ("deep learning", "Copenhagen, Denmark", False),
    ("computer vision", "Copenhagen, Denmark", False),
    ("LLM", "Copenhagen, Denmark", False),
    # remote — broader Denmark scope
    ("data scientist", "Denmark", True),
    ("data engineer", "Denmark", True),
    ("machine learning", "Denmark", True),
    ("AI engineer", "Denmark", True),
    ("MLOps", "Denmark", True),
]


def _build_url(keyword: str, location: str, remote_only: bool) -> str:
    params: dict[str, str] = {
        "keywords": keyword,
        "location": location,
        "f_TPR": _TIME_FILTER,
    }
    if remote_only:
        params["f_WT"] = "2"  # LinkedIn work type: 2 = remote
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def scrape() -> list[JobPosting]:
    if not APIFY_API_TOKEN:
        logger.warning("LinkedIn: APIFY_API_TOKEN not set — skipping")
        return []

    search_urls = [_build_url(kw, loc, remote) for kw, loc, remote in _SEARCHES]
    logger.info("LinkedIn: launching Apify actor with %d search URLs", len(search_urls))

    client = ApifyClient(APIFY_API_TOKEN)
    run = _run_actor(client, search_urls)
    if run is None:
        return []

    items = _fetch_dataset(client, run["defaultDatasetId"])
    if not items:
        return []

    postings = _parse_items(items)
    logger.info("LinkedIn: %d unique postings parsed from %d raw items", len(postings), len(items))
    return postings


def _run_actor(client: ApifyClient, urls: list[str]) -> Optional[dict]:
    try:
        run = client.actor(ACTOR_ID).call(
            run_input={"urls": urls, "maxItems": MAX_ITEMS_PER_URL},
            timeout_secs=ACTOR_TIMEOUT_SECS,
        )
        status = (run or {}).get("status", "UNKNOWN")
        if status != "SUCCEEDED":
            logger.warning("LinkedIn: Apify run finished with status %s", status)
            return None
        logger.info("LinkedIn: actor run succeeded, dataset %s", run["defaultDatasetId"])
        return run
    except Exception as exc:
        logger.error("LinkedIn: Apify actor call failed: %s", exc)
        return None


def _fetch_dataset(client: ApifyClient, dataset_id: str) -> list[dict]:
    try:
        items = list(client.dataset(dataset_id).iterate_items())
        return items
    except Exception as exc:
        logger.error("LinkedIn: dataset fetch failed: %s", exc)
        return []


def _parse_items(items: list[dict]) -> list[JobPosting]:
    seen_urls: set[str] = set()
    postings: list[JobPosting] = []

    for item in items:
        posting = _parse_item(item)
        if posting is None:
            continue
        if posting.url in seen_urls:
            continue
        seen_urls.add(posting.url)
        postings.append(posting)

    return postings


def _canonical_linkedin_url(url: str) -> str:
    """Strip tracking query params from a LinkedIn job URL.

    Raw:       https://dk.linkedin.com/jobs/view/title-at-co-12345?refId=x&trackingId=y
    Canonical: https://dk.linkedin.com/jobs/view/title-at-co-12345
    """
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def _parse_item(item: dict) -> Optional[JobPosting]:
    title = (item.get("title") or "").strip()
    if not title:
        return None

    raw_url = (item.get("link") or item.get("applyUrl") or "").strip()
    if not raw_url:
        return None
    url = _canonical_linkedin_url(raw_url)

    company = (item.get("companyName") or "").strip()
    location = (item.get("location") or "").strip()
    description = (item.get("descriptionText") or "")[:1000].strip()

    # Derive deadline hint from expireAt (milliseconds epoch) if present
    deadline: Optional[str] = None
    expire_ms = item.get("expireAt")
    if expire_ms:
        try:
            deadline = datetime.fromtimestamp(int(expire_ms) / 1000, tz=timezone.utc).date().isoformat()
        except (ValueError, OSError):
            pass

    return JobPosting(
        title=title,
        company=company,
        url=url,
        source=SOURCE,
        description=description,
        location=location,
        deadline=deadline,
    )
