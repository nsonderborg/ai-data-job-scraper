"""AI & Data Job Scraper — automated Danish job market monitor.

Pipeline per run:
  1. Run all scrapers in sequence (8 sources)
  2. Apply pre-scoring filters (location + student-role + AI/data domain keywords)
  3. Deduplicate across scrapers by URL and normalised title+company
  4. Score with local Ollama LLM (skipped gracefully if offline)
  5. Write new postings to Notion (writer deduplicates against existing DB)
  6. Log summary

Usage:
  python main.py              # full run — scrape, filter, score, write to Notion
  python main.py --dry-run    # scrape, filter, score, print results (no Notion write)
"""

import argparse
import re
import sys
import time

from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.filters import apply_all
from scoring.relevancy import score_postings

# Scrapers
from scrapers import jobindex, pensionsjobs, politi, forsvaret
from scrapers import linkedin_apify, thehub, vc_careers, venturecapitalcareers

logger = get_logger("main")

# Legal-entity suffixes to strip before title+company comparison
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(a/s|aps|ap s|gmbh|ltd|llc|inc|as|ab|se|oy|nv|bv|sarl|sas)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Normalise a title or company name for fuzzy deduplication."""
    t = (text or "").lower()
    t = _LEGAL_SUFFIX_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _company_match(a: str, b: str) -> bool:
    """True if either normalised company name contains the other as a substring."""
    if not a or not b:
        return False
    return a in b or b in a

# Ordered list of (label, scrape_fn)
_SCRAPERS: list[tuple[str, object]] = [
    ("Jobindex",     jobindex.scrape),
    ("PensionsJobs", pensionsjobs.scrape),
    ("Politi",       politi.scrape),
    ("Forsvaret",    forsvaret.scrape),
    ("LinkedIn",     linkedin_apify.scrape),
    ("The Hub",      thehub.scrape),
    ("VC Careers",   vc_careers.scrape),
    ("VCC Jobs",     venturecapitalcareers.scrape),
]


def main(dry_run: bool = False) -> None:
    start = time.monotonic()
    logger.info("=" * 60)
    logger.info("AI & Data Job Scraper run starting%s", " (DRY RUN)" if dry_run else "")

    # 1. Run all scrapers
    raw: list[JobPosting] = []
    for label, fn in _SCRAPERS:
        logger.info("Running scraper: %s", label)
        try:
            found = fn()
            logger.info("  %s → %d raw postings", label, len(found))
            raw.extend(found)
        except Exception as exc:
            logger.error("  %s scraper crashed: %s", label, exc, exc_info=True)

    logger.info("All scrapers done — %d raw postings total", len(raw))

    # 2. Pre-scoring filters (location + student roles + AI/data domain)
    filtered = apply_all(raw)

    # 3. Deduplicate across scrapers
    seen_urls: set[str] = set()
    seen_title_co: list[tuple[str, str]] = []
    unique: list[JobPosting] = []

    for p in filtered:
        if p.url in seen_urls:
            continue
        nt, nc = _norm(p.title), _norm(p.company)
        if nt and any(nt == st and _company_match(nc, sc) for st, sc in seen_title_co):
            logger.debug(
                "Title+company dedup: skipping %r @ %r (duplicate of earlier entry)",
                p.title, p.company,
            )
            continue
        seen_urls.add(p.url)
        seen_title_co.append((nt, nc))
        unique.append(p)

    dupes = len(filtered) - len(unique)
    if dupes:
        logger.info("Cross-scraper dedup: removed %d duplicates → %d unique", dupes, len(unique))

    # 4. Score with Ollama
    score_postings(unique)

    high_score_count = sum(1 for p in unique if p.relevancy_score >= 4)

    # 5. Write to Notion (or print in dry-run mode)
    if dry_run:
        written, skipped = 0, 0
        logger.info("-" * 60)
        logger.info("DRY RUN — %d postings would be written to Notion:", len(unique))
        for p in sorted(unique, key=lambda x: x.relevancy_score, reverse=True):
            logger.info(
                "  [%d] %s @ %s — %s | %s",
                p.relevancy_score, p.title, p.company, p.source, p.match_reason,
            )
    else:
        from notiondb.writer import write_jobs
        written, skipped = write_jobs(unique)

    # 6. Summary
    elapsed = time.monotonic() - start
    logger.info("-" * 60)
    logger.info(
        "Run complete in %.0fs — %d unique postings after filters, "
        "%d scored 4+, %d written to Notion, %d duplicates skipped",
        elapsed,
        len(unique),
        high_score_count,
        written,
        skipped,
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI & Data Job Scraper")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape, filter, and score but don't write to Notion — print results instead",
    )
    args = parser.parse_args()

    try:
        main(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as exc:
        logger.critical("Unhandled exception: %s", exc, exc_info=True)
        sys.exit(1)
