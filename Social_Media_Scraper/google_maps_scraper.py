#!/usr/bin/env python3
"""Google Maps / Places Business Scraper
==========================================
Scrapes business listings from Google Maps using Playwright to render
the JavaScript-heavy Maps interface, then extracts business data from
the rendered DOM.

Usage:
    python google_maps_scraper.py --query "restaurants in Mumbai"
    python google_maps_scraper.py --query "dentist" --location "Delhi" --limit 20
    python google_maps_scraper.py --query "coffee shop" --location "New York"

Requirements:
    pip install playwright
    python -m playwright install chromium

Architecture:
    Google Maps is entirely JavaScript-rendered. The initial HTML payload
    contains no business listing data — it only has map configuration and
    endpoint URLs. Business results are loaded via subsequent XHR/RPC calls
    that require a full browser engine. This scraper uses Playwright to:
    1. Navigate to the Google Maps search URL
    2. Wait for results to render in the sidebar
    3. Scroll the results panel to load more listings
    4. Extract business data from the rendered DOM elements

Limitations:
    - Requires Playwright + Chromium browser binary.
    - Slower than pure requests-based scrapers (~30–60s per query).
    - Google may occasionally show consent dialogs or CAPTCHAs.
    - Maximum ~20-60 results depending on query popularity.
"""

from __future__ import annotations

import csv
import logging
import random
import re
import sys
import time
import argparse
from dataclasses import dataclass, fields, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_DIR = "output"
DELAY_BETWEEN_QUERIES = (3, 6)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Business:
    search_query: str
    name: str
    category: str
    rating: str
    review_count: str
    address: str
    phone: str
    website: str
    hours: str
    price_level: str
    latitude: str
    longitude: str
    place_id: str
    maps_url: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Clean extracted DOM text."""
    if not text:
        return "N/A"
    text = re.sub(r"\s+", " ", text).strip()
    return text or "N/A"


# ── Playwright-based Google Maps Scraper ──────────────────────────────────────

def scrape_google_maps(
    query: str,
    location: str = "",
    limit: int = 20,
    headless: bool = True,
) -> list[Business]:
    """Scrape Google Maps using Playwright to render the JS-heavy page."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for Google Maps scraping.\n"
            "Install it with: pip install playwright && python -m playwright install chromium"
        )
        return []

    search_query = f"{query} in {location}" if location else query
    url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"

    log.info(f"[Google Maps] Launching browser for: '{search_query}'")
    businesses: list[Business] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            log.warning(f"[Google Maps] Navigation timeout (may still work): {e}")

        # Dismiss consent dialog if present
        try:
            consent_btn = page.locator("button:has-text('Accept all'), button:has-text('Reject all')")
            if consent_btn.count() > 0:
                consent_btn.first.click(timeout=3000)
                page.wait_for_timeout(1500)
        except Exception:
            pass

        # Wait for the results panel to appear
        results_selector = "div[role='feed']"
        try:
            page.wait_for_selector(results_selector, timeout=15000)
        except Exception:
            log.warning("[Google Maps] Results panel did not appear. Trying alternative selector...")
            # Sometimes results are in a different container
            results_selector = "div.m6QErb[aria-label]"
            try:
                page.wait_for_selector(results_selector, timeout=10000)
            except Exception:
                log.error("[Google Maps] Could not find results panel. Google may have blocked the request.")
                browser.close()
                return businesses

        # Scroll the results panel to load more items
        results_panel = page.locator(results_selector).first
        previous_count = 0
        scroll_attempts = 0
        max_scrolls = max(limit // 5, 6)

        while scroll_attempts < max_scrolls:
            # Count current results
            items = page.locator("div[role='feed'] > div > div[jsaction]").all()
            current_count = len(items)

            if current_count >= limit:
                break
            if current_count == previous_count:
                scroll_attempts += 1
                if scroll_attempts >= 3:
                    break
            else:
                scroll_attempts = 0

            previous_count = current_count
            log.info(f"[Google Maps] {current_count} results loaded, scrolling for more...")

            # Scroll the results panel
            try:
                results_panel.evaluate("el => el.scrollTop = el.scrollHeight")
            except Exception:
                try:
                    page.evaluate("""
                        const panel = document.querySelector("div[role='feed']");
                        if (panel) panel.scrollTop = panel.scrollHeight;
                    """)
                except Exception:
                    break

            page.wait_for_timeout(2000)

        # Extract business data from rendered DOM
        log.info(f"[Google Maps] Extracting business data from rendered page...")

        # Each result card is typically an <a> element with an href containing /maps/place/
        result_links = page.locator("a[href*='/maps/place/']").all()
        log.info(f"[Google Maps] Found {len(result_links)} result links")

        for link in result_links[:limit]:
            try:
                biz = _extract_business_from_card(link, query)
                if biz and biz.name != "N/A":
                    businesses.append(biz)
            except Exception as e:
                log.debug(f"[Google Maps] Error extracting card: {e}")
                continue

        # If the link-based approach didn't work, try aria-label approach
        if not businesses:
            log.info("[Google Maps] Trying aria-label extraction...")
            cards = page.locator("div[role='feed'] div[aria-label]").all()
            for card in cards[:limit]:
                try:
                    aria = card.get_attribute("aria-label") or ""
                    if not aria or len(aria) < 3:
                        continue
                    text = card.inner_text()
                    biz = _parse_card_text(aria, text, query)
                    if biz:
                        businesses.append(biz)
                except Exception:
                    continue

        browser.close()

    log.info(f"[Google Maps] Extracted {len(businesses)} businesses for '{search_query}'")
    return businesses


def _extract_business_from_card(link, query: str) -> Optional[Business]:
    """Extract business data from a Google Maps result card link."""
    href = link.get_attribute("href") or ""
    aria_label = link.get_attribute("aria-label") or ""

    # Get the text content of the card
    try:
        text = link.inner_text(timeout=2000)
    except Exception:
        text = ""

    if not aria_label and not text:
        return None

    name = aria_label if aria_label else "N/A"

    # Parse the text content for details
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    rating = "N/A"
    review_count = "N/A"
    category = "N/A"
    address = "N/A"
    phone = "N/A"
    price_level = "N/A"
    hours = "N/A"

    for line in lines:
        # Rating: "4.5(1,234)" or "4.5 (1,234)"
        rating_match = re.match(r"^(\d\.\d)\s*\(?([\d,]+)\)?", line)
        if rating_match:
            rating = rating_match.group(1)
            review_count = rating_match.group(2)
            continue

        # Rating with stars: "4.5"
        if re.match(r"^\d\.\d$", line):
            rating = line
            continue

        # Review count standalone: "(1,234)"
        review_match = re.match(r"^\(?(\d[\d,]+)\)?$", line)
        if review_match and review_count == "N/A":
            review_count = review_match.group(1)
            continue

        # Price level: "$$" or "₹₹"
        if re.match(r"^[₹$€£·\s]+$", line):
            price_level = line.strip()
            continue

        # Phone number
        if re.match(r"^\+?\d[\d\s\-()]{7,}$", line):
            phone = line
            continue

        # Hours: "Open" / "Closed" / "Opens at..."
        if any(h in line.lower() for h in ["open", "closed", "opens", "closes"]):
            hours = line
            continue

        # Category: short text without digits (usually after rating line)
        if category == "N/A" and 2 < len(line) < 40 and not re.search(r"\d{3,}", line):
            if line != name:
                # Check if it looks like a category (e.g., "Restaurant", "Cafe")
                category = line.split(" · ")[0].strip() if " · " in line else line
                continue

        # Address: longer text with numbers
        if address == "N/A" and len(line) > 10 and re.search(r"\d", line):
            if line != name and not re.match(r"^\+?\d[\d\s\-()]{7,}$", line):
                address = line
                continue

    # Extract coordinates from href
    latitude = "N/A"
    longitude = "N/A"
    coord_match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", href)
    if coord_match:
        latitude = coord_match.group(1)
        longitude = coord_match.group(2)

    # Maps URL
    maps_url = href if href.startswith("http") else "N/A"

    # Extract place ID from URL
    place_id = ""
    pid_match = re.search(r"data=.*!1s(0x[a-f0-9]+:0x[a-f0-9]+)", href)
    if pid_match:
        place_id = pid_match.group(1)

    return Business(
        search_query=query,
        name=name,
        category=category,
        rating=rating,
        review_count=review_count,
        address=address,
        phone=phone,
        website="N/A",
        hours=hours,
        price_level=price_level,
        latitude=latitude,
        longitude=longitude,
        place_id=place_id,
        maps_url=maps_url,
    )


def _parse_card_text(name: str, text: str, query: str) -> Optional[Business]:
    """Parse a business card from its aria-label (name) and inner text."""
    if not name or len(name) < 2:
        return None

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    rating = "N/A"
    review_count = "N/A"
    address = "N/A"

    for line in lines:
        rm = re.match(r"(\d\.\d)\s*\(?([\d,]+)\)?", line)
        if rm:
            rating = rm.group(1)
            review_count = rm.group(2)
            continue
        if address == "N/A" and len(line) > 10 and re.search(r"\d", line):
            address = line

    return Business(
        search_query=query, name=name, category="N/A",
        rating=rating, review_count=review_count, address=address,
        phone="N/A", website="N/A", hours="N/A", price_level="N/A",
        latitude="N/A", longitude="N/A", place_id="", maps_url="N/A",
    )


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_to_csv(businesses: list[Business], filepath: Path) -> None:
    if not businesses:
        log.warning("No businesses to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(Business)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for b in businesses:
            writer.writerow(asdict(b))
    log.info(f"Saved {len(businesses)} businesses to '{filepath}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape business listings from Google Maps (Playwright-based)."
    )
    parser.add_argument(
        "-q", "--query", action="append", default=[],
        help="Business search query. Repeat for multiple.",
    )
    parser.add_argument(
        "-l", "--location", default="",
        help="Location context (e.g. 'Mumbai'). Appended to query.",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Maximum results per query (default: 20).",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Run browser in headed (visible) mode for debugging.",
    )
    parser.add_argument(
        "-o", "--output-dir", default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    return parser


def main(
    queries: Optional[list[str]] = None,
    location: str = "",
    limit: int = 20,
    headless: bool = True,
    output_dir: str = OUTPUT_DIR,
) -> int:
    queries = queries or ["restaurants"]
    output_path = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_businesses: list[Business] = []

    for query in queries:
        results = scrape_google_maps(query, location, limit, headless=headless)
        all_businesses.extend(results)
        if len(queries) > 1:
            time.sleep(random.uniform(*DELAY_BETWEEN_QUERIES))

    filepath = output_path / f"google_maps_businesses_{timestamp}.csv"
    save_to_csv(all_businesses, filepath)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  Google Maps Scraper Results")
    print(f"{'=' * 70}")
    for query in queries:
        query_results = [b for b in all_businesses if b.search_query == query]
        print(f"\n  '{query}': {len(query_results)} businesses found")
        for b in query_results[:10]:
            rating_str = f"  {b.rating}/5" if b.rating != "N/A" else ""
            reviews_str = f" ({b.review_count})" if b.review_count != "N/A" else ""
            name_display = b.name[:45] if len(b.name) > 45 else b.name
            print(f"    {name_display:48s}{rating_str}{reviews_str}")
            if b.address != "N/A":
                print(f"      {b.address[:60]}")

    print(f"\n  Total: {len(all_businesses)} businesses")
    print(f"  Output: {filepath.resolve()}")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            queries=args.query or None,
            location=args.location,
            limit=args.limit,
            headless=not args.headed,
            output_dir=args.output_dir,
        )
    )
