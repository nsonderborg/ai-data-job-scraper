from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobPosting:
    title: str
    company: str
    url: str
    source: str
    description: str = ""
    deadline: Optional[str] = None
    # Comma-separated city/location string populated by each scraper
    location: str = ""
    # Filled in by scoring phase
    relevancy_score: int = 0
    match_reason: str = ""
