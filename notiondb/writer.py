"""Notion writer — queries existing entries by URL before inserting to deduplicate."""
from datetime import date
from typing import Optional

from notion_client import Client

from config.settings import NOTION_API_KEY, NOTION_DATABASE_ID
from config.logging_config import get_logger
from scrapers import JobPosting

logger = get_logger(__name__)

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(auth=NOTION_API_KEY)
    return _client


def _url_exists(url: str) -> bool:
    """Return True if a page with this URL already exists in the database."""
    client = _get_client()
    response = client.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "property": "URL",
            "url": {"equals": url},
        },
    )
    return len(response["results"]) > 0


def write_job(posting: JobPosting) -> bool:
    """Write a job posting to Notion. Returns True if written, False if duplicate/skipped."""
    if _url_exists(posting.url):
        logger.debug("Duplicate — skipping: %s", posting.url)
        return False

    client = _get_client()

    properties: dict = {
        "Job Title": {
            "title": [{"text": {"content": posting.title}}]
        },
        "Company": {
            "rich_text": [{"text": {"content": posting.company}}]
        },
        "Source": {
            "select": {"name": posting.source}
        },
        "Description & Match": {
            "rich_text": [{"text": {"content": _truncate(posting.match_reason or posting.description, 2000)}}]
        },
        "Relevancy Score": {
            "number": posting.relevancy_score if posting.relevancy_score else None
        },
        "Date Found": {
            "date": {"start": date.today().isoformat()}
        },
        "Pipeline Status": {
            "select": {"name": "New"}
        },
        "URL": {
            "url": posting.url
        },
    }

    if posting.deadline:
        properties["Deadline"] = {"date": {"start": posting.deadline}}

    # Remove None-valued number properties (Notion rejects null numbers)
    if properties["Relevancy Score"]["number"] is None:
        del properties["Relevancy Score"]

    client.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )
    logger.info("Written to Notion: %s — %s", posting.company, posting.title)
    return True


def write_jobs(postings: list[JobPosting]) -> tuple[int, int]:
    """Write a list of postings. Returns (written, skipped)."""
    written = skipped = 0
    for posting in postings:
        try:
            if write_job(posting):
                written += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("Failed to write posting %s: %s", posting.url, exc)
            skipped += 1
    return written, skipped


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
