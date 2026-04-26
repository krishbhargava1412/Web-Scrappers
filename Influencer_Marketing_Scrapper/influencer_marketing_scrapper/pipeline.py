from __future__ import annotations

import csv
import json
import logging
import random
from datetime import datetime
from pathlib import Path

from .discovery import discover_profiles
from .extractors import extract_profile
from .http import FetchSettings, HttpClient
from .models import InfluencerProfile, MarketConfig, SearchDebugRecord, SearchResult

log = logging.getLogger(__name__)


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_profiles(profiles: list[InfluencerProfile]) -> list[InfluencerProfile]:
    seen: set[tuple[str, str]] = set()
    deduped: list[InfluencerProfile] = []

    for profile in profiles:
        key = (profile.platform, profile.profile_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(profile)

    return deduped


def _write_outputs(output_dir: Path, profiles: list[InfluencerProfile], summary: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "profiles.csv"
    jsonl_path = output_dir / "profiles.jsonl"
    summary_path = output_dir / "run_summary.json"

    fieldnames = [
        "market",
        "platform",
        "profile_url",
        "handle",
        "display_name",
        "bio",
        "followers_text",
        "following_text",
        "posts_text",
        "location_text",
        "email_text",
        "phone_text",
        "website_url",
        "source_query",
        "page_title",
        "meta_description",
        "discovery_title",
        "discovery_snippet",
    ]

    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for profile in profiles:
            row = {name: _safe_text(getattr(profile, name)) for name in fieldnames}
            writer.writerow(row)

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for profile in profiles:
            handle.write(json.dumps(profile.to_dict(), ensure_ascii=False) + "\n")

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _write_search_debug(output_dir: Path, debug_records: list[SearchDebugRecord]) -> None:
    debug_path = output_dir / "search_debug.csv"
    fieldnames = [
        "market",
        "platform",
        "engine",
        "query",
        "title",
        "raw_url",
        "normalized_url",
        "reason",
    ]
    with debug_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in debug_records:
            writer.writerow({
                "market": record.market,
                "platform": record.platform,
                "engine": record.engine,
                "query": record.query,
                "title": record.title,
                "raw_url": record.raw_url,
                "normalized_url": record.normalized_url,
                "reason": record.reason,
            })


def _load_seen_urls(history_file: Path) -> set[str]:
    if not history_file.exists():
        return set()

    with history_file.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        str(row.get("profile_url", "")).strip()
        for row in rows
        if str(row.get("profile_url", "")).strip()
    }


def _append_seen_profiles(history_file: Path, profiles: list[InfluencerProfile]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_seen_urls(history_file)
    write_header = not history_file.exists()

    with history_file.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["market", "platform", "profile_url", "handle", "display_name", "saved_at"],
        )
        if write_header:
            writer.writeheader()

        for profile in profiles:
            if profile.profile_url in existing:
                continue
            writer.writerow({
                "market": profile.market,
                "platform": profile.platform,
                "profile_url": profile.profile_url,
                "handle": profile.handle,
                "display_name": profile.display_name,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            })
            existing.add(profile.profile_url)


def _load_seed_results(
    seed_file: Path,
    market: MarketConfig,
    platform_filter: set[str],
) -> tuple[list[SearchResult], list[SearchDebugRecord]]:
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file}")

    if seed_file.suffix.lower() == ".json":
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("profiles", [])
    else:
        with seed_file.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    results: list[SearchResult] = []
    debug_records: list[SearchDebugRecord] = []

    for row in rows:
        url = str(row.get("url", "") or row.get("profile_url", "")).strip()
        platform = str(row.get("platform", "")).strip().lower()
        title = str(row.get("title", "") or row.get("display_name", "") or url).strip()
        query = str(row.get("query", "") or row.get("source_query", "") or "seed_file").strip()

        if not url or not platform:
            continue
        if platform not in platform_filter:
            continue

        result = SearchResult(
            title=title,
            url=url,
            snippet=str(row.get("snippet", "")).strip(),
            query=query,
            platform=platform,
            market=market.name,
            engine="seed_file",
        )
        results.append(result)
        debug_records.append(
            SearchDebugRecord(
                market=market.name,
                platform=platform,
                engine="seed_file",
                query=query,
                title=title,
                raw_url=url,
                normalized_url=url,
                reason="accepted_seed",
            )
        )

    return results, debug_records


def run_market_scrape(
    market: MarketConfig,
    output_root: Path,
    platforms: list[str],
    limit_per_query: int,
    fetch_settings: FetchSettings,
    search_engines: list[str],
    max_queries_per_platform: int | None,
    seed_file: Path | None = None,
    history_file: Path | None = None,
    stop_after_empty_queries: int | None = None,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / f"{market.name}_{timestamp}"

    client = HttpClient(fetch_settings)
    discovered_total = 0
    fetched_total = 0
    profiles: list[InfluencerProfile] = []
    search_debug_records: list[SearchDebugRecord] = []
    seeded_results: dict[str, list[SearchResult]] = {}
    history_path = history_file or (output_root / "seen_profiles.csv")
    seen_urls = _load_seen_urls(history_path)

    if seed_file is not None:
        loaded_results, loaded_debug = _load_seed_results(seed_file, market, set(platforms))
        search_debug_records.extend(loaded_debug)
        for result in loaded_results:
            seeded_results.setdefault(result.platform, []).append(result)

    for platform in platforms:
        log.info("[%s] Starting platform: %s", market.name, platform)
        if platform in seeded_results:
            results = seeded_results[platform]
            log.info("[%s] Using %s seeded profile URL(s) for %s", market.name, len(results), platform)
        else:
            results = discover_profiles(
                client,
                market,
                platform,
                limit_per_query,
                search_engines,
                max_queries_per_platform,
                stop_after_empty_queries,
            )
            search_debug_records.extend(getattr(discover_profiles, "debug_records", []))
        random.shuffle(results)
        fresh_results = [result for result in results if result.url not in seen_urls]
        skipped_repeats = len(results) - len(fresh_results)
        discovered_total += len(fresh_results)
        log.info("[%s] Discovered %s candidate profile URL(s) on %s", market.name, len(fresh_results), platform)
        if skipped_repeats:
            log.info("[%s] Skipped %s previously seen profile URL(s) on %s", market.name, skipped_repeats, platform)

        for result in fresh_results:
            html = client.get_text(result.url)
            client.pause()
            if not html:
                log.warning("[%s] Skipping unreachable profile: %s", market.name, result.url)
                continue

            fetched_total += 1
            profile = extract_profile(html, result)
            profiles.append(profile)
            seen_urls.add(result.url)
        log.info("[%s] Finished platform %s with %s saved profile(s) so far", market.name, platform, len(profiles))

    profiles = _dedupe_profiles(profiles)
    summary = {
        "market": market.name,
        "countries": market.countries,
        "languages": market.languages,
        "niches": market.niches,
        "platforms": platforms,
        "search_engines": search_engines,
        "seed_file": str(seed_file) if seed_file else "",
        "history_file": str(history_path),
        "search_terms": market.search_terms,
        "discovered_results": discovered_total,
        "fetched_profiles": fetched_total,
        "saved_profiles": len(profiles),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_outputs(output_dir, profiles, summary)
    _write_search_debug(output_dir, search_debug_records)
    _append_seen_profiles(history_path, profiles)
    return output_dir
