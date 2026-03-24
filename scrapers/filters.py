"""Pre-scoring filters applied to every scraper's output.

Order:
  1. location_filter       — drop jobs clearly outside Region Hovedstaden/Nordsjaelland/Skaane/remote
  2. filter_student_roles  — drop student/internship positions
  3. filter_domain         — drop postings with no AI/data domain keyword in title+description

Filters run before Ollama scoring to avoid wasting LLM calls on irrelevant postings.
"""
import re
from config.logging_config import get_logger
from scrapers import JobPosting
from scrapers.location_filter import filter_location

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Student / unpaid role exclusion
# ---------------------------------------------------------------------------
_STUDENT_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bstudiejob\b",
        r"\bstudenterjob\b",
        r"\bstudent(?:er)?\s+(?:assistant|medarbejder|worker|job|position|stilling)\b",
        r"\bstudentermedarbejder\b",
        r"\bstudentermedhjælper",
        r"\bstudenterstilling\b",
        r"\bstudent\s+assistan[ct]\b",
        r"\bstudent\s+(?:til|i|som|ved)\b",
        r"\bstudent\b",
        r"\bwerkstudent\b",
        r"\bworking\s+student\b",
        r"\bintern(?:ship)?\b",
        r"\bpraktik(?:ant|plads|stilling|forløb)?\b",
        r"\bpraktikan[dt]\b",
        r"\btrainee\b",
        r"\b(?:ulønnet|unpaid)\b",
        r"\bstudent[-/]job\b",
    ]
]

_STUDENT_DESC_REINFORCED_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bstudent\b",
    ]
]

_STUDENT_DESC_CONTEXT_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bstudiejob\b",
        r"\bstudenterjob\b",
        r"\bca\.\s*\d+\s*timer?\s+(?:om\s+)?ugen\b",
        r"\b1[0-9]\s*[-–]\s*2[05]\s*timer?\b",
        r"\bunder\s+(?:din\s+)?uddannelse\b",
        r"\bstudierelevant\b",
        r"\bsom\s+studerende\b",
        r"\bdu\s+(?:er|læser)\s+(?:på\s+)?(?:en\s+)?(?:kandidat|bachelor|cand\.)\b",
    ]
]


def _is_student_role(posting: JobPosting) -> bool:
    title = posting.title or ""
    desc = posting.description or ""

    for pattern in _STUDENT_TITLE_PATTERNS:
        if pattern.search(title):
            return True

    for pattern in _STUDENT_DESC_REINFORCED_PATTERNS:
        if pattern.search(title):
            for ctx in _STUDENT_DESC_CONTEXT_PATTERNS:
                if ctx.search(desc):
                    return True

    return False


def filter_student_roles(postings: list[JobPosting]) -> list[JobPosting]:
    kept, dropped = [], []
    for p in postings:
        if _is_student_role(p):
            dropped.append(p)
        else:
            kept.append(p)

    if dropped:
        logger.info(
            "Student-role filter: kept %d, dropped %d — %s",
            len(kept),
            len(dropped),
            [p.title for p in dropped],
        )
    return kept


# ---------------------------------------------------------------------------
# Domain keyword filter — AI & data focused
# ---------------------------------------------------------------------------
_DOMAIN_KEYWORDS: list[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        # ── AI / ML ───────────────────────────────────────────────────────────
        r"\bAI\b",
        r"\bartificial\s+intelligence\b",
        r"\bmachine\s+learning\b",
        r"\bmaskinlæring",
        r"\bkunstig\s+intelligens",
        r"\bdeep\s+learning\b",
        r"\bneural\s+net",
        r"\bNLP\b",
        r"\bnatural\s+language\s+processing\b",
        r"\bcomputer\s+vision\b",
        r"\bLLM\b",
        r"\blarge\s+language\s+model\b",
        r"\bgenerative\s+AI\b",
        r"\bgenAI\b",
        r"\bMLOps\b",
        r"\bML\s+engineer",
        r"\bagentic\b",
        r"\bRAG\b",
        r"\btransformer",
        r"\breinforcement\s+learning\b",
        r"\bGPT\b",
        r"\bprompt\s+engineer",
        # ── Data ──────────────────────────────────────────────────────────────
        r"\bdata\s+scien",
        r"\bdata\s+engineer",
        r"\bdata\s+analyst",
        r"\bdataanalytiker",
        r"\bdata\s+platform\b",
        r"\bdata\s+architect",
        r"\bdata\s+warehouse\b",
        r"\banalytics\s+engineer",
        r"\bETL\b",
        r"\bELT\b",
        r"\bdbt\b",
        r"\bdata\s+pipeline",
        r"\bdata\s+lake",
        r"\bdata\s+mesh\b",
        r"\bbig\s+data\b",
        r"\bdata\s+governance\b",
        r"\bdata\s+model",
        # ── BI & analytics ────────────────────────────────────────────────────
        r"\bbusiness\s+intelligence\b",
        r"\bBI\b",
        r"\bPower\s*BI\b",
        r"\bDAX\b",
        r"\bTableau\b",
        r"\bLooker\b",
        r"\banalytiker",
        r"\banalyse",
        r"\banalyst\b",
        r"\breporting\b",
        r"\brapportering",
        r"\bdashboard",
        # ── Programming / infrastructure ──────────────────────────────────────
        r"\bPython\b",
        r"\bSQL\b",
        r"\bSpark\b",
        r"\bAirflow\b",
        r"\bKafka\b",
        r"\bSnowflake\b",
        r"\bDatabricks\b",
        r"\bRedshift\b",
        r"\bBigQuery\b",
        r"\bcloud\s+engineer",
        r"\bDevOps\b",
        r"\bMLflow\b",
        r"\bKubeflow\b",
        r"\bTensorFlow\b",
        r"\bPyTorch\b",
        # ── Software engineering (data-adjacent) ─────────────────────────────
        r"\bsoftware\s+engineer",
        r"\bbackend\s+developer",
        r"\bdeveloper\b",
        r"\bengineer\b",
        r"\bautomation\b",
        r"\bautomatisering",
        r"\bdigitalisering",
    ]
]


def _has_domain_keyword(posting: JobPosting) -> bool:
    text = f"{posting.title} {posting.description}"
    return any(p.search(text) for p in _DOMAIN_KEYWORDS)


def filter_domain(postings: list[JobPosting]) -> list[JobPosting]:
    kept, dropped = [], []
    for p in postings:
        if _has_domain_keyword(p):
            kept.append(p)
        else:
            dropped.append(p)

    if dropped:
        logger.info(
            "Domain filter: kept %d, dropped %d — e.g. %s",
            len(kept),
            len(dropped),
            [p.title for p in dropped[:5]],
        )
    return kept


# ---------------------------------------------------------------------------
# Compose all filters
# ---------------------------------------------------------------------------

def apply_all(postings: list[JobPosting]) -> list[JobPosting]:
    """Run every pre-scoring filter in order. Returns the surviving postings."""
    before = len(postings)
    postings = filter_location(postings)
    postings = filter_student_roles(postings)
    postings = filter_domain(postings)
    after = len(postings)
    logger.info("Filters: %d → %d postings (%d removed total)", before, after, before - after)
    return postings
