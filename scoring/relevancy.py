"""Relevancy scoring via local Ollama (llama3.2).

For each JobPosting:
  - Sends a structured prompt to Ollama with job title + description and the
    candidate profile.
  - Expects a JSON response: {"score": 1-5, "match_reason": "..."}
  - Attaches score and match_reason back to the posting in-place.
  - If Ollama is unavailable or returns unparseable output: score=0,
    match_reason="Scoring unavailable" — posting is still written to Notion
    so it can be reviewed manually.

Timeout: 30 s per posting.
"""

import json
import re
from typing import Optional

import requests

from config.settings import OLLAMA_URL, OLLAMA_MODEL
from config.logging_config import get_logger
from scrapers import JobPosting

logger = get_logger(__name__)

_HEALTH_URL = OLLAMA_URL.replace("/api/generate", "/api/tags")

# ─────────────────────────────────────────────────────────────────────────────
# Candidate profile — AI & data focus
# ─────────────────────────────────────────────────────────────────────────────

_PROFILE = """
Candidate: Nikolas Nogueira Sonderborg
Education: MSc Applied Economics & Finance, Copenhagen Business School (2025)
Core skills: Python, SQL, Power BI, DAX, machine learning, financial modeling,
  data analysis, statistics, pandas, scikit-learn, TensorFlow
Recent role: FP&A Associate at a real estate company — built Power BI
  infrastructure, KPI dashboards, automated reporting pipelines
Prior experience: Investment Analyst at a Danish VC (Coop Invest Venture),
  Junior Consultant at NNIT A/S
Pivot direction: AI/ML engineering, data science, data engineering, analytics
  engineering — roles combining quantitative skills with AI/data tooling

HARD SCORE CAPS (apply before everything else):
  - If this is a student, intern, trainee, or praktik position
    (studiejob, praktikant, trainee, student assistant, internship, student position,
    studenterstilling, studentermedhjælper, or any role explicitly for students) → score MUST be 1.
    Do not let a relevant topic area raise it above 1.
  - If this role requires 8+ years of experience OR carries a title like
    Director, VP, Vice President, Head of, Partner, C-suite (CEO, CFO, CTO, COO),
    Afdelingsleder, Chefkonsulent, or equivalent seniority → score MUST be at most 2.

Scoring guide (after applying hard caps above):
  5 — Perfect fit: data scientist, ML engineer, AI engineer, MLOps engineer,
      analytics engineer, data engineer with Python/ML focus, applied AI roles
  4 — Strong fit: data analyst with Python/ML scope, BI developer with data
      engineering, NLP/computer vision engineer, cloud/data platform engineer
  3 — Acceptable: general data analyst, business intelligence developer,
      backend developer with data focus, DevOps with data platform
  2 — Weak fit: pure frontend developer, pure accounting, generic IT support,
      project management without data/AI scope
  1 — Not a fit: student/intern/trainee positions, HR, pure sales,
      completely unrelated fields
""".strip()

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def score_postings(postings: list[JobPosting]) -> None:
    """Score all postings in-place. Skips if Ollama is unreachable."""
    if not postings:
        return

    if not _ollama_available():
        logger.warning(
            "Ollama not reachable at %s — all %d postings get score=0",
            OLLAMA_URL,
            len(postings),
        )
        for p in postings:
            p.relevancy_score = 0
            p.match_reason = "Scoring unavailable (Ollama offline)"
        return

    logger.info("Scoring %d postings via Ollama (%s)", len(postings), OLLAMA_MODEL)
    scored = skipped = 0

    for posting in postings:
        result = _score_one(posting)
        posting.relevancy_score = result["score"]
        posting.match_reason = result["match_reason"]
        if result["score"] > 0:
            scored += 1
        else:
            skipped += 1

    logger.info(
        "Scoring complete: %d scored, %d failed/skipped", scored, skipped
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ollama health check
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        r = requests.get(_HEALTH_URL, timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Scoring a single posting
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """\
You are a career advisor. Given the candidate profile and a job posting, \
rate how relevant the job is for the candidate on a scale of 1 to 5.

CANDIDATE PROFILE:
{profile}

JOB POSTING:
Title: {title}
Company: {company}
Description: {description}

Respond ONLY with a JSON object — no markdown, no explanation outside the JSON:
{{"score": <integer 1-5>, "match_reason": "<two concise sentences explaining the score>"}}
"""


def _score_one(posting: JobPosting) -> dict:
    prompt = _PROMPT_TEMPLATE.format(
        profile=_PROFILE,
        title=posting.title,
        company=posting.company or "Unknown",
        description=(posting.description or "No description provided.")[:800],
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=30)
        r.raise_for_status()
    except requests.Timeout:
        logger.warning("Ollama timeout for %r", posting.title)
        return _fallback("Scoring timed out")
    except requests.RequestException as exc:
        logger.warning("Ollama request failed for %r: %s", posting.title, exc)
        return _fallback("Scoring request failed")

    raw = r.json().get("response", "")
    return _parse_response(raw, posting.title)


def _parse_response(raw: str, title: str) -> dict:
    """Extract {score, match_reason} from Ollama's raw response string."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        return _validate(data, title)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return _validate(data, title)
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse Ollama JSON for %r — raw: %.200s", title, raw)
    return _fallback("Unparseable scoring response")


def _validate(data: dict, title: str) -> dict:
    """Clamp score to 1-5 and ensure match_reason is a non-empty string."""
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    score = max(0, min(5, score))

    reason = str(data.get("match_reason") or "").strip()
    if not reason:
        reason = "No reason provided"

    if score == 0:
        logger.warning("Ollama returned score=0 for %r", title)

    return {"score": score, "match_reason": reason}


def _fallback(reason: str) -> dict:
    return {"score": 0, "match_reason": reason}
