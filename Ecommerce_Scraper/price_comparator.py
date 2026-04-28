#!/usr/bin/env python3
"""E-Commerce Price Comparator
================================
Cross-platform price comparison that searches Amazon India, Amazon US,
Flipkart, and the existing IndiaMart/Alibaba scrapers, then outputs a
unified comparison CSV sorted by price.

Usage:
    python price_comparator.py --query "wireless earbuds"
    python price_comparator.py --query "laptop" --site all --output comparison.csv
    python price_comparator.py --query "phone case" --site amazon_india --site flipkart

Requirements:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import csv
import logging
import argparse
import re
import sys
from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Optional

import requests

# ── Local imports (sibling modules) ───────────────────────────────────────────
# Ensure the parent directory is on sys.path so we can import siblings.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from amazon_scraper import (
    scrape_amazon_search,
    get_headers as amazon_get_headers,
    AmazonProduct,
)
from flipkart_scraper import (
    scrape_flipkart_search,
    get_headers as flipkart_get_headers,
    FlipkartProduct,
)

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_FILE = "price_comparison.csv"

AVAILABLE_SITES = [
    "amazon_india",
    "amazon_us",
    "flipkart",
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Unified Data Model ───────────────────────────────────────────────────────

@dataclass
class ComparedProduct:
    search_query: str
    source: str
    name: str
    price_raw: str
    price_numeric: float
    currency: str
    mrp: str
    discount: str
    rating: str
    review_count: str
    url: str
    image_url: str


# ── Price Normalization ───────────────────────────────────────────────────────

def parse_numeric_price(price_str: str) -> float:
    """Convert a price string like '₹1,299.00' or '$49.99' to a float.
    Returns -1.0 if parsing fails (so N/A products sort to the bottom).
    """
    if not price_str or price_str == "N/A":
        return -1.0
    cleaned = re.sub(r"[₹$€£,\s]", "", price_str.strip())
    match = re.search(r"[\d]+\.?\d*", cleaned)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return -1.0
    return -1.0


def detect_currency(price_str: str, source: str) -> str:
    """Detect currency from the price string or infer from source."""
    if "₹" in price_str:
        return "INR"
    if "$" in price_str:
        return "USD"
    if "€" in price_str:
        return "EUR"
    if "£" in price_str:
        return "GBP"
    # Infer from source
    if "india" in source.lower() or "flipkart" in source.lower() or "indiamart" in source.lower():
        return "INR"
    if "us" in source.lower() or "alibaba" in source.lower():
        return "USD"
    return "N/A"


# ── Normalizers ───────────────────────────────────────────────────────────────

def normalize_amazon(product: AmazonProduct) -> ComparedProduct:
    source = f"Amazon {product.region.upper()}"
    price_numeric = parse_numeric_price(product.price)
    return ComparedProduct(
        search_query=product.search_query,
        source=source,
        name=product.name,
        price_raw=product.price,
        price_numeric=price_numeric,
        currency=detect_currency(product.price, source),
        mrp=product.mrp,
        discount=product.discount,
        rating=product.rating,
        review_count=product.review_count,
        url=product.url,
        image_url=product.image_url,
    )


def normalize_flipkart(product: FlipkartProduct) -> ComparedProduct:
    price_numeric = parse_numeric_price(product.price)
    return ComparedProduct(
        search_query=product.search_query,
        source="Flipkart",
        name=product.name,
        price_raw=product.price,
        price_numeric=price_numeric,
        currency="INR",
        mrp=product.mrp,
        discount=product.discount,
        rating=product.rating,
        review_count=product.review_count,
        url=product.url,
        image_url=product.image_url,
    )


# ── Core Comparison Engine ────────────────────────────────────────────────────

def compare_prices(
    queries: list[str],
    sites: list[str],
    max_pages: int = 1,
    use_env_proxies: bool = False,
) -> list[ComparedProduct]:
    """Run scrapers across selected sites and return a unified, sorted list."""
    all_results: list[ComparedProduct] = []

    session = requests.Session()
    session.trust_env = use_env_proxies

    for query in queries:
        # Amazon India
        if "all" in sites or "amazon_india" in sites:
            log.info(f"Comparing on Amazon India: '{query}'")
            session.headers.update(amazon_get_headers())
            amazon_in = scrape_amazon_search(
                session, query, "india", max_pages=max_pages, max_results=10
            )
            all_results.extend(normalize_amazon(p) for p in amazon_in)

        # Amazon US
        if "all" in sites or "amazon_us" in sites:
            log.info(f"Comparing on Amazon US: '{query}'")
            session.headers.update(amazon_get_headers())
            amazon_us = scrape_amazon_search(
                session, query, "us", max_pages=max_pages, max_results=10
            )
            all_results.extend(normalize_amazon(p) for p in amazon_us)

        # Flipkart
        if "all" in sites or "flipkart" in sites:
            log.info(f"Comparing on Flipkart: '{query}'")
            session.headers.update(flipkart_get_headers())
            flipkart = scrape_flipkart_search(session, query, max_pages=max_pages)
            all_results.extend(normalize_flipkart(p) for p in flipkart)

    # Sort: products with valid prices first, ascending; N/A at the end
    all_results.sort(
        key=lambda p: (p.price_numeric < 0, p.price_numeric, p.source)
    )

    return all_results


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_comparison_csv(results: list[ComparedProduct], filename: str) -> None:
    if not results:
        log.warning("No comparison results to save.")
        return
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(ComparedProduct)]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in results:
            writer.writerow(asdict(item))
    log.info(f"Saved {len(results)} comparison results to '{path}'")


# ── Summary Printer ───────────────────────────────────────────────────────────

def print_summary(results: list[ComparedProduct], query: str) -> None:
    """Print a quick comparison summary to stdout."""
    query_results = [r for r in results if r.search_query == query and r.price_numeric > 0]
    if not query_results:
        print(f"\n  No valid prices found for '{query}'")
        return

    print(f"\n{'─' * 80}")
    print(f"  Price Comparison: '{query}'")
    print(f"{'─' * 80}")
    print(f"  {'Source':<18} {'Price':>12} {'Rating':>8}  Name")
    print(f"  {'─' * 16}   {'─' * 10}  {'─' * 6}  {'─' * 40}")

    for item in query_results[:15]:
        name = item.name[:45] + "..." if len(item.name) > 48 else item.name
        price_display = f"{item.currency} {item.price_numeric:,.2f}" if item.price_numeric > 0 else "N/A"
        print(f"  {item.source:<18} {price_display:>12} {item.rating:>8}  {name}")

    # Best deal
    best = query_results[0]
    print(f"\n  💰 Best price: {best.currency} {best.price_numeric:,.2f} on {best.source}")
    print(f"     {best.name[:70]}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare product prices across Amazon and Flipkart."
    )
    parser.add_argument(
        "-q", "--query",
        action="append",
        default=[],
        help="Product search query. Repeat for multiple queries.",
    )
    parser.add_argument(
        "-o", "--output",
        default=OUTPUT_FILE,
        help=f"CSV output file (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--site",
        action="append",
        default=[],
        choices=["all"] + AVAILABLE_SITES,
        help="Sites to compare. Repeat to add multiple. Default: all.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max search result pages per site per query (default: 1).",
    )
    parser.add_argument(
        "--use-env-proxies",
        action="store_true",
        help="Honor HTTP(S)_PROXY environment variables.",
    )
    return parser


def main(
    queries: Optional[list[str]] = None,
    output_file: str = OUTPUT_FILE,
    sites: Optional[list[str]] = None,
    max_pages: int = 1,
    use_env_proxies: bool = False,
) -> int:
    queries = queries or ["wireless earbuds"]
    sites = sites or ["all"]

    results = compare_prices(
        queries=queries,
        sites=sites,
        max_pages=max_pages,
        use_env_proxies=use_env_proxies,
    )

    save_comparison_csv(results, output_file)

    for query in queries:
        print_summary(results, query)

    print(f"\n{'═' * 80}")
    print(f"  Total: {len(results)} products compared across {', '.join(sites)}")
    print(f"  Saved to: '{output_file}'")
    print(f"{'═' * 80}")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            queries=args.query or None,
            output_file=args.output,
            sites=args.site or None,
            max_pages=args.max_pages,
            use_env_proxies=args.use_env_proxies,
        )
    )
