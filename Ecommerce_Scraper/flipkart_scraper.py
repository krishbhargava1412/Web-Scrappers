#!/usr/bin/env python3
"""Flipkart Product Scraper
============================
Scrapes product listings, prices, ratings, and specifications from
Flipkart using Playwright (headless Chromium).

Flipkart aggressively blocks raw HTTP requests (403).  This scraper
launches a real browser to bypass bot-detection, then parses the
rendered DOM with BeautifulSoup.

Usage:
    python flipkart_scraper.py --query "wireless earbuds"
    python flipkart_scraper.py --query "gaming laptop" --query "smartwatch" --output results.csv
    python flipkart_scraper.py --query "phone case" --headed

Requirements:
    pip install playwright beautifulsoup4 lxml
    python -m playwright install chromium
"""

from __future__ import annotations

import csv
import html as html_lib
import logging
import random
import re
import sys
import time
import argparse
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

PRODUCTS_TO_SEARCH = [
    "wireless earbuds",
    "gaming laptop",
]

OUTPUT_FILE = "flipkart_products.csv"

FLIPKART_DOMAIN = "https://www.flipkart.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

DELAY_BETWEEN_REQUESTS = (2, 4)
MAX_RESULTS_PER_PAGE = 40
MAX_PAGES = 3

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class FlipkartProduct:
    search_query: str
    name: str
    price: str
    mrp: str
    discount: str
    rating: str
    review_count: str
    rating_count: str
    highlights: str
    seller: str
    url: str
    image_url: str
    is_assured: str
    is_sponsored: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_headers() -> dict[str, str]:
    """Return request headers.  Kept for API compatibility with price_comparator."""
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def clean_text(value: object) -> str:
    if value is None:
        return "N/A"
    text = html_lib.unescape(str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text or "N/A"


def random_delay() -> None:
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))


# ── Flipkart Playwright Scraper ──────────────────────────────────────────────

def _fetch_page_html(url: str, headless: bool = True) -> Optional[str]:
    """Fetch a Flipkart page using Playwright and return rendered HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for Flipkart scraping.\n"
            "Install: pip install playwright && python -m playwright install chromium"
        )
        return None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-IN",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"[Flipkart] Navigation timeout (may still work): {e}")

        # Wait for product cards to render
        try:
            page.wait_for_selector("div[data-id]", timeout=10000)
        except Exception:
            log.warning("[Flipkart] No product cards loaded within timeout")

        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()
        return html


def parse_flipkart_grid(
    soup: BeautifulSoup,
    query: str,
) -> list[FlipkartProduct]:
    """Parse Flipkart search results from rendered HTML.

    Uses a robust extraction strategy that does NOT depend on Flipkart's
    obfuscated CSS class names (which change every few weeks).  Instead,
    it relies on:
      - ``div[data-id]`` for card boundaries (stable)
      - ``img[alt]`` for product names (stable — the alt text is the title)
      - ``a[href*='/p/']`` for product URLs (stable URL pattern)
      - Regex on card text for ₹-prices, ratings, discounts
    """
    products: list[FlipkartProduct] = []

    cards = soup.select("div[data-id]")
    if not cards:
        return products

    for card in cards:
        try:
            # ── Product name ──
            # The product image alt text is the most reliable name source
            img = card.select_one("img[alt]")
            name = "N/A"
            if img:
                alt = img.get("alt", "").strip()
                if alt and len(alt) > 5:
                    name = alt
            if name == "N/A":
                continue  # skip non-product cards

            # ── URL ──
            href = "N/A"
            link = card.select_one("a[href*='/p/']")
            if link:
                raw = link.get("href", "")
                href = raw if raw.startswith("http") else FLIPKART_DOMAIN + raw

            # ── Image URL ──
            image_url = img.get("src", "N/A") if img else "N/A"

            # ── Prices, rating, discount via text parsing ──
            card_text = card.get_text(separator="|", strip=True)

            # Prices: find all ₹-prefixed numbers
            price_matches = re.findall(r"₹([\d,]+)", card_text)
            price = f"₹{price_matches[0]}" if len(price_matches) >= 1 else "N/A"
            mrp = f"₹{price_matches[1]}" if len(price_matches) >= 2 else "N/A"

            # Discount: "XX% off"
            disc_match = re.search(r"(\d+%)\s*off", card_text, re.IGNORECASE)
            discount = disc_match.group(1) + " off" if disc_match else "N/A"

            # Rating: standalone decimal like "4.1" before a parenthesised count
            rating = "N/A"
            rating_match = re.search(r"\|(\d\.\d)\|", card_text)
            if rating_match:
                rating = rating_match.group(1)
            else:
                # Fallback: any X.X that looks like a rating
                for m in re.finditer(r"(\d\.\d)", card_text):
                    candidate = m.group(1)
                    if 1.0 <= float(candidate) <= 5.0:
                        rating = candidate
                        break

            # Rating / review count: "(XX,XXX)" pattern
            review_count = "N/A"
            rating_count = "N/A"
            count_match = re.search(r"\(([\d,]+)\)", card_text)
            if count_match:
                rating_count = count_match.group(1)

            # ── Flipkart Assured ──
            is_assured = "No"
            if card.select_one("img[alt*='Assured'], img[src*='fa_icon']"):
                is_assured = "Yes"

            # ── Sponsored ──
            is_sponsored = "No"
            if "Sponsored" in card_text or "Ad" == card_text.split("|")[0].strip():
                is_sponsored = "Yes"

            products.append(FlipkartProduct(
                search_query=query,
                name=name,
                price=price,
                mrp=mrp,
                discount=discount,
                rating=rating,
                review_count=review_count,
                rating_count=rating_count,
                highlights="N/A",
                seller="N/A",
                url=href,
                image_url=image_url,
                is_assured=is_assured,
                is_sponsored=is_sponsored,
            ))

        except Exception as e:
            log.debug(f"[Flipkart] Error parsing card: {e}")
            continue

    return products


def scrape_flipkart_search(
    session=None,  # Kept for API compat with price_comparator; unused
    query: str = "",
    max_pages: int = MAX_PAGES,
    headless: bool = True,
) -> list[FlipkartProduct]:
    """Scrape Flipkart search results for a given product query."""
    all_products: list[FlipkartProduct] = []

    for page_num in range(1, max_pages + 1):
        url = f"{FLIPKART_DOMAIN}/search?q={query.replace(' ', '+')}&page={page_num}"
        log.info(f"[Flipkart] Searching '{query}' — page {page_num}")

        html = _fetch_page_html(url, headless=headless)
        if not html:
            log.warning(f"[Flipkart] Failed to fetch page {page_num} for '{query}'")
            break

        soup = BeautifulSoup(html, "lxml")
        products = parse_flipkart_grid(soup, query)

        if not products:
            log.warning(
                f"[Flipkart] No products found on page {page_num} for '{query}' "
                "— may have reached the end."
            )
            break

        all_products.extend(products)
        log.info(f"[Flipkart] Page {page_num}: found {len(products)} products")

        if page_num < max_pages:
            random_delay()

    log.info(f"[Flipkart] Total: {len(all_products)} products for '{query}'")
    return all_products


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_to_csv(products: list[FlipkartProduct], filename: str) -> None:
    if not products:
        log.warning("No products to save.")
        return
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(FlipkartProduct)]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in products:
            writer.writerow(asdict(p))
    log.info(f"Saved {len(products)} products to '{path}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Flipkart product listings (Playwright-based)."
    )
    parser.add_argument(
        "-q", "--query", action="append", default=[],
        help="Product search query. Repeat for multiple queries.",
    )
    parser.add_argument(
        "-o", "--output", default=OUTPUT_FILE,
        help=f"CSV output file (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--max-pages", type=int, default=MAX_PAGES,
        help=f"Maximum search result pages per query (default: {MAX_PAGES}).",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Run browser in headed (visible) mode for debugging.",
    )
    return parser


def main(
    queries: Optional[list[str]] = None,
    output_file: str = OUTPUT_FILE,
    max_pages: int = MAX_PAGES,
    headless: bool = True,
) -> int:
    queries = queries or PRODUCTS_TO_SEARCH
    all_products: list[FlipkartProduct] = []

    for query in queries:
        products = scrape_flipkart_search(
            query=query, max_pages=max_pages, headless=headless
        )
        all_products.extend(products)
        random_delay()

    save_to_csv(all_products, output_file)
    print(f"\nDone! {len(all_products)} products saved to '{output_file}'")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            queries=args.query or None,
            output_file=args.output,
            max_pages=args.max_pages,
            headless=not args.headed,
        )
    )
