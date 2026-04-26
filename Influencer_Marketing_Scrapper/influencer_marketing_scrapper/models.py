from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MarketConfig:
    name: str
    countries: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    niches: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    query: str
    platform: str
    market: str
    engine: str = ""


@dataclass
class SearchDebugRecord:
    market: str
    platform: str
    engine: str
    query: str
    title: str
    raw_url: str
    normalized_url: str
    reason: str


@dataclass
class InfluencerProfile:
    market: str
    platform: str
    profile_url: str
    handle: str
    display_name: str
    bio: str
    followers_text: str
    following_text: str
    posts_text: str
    location_text: str
    email_text: str
    phone_text: str
    website_url: str
    source_query: str
    page_title: str
    meta_description: str
    discovery_title: str
    discovery_snippet: str
    raw_signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
