"""Location filter — keeps only jobs in Region Hovedstaden, Nordsjælland,
Skåne/southern Sweden, or remote positions within CET/CEST +/-4h.
Jobs with no location data are kept (assumed potentially relevant).

Decision logic per posting:
  1. No location info at all -> KEEP (benefit of the doubt)
  2. Remote signals in title/description -> KEEP
  3. Any city in the ALLOWED set -> KEEP
  4. All cities in the EXCLUDED set -> DISCARD
  5. Otherwise (unknown/ambiguous cities not on either list) -> KEEP
"""
import re
from config.logging_config import get_logger
from scrapers import JobPosting

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Allowed regions
# ---------------------------------------------------------------------------
_ALLOWED_CITIES: frozenset[str] = frozenset({
    # Kobenhavn & Frederiksberg
    "kobenhavn", "copenhagen", "kbh", "frederiksberg",
    # Inner ring (Region Hovedstaden)
    "gentofte", "lyngby", "kongens lyngby", "kgs. lyngby", "kgs lyngby",
    "gladsaxe", "herlev", "ballerup", "rodovre", "glostrup", "brondby",
    "hvidovre", "vallensbaek", "ishoj", "albertslund", "hoje taastrup",
    "hoje-taastrup", "tarnby", "dragor", "kastrup",
    # Northern suburbs & Nordsjaelland
    "hellerup", "charlottenlund", "klampenborg", "soborg", "bagsvaerd",
    "birkerod", "allerod", "hillerod", "helsingor", "elsinore",
    "fredensborg", "frederikssund", "halsnæs", "hundested",
    "gribskov", "gilleleje", "helsinge", "graested",
    "horsholm", "kokkedal", "vedbaek", "holte", "naerum",
    "rudersdal", "fureso", "varlose", "farum", "lillerod",
    "egedal", "smorum", "stenlose",
    # Skaane / southern Sweden
    "malmo", "malmoe",
    "lund",
    "helsingborg",
    "landskrona",
    "vellinge", "trelleborg", "ystad", "kristianstad",
    "skane", "scania",
})

# ---------------------------------------------------------------------------
# Excluded regions
# ---------------------------------------------------------------------------
_EXCLUDED_CITIES: frozenset[str] = frozenset({
    # Jutland
    "aarhus", "arhus", "aarhus c", "aarhus n", "aarhus v",
    "aalborg", "alborg",
    "odense", "odense c",
    "esbjerg", "vejle", "kolding", "silkeborg", "herning",
    "randers", "viborg", "horsens", "skanderborg", "ikast",
    "holstebro", "ringkobing", "struer", "skive", "lemvig",
    "fredericia", "middelfart",
    "haderslev", "sonderborg", "aabenraa", "tonder",
    "thisted", "hjorring", "frederikshavn", "bronderslev",
    "jammerbugt", "rebild", "mariagerfjord", "vesthimmerland",
    "norddjurs", "syddjurs", "favrskov", "hedensted", "odder",
    "morso",
    # Funen / non-CPH islands
    "svendborg", "nyborg", "kerteminde", "nordfyn", "faaborg",
    "faaborg-midtfyn", "assens", "langeland", "aero", "middelfart",
    # Abroad
    "berlin", "hamburg", "munich", "munchen", "frankfurt", "dusseldorf",
    "london", "manchester", "amsterdam", "brussels", "bruxelles",
    "stockholm", "gothenburg", "goteborg", "oslo", "helsinki",
    "paris", "madrid", "barcelona", "warsaw", "prague",
    "new york", "san francisco", "chicago",
    # Danish islands out of scope
    "bornholm", "ronne", "nexo", "gudhjem", "allinge",
})

# ---------------------------------------------------------------------------
# Remote signals
# ---------------------------------------------------------------------------
_REMOTE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bremote\b",
        r"\bfully\s+remote\b",
        r"\b100\s*%\s*remote\b",
        r"\bhome\s*(?:office|based|working)\b",
        r"\bhjemmearbejde\b",
        r"\barbejd(?:e|er)\s+hjemmefra\b",
        r"\bfuldt\s+ud\s+remote\b",
        r"\bwork(?:ing)?\s+from\s+(?:anywhere|home)\b",
        r"\bCE[ST]T?\b",
        r"\bcentral\s+european\s+time\b",
    ]
]


def _normalise_city(raw: str) -> str:
    """Lowercase and strip postal codes and common suffixes for matching."""
    city = raw.lower().strip()
    city = re.sub(r"^\d{4,5}\s*", "", city)
    city = re.sub(r"\s+[oovnsk]$", "", city)
    return city.strip()


def _is_remote(posting: JobPosting) -> bool:
    text = f"{posting.title} {posting.description}"
    return any(p.search(text) for p in _REMOTE_PATTERNS)


def _classify(posting: JobPosting) -> str:
    """Returns 'keep' or 'discard' with a short reason string."""
    location_str = (posting.location or "").strip()

    if not location_str:
        return "keep"

    if _is_remote(posting):
        return "keep"

    raw_cities = [c.strip() for c in location_str.split(",") if c.strip()]
    normalised = [_normalise_city(c) for c in raw_cities]

    if any(c in _ALLOWED_CITIES for c in normalised):
        return "keep"

    if normalised and all(c in _EXCLUDED_CITIES for c in normalised):
        return "discard"

    return "keep"


def filter_location(postings: list[JobPosting]) -> list[JobPosting]:
    kept, dropped = [], []
    for p in postings:
        if _classify(p) == "keep":
            kept.append(p)
        else:
            dropped.append(p)

    if dropped:
        logger.info(
            "Location filter: kept %d, dropped %d",
            len(kept), len(dropped),
        )
        for p in dropped:
            logger.debug("  Location-dropped: %r @ %r", p.title, p.location)

    return kept
