"""
Web Scraper - IndiaMart & Alibaba (requests + BeautifulSoup)
============================================================
Scrapes Product Name and Price from IndiaMart and Alibaba.

Usage:
    python scraper_requests.py

Requirements:
    pip install requests beautifulsoup4 lxml

Limitations:
    - May get blocked by anti-bot systems (Cloudflare, JS challenges).
    - If blocked, use scraper_playwright.py instead.
"""

import csv
import html as html_lib
import json
import time
import random
import logging
import argparse
from dataclasses import dataclass, fields
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

PRODUCTS_TO_SEARCH = [
    "Cnc Router Machine",
    "Optimus Nesting CNC  Machine",
    "Cnc Router With Vacuum Table",
    "CNC Router Cutting & Engraving Machine",
    # Add more products here
]

OUTPUT_FILE = "products_output.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

DELAY_BETWEEN_REQUESTS = (2, 5)   # seconds (random range)
MAX_RESULTS_PER_SITE   = 10       # max products per search per site
USE_ENV_PROXIES        = False     # Set True only if HTTP(S)_PROXY is valid

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Product:
    search_query: str
    source:       str
    name:         str
    price:        str
    unit:         str
    supplier:     str
    location:     str
    url:          str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_page(url: str, params: Optional[dict] = None) -> Optional[BeautifulSoup]:
    """Fetch a page and return a BeautifulSoup object, or None on failure."""
    try:
        session = requests.Session()
        session.trust_env = USE_ENV_PROXIES
        response = session.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.exceptions.HTTPError as e:
        log.warning(f"HTTP error {e.response.status_code} for {url}")
    except requests.exceptions.RequestException as e:
        log.warning(f"Request failed for {url}: {e}")
    return None


def random_delay():
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))


def clean_text(value) -> str:
    if value is None:
        return "N/A"
    return html_lib.unescape(str(value)).strip() or "N/A"


def split_price_unit(price: str) -> tuple[str, str]:
    if not price or price == "N/A" or "/" not in price:
        return price, "N/A"
    amount, unit = price.split("/", 1)
    return amount.strip() or "N/A", unit.strip() or "N/A"


def parse_indiamart_next_data(soup: BeautifulSoup, query: str) -> list[Product]:
    """Parse IndiaMart product data embedded in the Next.js JSON payload."""
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        return []

    try:
        payload = json.loads(script.string)
        rows = (
            payload.get("props", {})
            .get("pageProps", {})
            .get("searchResponse", {})
            .get("results", [])
        )
    except (TypeError, json.JSONDecodeError):
        return []

    results: list[Product] = []
    for row in rows[:MAX_RESULTS_PER_SITE]:
        fields_data = row.get("fields", {}) if isinstance(row, dict) else {}
        if not fields_data:
            continue

        name = clean_text(fields_data.get("title"))
        raw_price = clean_text(
            fields_data.get("price_f") or fields_data.get("indiaPriceFormat")
        )
        price, unit = split_price_unit(raw_price)
        supplier = clean_text(fields_data.get("companyname") or fields_data.get("company"))
        location = clean_text(
            fields_data.get("city")
            or fields_data.get("district")
            or fields_data.get("state")
        )
        href = clean_text(
            fields_data.get("title_url") or fields_data.get("desktop_title_url")
        )

        results.append(Product(
            search_query=query,
            source="IndiaMart",
            name=name,
            price=price,
            unit=unit,
            supplier=supplier,
            location=location,
            url=href,
        ))

    return results


# ── IndiaMart Scraper ─────────────────────────────────────────────────────────

def scrape_indiamart(query: str) -> list[Product]:
    """
    Scrape IndiaMart search results for a given product query.
    URL pattern: https://dir.indiamart.com/search.mp?ss=<query>
    """
    results = []
    url    = "https://dir.indiamart.com/search.mp"
    params = {"ss": query}

    log.info(f"[IndiaMart] Searching: '{query}'")
    soup = get_page(url, params=params)
    if not soup:
        log.warning(f"[IndiaMart] Failed to fetch results for '{query}'")
        return results

    results = parse_indiamart_next_data(soup, query)
    if results:
        log.info(f"[IndiaMart] Found {len(results)} results for '{query}'")
        return results

    # Product cards are inside <div class="card"> or similar wrappers
    # Selectors may need updating if IndiaMart changes its HTML structure
    cards = soup.select("div.lst-wpr") or soup.select("div.card-body")

    if not cards:
        log.warning(f"[IndiaMart] No product cards found for '{query}' — site may have changed or blocked request.")
        return results

    for card in cards[:MAX_RESULTS_PER_SITE]:
        try:
            name_tag     = card.select_one("a.elps.elps2, div.name a, h2.name a")
            price_tag    = card.select_one("p.price, div.prc, span.price")
            unit_tag     = card.select_one("span.unit, p.unit")
            supplier_tag = card.select_one("a.lcname, div.cname a, p.company-name a")
            location_tag = card.select_one("span.city, p.location, span.lctn")
            link_tag     = card.select_one("a[href]")

            name     = name_tag.get_text(strip=True)     if name_tag     else "N/A"
            price    = price_tag.get_text(strip=True)    if price_tag    else "N/A"
            unit     = unit_tag.get_text(strip=True)     if unit_tag     else "N/A"
            supplier = supplier_tag.get_text(strip=True) if supplier_tag else "N/A"
            location = location_tag.get_text(strip=True) if location_tag else "N/A"
            href     = link_tag["href"]                  if link_tag     else "N/A"

            if not href.startswith("http"):
                href = "https://dir.indiamart.com" + href

            results.append(Product(
                search_query=query,
                source="IndiaMart",
                name=name,
                price=price,
                unit=unit,
                supplier=supplier,
                location=location,
                url=href,
            ))
        except Exception as e:
            log.debug(f"[IndiaMart] Error parsing card: {e}")
            continue

    log.info(f"[IndiaMart] Found {len(results)} results for '{query}'")
    return results


# ── Alibaba Scraper ───────────────────────────────────────────────────────────

def scrape_alibaba(query: str) -> list[Product]:
    """
    Scrape Alibaba search results for a given product query.
    URL pattern: https://www.alibaba.com/trade/search?SearchText=<query>
    """
    results = []
    url    = "https://www.alibaba.com/trade/search"
    params = {"SearchText": query, "IndexArea": "product_en"}

    log.info(f"[Alibaba] Searching: '{query}'")
    soup = get_page(url, params=params)
    if not soup:
        log.warning(f"[Alibaba] Failed to fetch results for '{query}'")
        return results

    # Alibaba product cards
    cards = (
        soup.select("div.organic-list-offer-outter")
        or soup.select("div[class*='offer-list-row']")
        or soup.select("div.J-offer-wrapper")
    )

    if not cards:
        log.warning(
            f"[Alibaba] No product cards found for '{query}' — "
            "Alibaba heavily uses JavaScript rendering. "
            "Use scraper_playwright.py for reliable results."
        )
        return results

    for card in cards[:MAX_RESULTS_PER_SITE]:
        try:
            name_tag     = card.select_one("h2.offer-title a, a.elements-title-normal, div.title a")
            price_tag    = card.select_one("div.price-range, span.price, div[class*='price']")
            unit_tag     = card.select_one("span.unit, div[class*='unit']")
            supplier_tag = card.select_one("a.company-name, div[class*='company'] a")
            location_tag = card.select_one("span[class*='location'], div[class*='location']")
            link_tag     = card.select_one("a[href]")

            name     = name_tag.get_text(strip=True)     if name_tag     else "N/A"
            price    = price_tag.get_text(strip=True)    if price_tag    else "N/A"
            unit     = unit_tag.get_text(strip=True)     if unit_tag     else "N/A"
            supplier = supplier_tag.get_text(strip=True) if supplier_tag else "N/A"
            location = location_tag.get_text(strip=True) if location_tag else "N/A"
            href     = link_tag["href"]                  if link_tag     else "N/A"

            if href.startswith("//"):
                href = "https:" + href
            elif not href.startswith("http"):
                href = "https://www.alibaba.com" + href

            results.append(Product(
                search_query=query,
                source="Alibaba",
                name=name,
                price=price,
                unit=unit,
                supplier=supplier,
                location=location,
                url=href,
            ))
        except Exception as e:
            log.debug(f"[Alibaba] Error parsing card: {e}")
            continue

    log.info(f"[Alibaba] Found {len(results)} results for '{query}'")
    return results


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_to_csv(products: list[Product], filename: str):
    if not products:
        log.warning("No products to save.")
        return

    fieldnames = [f.name for f in fields(Product)]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in products:
            writer.writerow({
                "search_query": p.search_query,
                "source":       p.source,
                "name":         p.name,
                "price":        p.price,
                "unit":         p.unit,
                "supplier":     p.supplier,
                "location":     p.location,
                "url":          p.url,
            })

    log.info(f"Saved {len(products)} products to '{filename}'")


# ── Main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape IndiaMart and Alibaba product listings with requests."
    )
    parser.add_argument(
        "-q",
        "--query",
        action="append",
        default=[],
        help="Product search query. Repeat to run multiple queries.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"CSV output file (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--site",
        choices=["all", "indiamart", "alibaba"],
        default="all",
        help="Limit scraping to one site.",
    )
    return parser


def main(queries: Optional[list[str]] = None, output_file: str = OUTPUT_FILE, site: str = "all"):
    all_products: list[Product] = []
    queries = queries or PRODUCTS_TO_SEARCH

    for query in queries:
        # IndiaMart
        if site in ("all", "indiamart"):
            results = scrape_indiamart(query)
            all_products.extend(results)
            random_delay()

        # Alibaba
        if site in ("all", "alibaba"):
            results = scrape_alibaba(query)
            all_products.extend(results)
            random_delay()

    save_to_csv(all_products, output_file)
    print(f"\nDone! {len(all_products)} products saved to '{output_file}'")


if __name__ == "__main__":
    args = build_parser().parse_args()
    main(queries=args.query or None, output_file=args.output, site=args.site)
