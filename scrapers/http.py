"""Shared HTTP session with automatic retry-with-backoff.

All scrapers import get_session() and use it instead of requests.get/post
directly. One session is created per process (lazy singleton).

Retry policy:
  - 3 retries on transient errors: 429, 500, 502, 503, 504
  - Exponential backoff: 0 s, 2 s, 4 s  (backoff_factor=2)
  - GET and POST methods retried
  - raise_on_status=False — callers still call r.raise_for_status() so
    non-retried 4xx errors surface normally
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session: requests.Session | None = None

_RETRY = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist={429, 500, 502, 503, 504},
    allowed_methods={"GET", "POST"},
    raise_on_status=False,
)


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session
