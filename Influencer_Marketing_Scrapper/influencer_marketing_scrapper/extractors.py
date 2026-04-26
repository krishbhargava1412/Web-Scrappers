from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import InfluencerProfile, SearchResult


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
FOLLOWER_RE = re.compile(r"(\d[\d.,]*\s*[KMB]?)\s+(followers|subscribers)", re.I)
FOLLOWING_RE = re.compile(r"(\d[\d.,]*\s*[KMB]?)\s+following", re.I)
POSTS_RE = re.compile(r"(\d[\d.,]*\s*[KMB]?)\s+(posts|videos)", re.I)


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.select_one(f'meta[property="{name}"], meta[name="{name}"]')
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _json_ld_blocks(soup: BeautifulSoup) -> list[dict]:
    blocks: list[dict] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, list):
            blocks.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def _first_match(pattern: re.Pattern[str], *values: str) -> str:
    for value in values:
        match = pattern.search(value or "")
        if match:
            return match.group(1 if match.lastindex else 0).strip()
    return ""


def _find_contact(text: str) -> tuple[str, str]:
    email = _first_match(EMAIL_RE, text)
    phone = _first_match(PHONE_RE, text)
    return email, phone


def _extract_handle(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    for part in path.split("/"):
        if part and part not in {"in", "channel", "c", "user", "pages", "people"}:
            return part
    return path.split("/")[0]


def extract_profile(html: str, result: SearchResult) -> InfluencerProfile:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = _meta_content(soup, "description", "og:description", "twitter:description")
    og_title = _meta_content(soup, "og:title", "twitter:title")
    body_text = soup.get_text(" ", strip=True)
    json_ld = _json_ld_blocks(soup)

    json_names = [
        block.get("name", "")
        for block in json_ld
        if isinstance(block.get("name"), str)
    ]
    json_descriptions = [
        block.get("description", "")
        for block in json_ld
        if isinstance(block.get("description"), str)
    ]
    json_urls = [
        block.get("url", "")
        for block in json_ld
        if isinstance(block.get("url"), str)
    ]

    email, phone = _find_contact(" ".join([body_text, description, *json_descriptions]))
    website_url = next((value for value in json_urls if value and value != result.url), "")

    return InfluencerProfile(
        market=result.market,
        platform=result.platform,
        profile_url=result.url,
        handle=_extract_handle(result.url),
        display_name=next(
            (value for value in [og_title, title, *json_names] if value),
            "",
        ),
        bio=next((value for value in [description, *json_descriptions] if value), ""),
        followers_text=_first_match(FOLLOWER_RE, body_text, description),
        following_text=_first_match(FOLLOWING_RE, body_text, description),
        posts_text=_first_match(POSTS_RE, body_text, description),
        location_text="",
        email_text=email,
        phone_text=phone,
        website_url=website_url,
        source_query=result.query,
        page_title=title,
        meta_description=description,
        discovery_title=result.title,
        discovery_snippet=result.snippet,
        raw_signals={
            "json_ld_types": [block.get("@type", "") for block in json_ld],
            "meta_title": og_title,
        },
    )
