from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, fields
from pathlib import Path
from urllib.parse import quote_plus

from .extractors import (
    parse_duckduckgo_serp,
    parse_github_search,
    parse_google_serp,
    parse_rss_feed,
    parse_whois_text,
)
from .http import create_session, fetch_rendered_html, fetch_text, query_whois_server
from .models import IntelligenceRecord

log = logging.getLogger(__name__)


def build_google_search_url(query: str, limit: int) -> str:
    num = max(1, min(limit, 100))
    return f"https://www.google.com/search?q={quote_plus(query)}&num={num}&hl=en"


def build_duckduckgo_search_url(query: str) -> str:
    return f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"


def build_github_search_url(
    query: str,
    language: str = "",
    topic: str = "",
    limit: int = 25,
) -> str:
    terms = [query.strip()]
    if language.strip():
        terms.append(f"language:{language.strip()}")
    if topic.strip():
        terms.append(f"topic:{topic.strip()}")
    encoded_query = quote_plus(" ".join(term for term in terms if term))
    per_page = max(1, min(limit, 100))
    return f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page={per_page}"


def run_scraper(
    mode: str,
    output: Path,
    limit: int,
    queries: list[str] | None = None,
    feed_urls: list[str] | None = None,
    domains: list[str] | None = None,
    github_language: str = "",
    github_topic: str = "",
    serp_provider: str = "auto",
    serp_browser: str = "never",
    serp_headed: bool = False,
    json_output: Path | None = None,
    timeout: float = 20.0,
    use_env_proxies: bool = False,
) -> list[IntelligenceRecord]:
    session = create_session(use_env_proxies=use_env_proxies)
    records: list[IntelligenceRecord] = []

    if mode == "news":
        for feed_url in feed_urls or []:
            log.info("[news] Fetching %s", feed_url)
            text = fetch_text(session, feed_url, timeout=timeout)
            if text:
                records.extend(parse_rss_feed(text, feed_url, limit))
    elif mode == "github":
        for query in queries or []:
            url = build_github_search_url(query, language=github_language, topic=github_topic, limit=limit)
            log.info("[github] Searching %s", query)
            text = fetch_text(session, url, timeout=timeout)
            if text:
                records.extend(parse_github_search(text, query, limit))
    elif mode == "serp":
        for query in queries or []:
            records.extend(search_serp(session, query, limit, serp_provider, serp_browser, serp_headed, timeout))
    elif mode == "whois":
        for domain in domains or []:
            clean_domain = domain.strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
            if not clean_domain:
                continue
            log.info("[whois] Querying %s", clean_domain)
            text = query_whois_server(clean_domain, timeout=timeout)
            if text:
                records.append(parse_whois_text(clean_domain, text))
    else:
        raise ValueError(f"Unsupported data intelligence mode: {mode}")

    unique = dedupe_records(records)
    write_csv(unique, output)
    if json_output:
        write_json(unique, json_output)
    return unique


def search_serp(
    session: object,
    query: str,
    limit: int,
    provider: str,
    browser_mode: str,
    headed: bool,
    timeout: float,
) -> list[IntelligenceRecord]:
    if provider in {"auto", "google"}:
        url = build_google_search_url(query, limit)
        log.info("[serp/google] Searching %s", query)
        records = _fetch_and_parse_serp(
            session=session,
            url=url,
            query=query,
            limit=limit,
            parser=parse_google_serp,
            browser_mode=browser_mode,
            headed=headed,
            timeout=timeout,
        )
        if records:
            return records
        if provider == "google":
            log.warning("[serp/google] No organic results parsed. Google may have blocked or changed the page.")
            return []
        log.warning("[serp/google] No organic results parsed; falling back to DuckDuckGo HTML.")

    url = build_duckduckgo_search_url(query)
    log.info("[serp/duckduckgo] Searching %s", query)
    records = _fetch_and_parse_serp(
        session=session,
        url=url,
        query=query,
        limit=limit,
        parser=parse_duckduckgo_serp,
        browser_mode=browser_mode,
        headed=headed,
        timeout=timeout,
    )
    if not records:
        log.warning("[serp/duckduckgo] No organic results parsed. The provider may have blocked or changed the page.")
    return records


def _fetch_and_parse_serp(
    session: object,
    url: str,
    query: str,
    limit: int,
    parser,
    browser_mode: str,
    headed: bool,
    timeout: float,
) -> list[IntelligenceRecord]:
    if browser_mode == "always":
        html = fetch_rendered_html(url, timeout=timeout, headless=not headed)
        return parser(html, query, limit) if html else []

    text = fetch_text(session, url, timeout=timeout)
    records = parser(text, query, limit) if text else []
    if records or browser_mode == "never":
        return records

    html = fetch_rendered_html(url, timeout=timeout, headless=not headed)
    return parser(html, query, limit) if html else []


def dedupe_records(records: list[IntelligenceRecord]) -> list[IntelligenceRecord]:
    seen: set[str] = set()
    unique: list[IntelligenceRecord] = []
    for record in records:
        key = record.url if record.url != "N/A" else f"{record.source}|{record.query}|{record.title}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def write_csv(records: list[IntelligenceRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [field.name for field in fields(IntelligenceRecord)]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))
    log.info("Saved %s intelligence records to %s", len(records), output)


def write_json(records: list[IntelligenceRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved JSON output to %s", output)
