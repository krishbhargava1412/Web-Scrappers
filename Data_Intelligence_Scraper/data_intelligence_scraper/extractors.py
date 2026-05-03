from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from .models import IntelligenceRecord


def clean_text(value: object) -> str:
    if value is None:
        return "N/A"
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or "N/A"


def parse_rss_feed(xml_text: str, feed_url: str, limit: int) -> list[IntelligenceRecord]:
    root = ET.fromstring(xml_text)
    records: list[IntelligenceRecord] = []

    channel_title = clean_text(root.findtext("./channel/title"))
    items = root.findall("./channel/item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for item in items[:limit]:
        is_atom = item.tag.endswith("entry")
        title = clean_text(_find_text(item, ["title"]))
        link = _extract_link(item, is_atom=is_atom)
        summary = clean_text(_find_text(item, ["description", "summary", "content"]))
        published = clean_text(_find_text(item, ["pubDate", "published", "updated"]))
        author = clean_text(_find_text(item, ["author", "creator"]))
        records.append(
            IntelligenceRecord(
                source="news",
                query=feed_url,
                title=title,
                url=link,
                summary=summary,
                published=published,
                author=author,
                domain=_domain_from_url(feed_url),
                metadata_json=json.dumps({"feed_title": channel_title}, ensure_ascii=False),
            )
        )
    return records


def parse_github_search(json_text: str, query: str, limit: int) -> list[IntelligenceRecord]:
    payload = json.loads(json_text)
    records: list[IntelligenceRecord] = []
    for item in payload.get("items", [])[:limit]:
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        metadata = {
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "license": (item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), dict) else None,
        }
        records.append(
            IntelligenceRecord(
                source="github",
                query=query,
                title=clean_text(item.get("full_name")),
                url=clean_text(item.get("html_url")),
                summary=clean_text(item.get("description")),
                published=clean_text(item.get("updated_at")),
                author=clean_text(owner.get("login")),
                score=f"{item.get('stargazers_count', 0)} stars, {item.get('forks_count', 0)} forks",
                language=clean_text(item.get("language")),
                domain="github.com",
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        )
    return records


def parse_google_serp(html: str, query: str, limit: int) -> list[IntelligenceRecord]:
    soup = BeautifulSoup(html, "lxml")
    records: list[IntelligenceRecord] = []
    for block in soup.select("div.g"):
        title_node = block.select_one("h3")
        link_node = title_node.find_parent("a") if title_node else block.select_one("a[href]")
        if not title_node or not link_node:
            continue
        url = _normalize_google_url(clean_text(link_node.get("href")))
        if not url.startswith("http"):
            continue
        summary_node = block.select_one(".VwiC3b, .IsZvec, span.aCOpRe")
        records.append(
            IntelligenceRecord(
                source="serp",
                query=query,
                title=clean_text(title_node.get_text(" ", strip=True)),
                url=url,
                summary=clean_text(summary_node.get_text(" ", strip=True) if summary_node else None),
                domain=_domain_from_url(url),
            )
        )
        if len(records) >= limit:
            break
    return records


def parse_duckduckgo_serp(html: str, query: str, limit: int) -> list[IntelligenceRecord]:
    soup = BeautifulSoup(html, "lxml")
    records: list[IntelligenceRecord] = []
    for block in soup.select(".result, .web-result"):
        link_node = block.select_one(".result__a, a.result__url, a[href]")
        if not link_node:
            continue
        url = _normalize_duckduckgo_url(clean_text(link_node.get("href")))
        if not url.startswith("http"):
            continue
        snippet_node = block.select_one(".result__snippet, .result__body")
        records.append(
            IntelligenceRecord(
                source="serp",
                query=query,
                title=clean_text(link_node.get_text(" ", strip=True)),
                url=url,
                summary=clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else None),
                domain=_domain_from_url(url),
                metadata_json=json.dumps({"provider": "duckduckgo"}, ensure_ascii=False),
            )
        )
        if len(records) >= limit:
            break
    return records


def parse_whois_text(domain: str, text: str) -> IntelligenceRecord:
    registrar = _first_field(text, ["Registrar", "Sponsoring Registrar"])
    created = _first_field(text, ["Creation Date", "Created On", "Registered On"])
    expires = _first_field(text, ["Registry Expiry Date", "Expiration Date", "Expiry Date"])
    nameservers = _fields(text, ["Name Server", "nserver"])
    metadata = {
        "registrar": registrar,
        "created": created,
        "expires": expires,
        "nameservers": nameservers,
    }
    summary_parts = [part for part in [registrar, f"Created: {created}" if created != "N/A" else "", f"Expires: {expires}" if expires != "N/A" else ""] if part]
    return IntelligenceRecord(
        source="whois",
        query=domain,
        title=domain,
        summary="; ".join(summary_parts) or "N/A",
        domain=domain,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )


def _find_text(item: ET.Element, names: list[str]) -> str | None:
    for node in item.iter():
        tag = node.tag.split("}", 1)[-1].lower()
        if tag in {name.lower() for name in names} and node.text:
            return node.text
    return None


def _extract_link(item: ET.Element, is_atom: bool) -> str:
    if is_atom:
        for node in item.iter():
            if node.tag.endswith("link") and node.attrib.get("href"):
                return clean_text(node.attrib["href"])
    return clean_text(_find_text(item, ["link"]))


def _normalize_google_url(url: str) -> str:
    if url.startswith("/url?"):
        parsed = parse_qs(urlparse(url).query)
        return clean_text((parsed.get("q") or [""])[0])
    return url


def _normalize_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = (parse_qs(parsed.query).get("uddg") or [""])[0]
        return clean_text(unquote(target))
    return url


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or "N/A"


def _first_field(text: str, names: list[str]) -> str:
    values = _fields(text, names)
    return values[0] if values else "N/A"


def _fields(text: str, names: list[str]) -> list[str]:
    found: list[str] = []
    lowered_names = [name.lower() for name in names]
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() in lowered_names:
            cleaned = clean_text(value)
            if cleaned != "N/A" and cleaned not in found:
                found.append(cleaned)
    return found
