from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class IntelligenceRecord:
    source: str
    query: str
    title: str = "N/A"
    url: str = "N/A"
    summary: str = "N/A"
    published: str = "N/A"
    author: str = "N/A"
    score: str = "N/A"
    language: str = "N/A"
    domain: str = "N/A"
    metadata_json: str = "{}"
    fetched_at: str = field(default_factory=utc_now)
