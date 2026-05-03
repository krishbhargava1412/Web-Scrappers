from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import asdict, fields
from pathlib import Path
from urllib.parse import quote_plus
import re

from bs4 import BeautifulSoup

from .extractors import parse_listing_page
from .http import create_session, fetch_html, fetch_rendered_html
from .models import PropertyListing

log = logging.getLogger(__name__)

SITES = ("magicbricks", "99acres")


def build_search_url(site: str, query: str, location: str, page: int) -> str:
    encoded_query = quote_plus(query)
    encoded_location = quote_plus(location) if location else ""
    if site == "magicbricks":
        return (
            "https://www.magicbricks.com/property-for-sale/residential-real-estate"
            f"?keyword={encoded_query}&cityName={encoded_location}&page={page}"
        )
    if site == "99acres":
        location_slug = _slugify_location(location) if location else "residential-all"
        return (
            f"https://www.99acres.com/search/property/buy/{location_slug}"
            f"?keyword={encoded_query}&preference=S&area_unit=1&res_com=R&page={page}"
        )
    raise ValueError(f"Unsupported real estate site: {site}")


def run_scraper(
    sites: list[str],
    queries: list[str],
    location: str,
    max_pages: int,
    output: Path,
    urls: list[str] | None = None,
    json_output: Path | None = None,
    delay: float = 1.5,
    timeout: float = 20.0,
    use_env_proxies: bool = False,
    browser_mode: str = "auto",
    headed: bool = False,
) -> list[PropertyListing]:
    session = create_session(use_env_proxies=use_env_proxies)
    listings: list[PropertyListing] = []

    targets = build_search_targets(sites, queries, location, max_pages, urls or [])
    for index, (site, query, url) in enumerate(targets, start=1):
        log.info("[%s] Searching '%s' (%s/%s)", site, query, index, len(targets))
        html = fetch_listing_html(
            session=session,
            site=site,
            url=url,
            browser_mode=browser_mode,
            headed=headed,
            timeout=timeout,
        )
        if not html:
            continue
        parsed = parse_listing_page(BeautifulSoup(html, "lxml"), site, query, location, url)
        if not parsed:
            log.warning("[%s] No listings found for '%s' at %s", site, query, url)
            if site == "99acres" and query != "direct-url":
                log.warning(
                    "[99acres] If this opens a 'no page found' page, run a search manually on 99acres, "
                    "copy the results URL, and pass it with --url."
                )
            continue
        listings.extend(parsed)
        if index < len(targets):
            time.sleep(delay)

    unique = dedupe_listings(listings)
    write_csv(unique, output)
    if json_output:
        write_json(unique, json_output)
    return unique


def build_search_targets(
    sites: list[str],
    queries: list[str],
    location: str,
    max_pages: int,
    urls: list[str],
) -> list[tuple[str, str, str]]:
    raw_urls = [url.strip() for url in urls if url.strip()]
    if raw_urls:
        return [(_site_from_url(url), "direct-url", url) for url in raw_urls]

    targets: list[tuple[str, str, str]] = []
    for site in sites:
        for query in queries:
            for page in range(1, max_pages + 1):
                targets.append((site, query, build_search_url(site, query, location, page)))
    return targets


def _slugify_location(location: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")
    return slug or "residential-all"


def _site_from_url(url: str) -> str:
    if "99acres.com" in url:
        return "99acres"
    if "magicbricks.com" in url:
        return "magicbricks"
    return "99acres"


def fetch_listing_html(
    session: object,
    site: str,
    url: str,
    browser_mode: str,
    headed: bool,
    timeout: float,
) -> str | None:
    if browser_mode == "always":
        return fetch_rendered_html(url, timeout=timeout, headless=not headed)

    html = fetch_html(session, url, timeout=timeout)
    if html or browser_mode == "never":
        return html

    if site == "99acres" and browser_mode == "auto":
        log.info("[99acres] Requests fetch was blocked or empty; retrying with Chromium")
        return fetch_rendered_html(url, timeout=timeout, headless=not headed)

    return None


def dedupe_listings(listings: list[PropertyListing]) -> list[PropertyListing]:
    seen: set[str] = set()
    unique: list[PropertyListing] = []
    for listing in listings:
        key = listing.url if listing.url != "N/A" else "|".join(
            [listing.title.lower(), listing.locality.lower(), listing.city.lower()]
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


def write_csv(listings: list[PropertyListing], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [field.name for field in fields(PropertyListing)]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for listing in listings:
            writer.writerow(asdict(listing))
    log.info("Saved %s property listings to %s", len(listings), output)


def write_json(listings: list[PropertyListing], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(listing) for listing in listings]
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved JSON output to %s", output)
