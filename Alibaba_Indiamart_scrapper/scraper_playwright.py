"""
Web Scraper - IndiaMart & Alibaba (Playwright - Browser Automation)
====================================================================
More reliable scraper using a real headless browser.
Handles JavaScript-rendered pages, bypasses basic anti-bot measures.

Usage:
    python scraper_playwright.py

Requirements:
    pip install playwright beautifulsoup4 lxml
    playwright install chromium

Optional (better anti-bot evasion):
    pip install playwright-stealth
"""

import csv
import asyncio
import html as html_lib
import json
import logging
import random
import argparse
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PwTimeoutError
from bs4 import BeautifulSoup

# ── Try to import stealth (optional but recommended) ──────────────────────────
try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

# ── Configuration ─────────────────────────────────────────────────────────────

PRODUCTS_TO_SEARCH = [
    "steel pipes",
    "copper wire",
    # Add more products here
]

OUTPUT_FILE           = "products_output.csv"
HEADLESS              = True        # Set False to watch the browser in action
MAX_RESULTS_PER_SITE  = 10
DELAY_BETWEEN_PAGES   = (3, 6)     # seconds

# Alibaba often serves a CAPTCHA to fresh/headless sessions. This profile keeps
# cookies/local storage after you solve verification once in the opened browser.
ALIBABA_HEADLESS              = False
ALIBABA_PROFILE_DIR           = "alibaba_browser_profile"
ALIBABA_MANUAL_VERIFY_TIMEOUT = 180  # seconds
ALIBABA_PROXY_SERVER          = ""   # Example: "http://user:pass@host:port"

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


# ── Browser Helpers ───────────────────────────────────────────────────────────

async def new_page(browser: Browser) -> Page:
    """Create a new browser context + page with realistic settings."""
    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Kolkata",
        java_script_enabled=True,
    )
    page = await context.new_page()

    # Apply stealth patches if available
    if STEALTH_AVAILABLE:
        await Stealth().apply_stealth_async(page)

    # Block images/fonts/media to speed up loading
    await page.route(
        "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,avi}",
        lambda route: route.abort()
    )
    return page


async def new_alibaba_context(pw):
    """Create a persistent browser context for Alibaba verification/session reuse."""
    profile_dir = Path(ALIBABA_PROFILE_DIR)
    profile_dir.mkdir(exist_ok=True)

    launch_options = {
        "headless": ALIBABA_HEADLESS,
        "viewport": {"width": 1366, "height": 768},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "locale": "en-US",
        "timezone_id": "Asia/Kolkata",
        "java_script_enabled": True,
    }
    if ALIBABA_PROXY_SERVER:
        launch_options["proxy"] = {"server": ALIBABA_PROXY_SERVER}

    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        **launch_options,
    )
    if STEALTH_AVAILABLE:
        await Stealth().apply_stealth_async(context)
    return context


async def random_delay():
    await asyncio.sleep(random.uniform(*DELAY_BETWEEN_PAGES))


async def get_soup(page: Page, url: str, wait_selector: Optional[str] = None) -> Optional[BeautifulSoup]:
    """Navigate to URL and return BeautifulSoup of the rendered page."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=15_000)
            except PwTimeoutError:
                log.warning(f"Selector not found after load: {wait_selector}")
        else:
            await page.wait_for_timeout(3000)  # fallback wait
        html = await page.content()
        return BeautifulSoup(html, "lxml")
    except PwTimeoutError:
        log.warning(f"Timeout loading: {url}")
    except Exception as e:
        log.warning(f"Error loading {url}: {e}")
    return None


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

        raw_price = clean_text(
            fields_data.get("price_f") or fields_data.get("indiaPriceFormat")
        )
        price, unit = split_price_unit(raw_price)

        results.append(Product(
            search_query=query,
            source="IndiaMart",
            name=clean_text(fields_data.get("title")),
            price=price,
            unit=unit,
            supplier=clean_text(fields_data.get("companyname") or fields_data.get("company")),
            location=clean_text(
                fields_data.get("city")
                or fields_data.get("district")
                or fields_data.get("state")
            ),
            url=clean_text(fields_data.get("title_url") or fields_data.get("desktop_title_url")),
        ))

    return results


def is_captcha_page(soup: BeautifulSoup) -> bool:
    page_text = soup.get_text(" ", strip=True).lower()
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    return "captcha" in title or "slide to verify" in page_text or "unusual traffic" in page_text


def first_text(parent, selectors: list[str]) -> str:
    for selector in selectors:
        tag = parent.select_one(selector)
        if tag:
            text = clean_text(tag.get_text(" ", strip=True))
            if text != "N/A":
                return text
    return "N/A"


def first_href(parent, selectors: list[str]) -> str:
    for selector in selectors:
        tag = parent.select_one(selector)
        if tag and tag.get("href"):
            href = clean_text(tag["href"])
            if href.startswith("//"):
                return "https:" + href
            if href.startswith("/"):
                return "https://www.alibaba.com" + href
            return href
    return "N/A"


async def wait_for_alibaba_verification(page: Page, query: str) -> Optional[BeautifulSoup]:
    """Let the user complete Alibaba verification in the opened browser."""
    log.warning(
        f"[Alibaba] Verification required for '{query}'. "
        f"Solve it in the browser window within {ALIBABA_MANUAL_VERIFY_TIMEOUT} seconds."
    )
    try:
        await page.wait_for_function(
            """() => {
                const text = document.body ? document.body.innerText.toLowerCase() : "";
                const title = document.title.toLowerCase();
                return !title.includes("captcha")
                    && !text.includes("slide to verify")
                    && !text.includes("unusual traffic");
            }""",
            timeout=ALIBABA_MANUAL_VERIFY_TIMEOUT * 1000,
        )
        await page.wait_for_timeout(5000)
        return BeautifulSoup(await page.content(), "lxml")
    except PwTimeoutError:
        log.warning(f"[Alibaba] Verification was not completed for '{query}'.")
    return None


def parse_alibaba_cards(soup: BeautifulSoup, query: str) -> list[Product]:
    cards = (
        soup.select("div.search-card-e")
        or soup.select("div.organic-gallery-offer-outter")
        or soup.select("div.organic-list-offer-outter")
        or soup.select("div[class*='search-card']")
        or soup.select("div[class*='offer-card']")
        or soup.select("div[class*='gallery-offer']")
        or soup.select("div.J-offer-wrapper")
    )

    results: list[Product] = []
    seen_urls: set[str] = set()
    for card in cards:
        href = first_href(card, [
            "a[href*='product-detail']",
            "a[href*='/product-detail/']",
            "a[href*='alibaba.com']",
            "a[href]",
        ])
        name = first_text(card, [
            "h2 a",
            "a.elements-title-normal",
            "a[class*='title']",
            "div[class*='title']",
            "a[href*='product-detail']",
        ])

        if name == "N/A" or href == "N/A" or href in seen_urls:
            continue
        seen_urls.add(href)

        price_text = first_text(card, [
            "div.search-card-e-price-main",
            "div[class*='price-main']",
            "div.price-range",
            "span.price",
            "div[class*='price']",
        ])
        price, unit = split_price_unit(price_text)

        results.append(Product(
            search_query=query,
            source="Alibaba",
            name=name,
            price=price,
            unit=unit,
            supplier=first_text(card, [
                "a.company-name",
                "a[class*='company']",
                "div[class*='company']",
                "a[class*='supplier']",
                "div[class*='supplier']",
            ]),
            location=first_text(card, [
                "span[class*='location']",
                "div[class*='location']",
                "span[class*='country']",
                "div[class*='country']",
            ]),
            url=href,
        ))

        if len(results) >= MAX_RESULTS_PER_SITE:
            break

    return results


# ── IndiaMart Scraper ─────────────────────────────────────────────────────────

async def scrape_indiamart(page: Page, query: str) -> list[Product]:
    """Scrape IndiaMart search results using Playwright."""
    results = []
    url     = f"https://dir.indiamart.com/search.mp?ss={query.replace(' ', '+')}"

    log.info(f"[IndiaMart] Searching: '{query}'")
    soup = await get_soup(page, url, wait_selector="div.lst-wpr, div.card-body")

    if not soup:
        log.warning(f"[IndiaMart] Could not load page for '{query}'")
        return results

    results = parse_indiamart_next_data(soup, query)
    if results:
        log.info(f"[IndiaMart] Found {len(results)} results for '{query}'")
        return results

    cards = soup.select("div.lst-wpr") or soup.select("div.card-body")

    if not cards:
        log.warning(f"[IndiaMart] No cards found for '{query}'")
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
                name=name, price=price, unit=unit,
                supplier=supplier, location=location, url=href,
            ))
        except Exception as e:
            log.debug(f"[IndiaMart] Card parse error: {e}")

    log.info(f"[IndiaMart] Found {len(results)} results for '{query}'")
    return results


# ── Alibaba Scraper ───────────────────────────────────────────────────────────

async def scrape_alibaba(page: Page, query: str) -> list[Product]:
    """Scrape Alibaba search results using Playwright."""
    results = []
    url     = (
        f"https://www.alibaba.com/trade/search"
        f"?SearchText={quote_plus(query)}&IndexArea=product_en"
    )

    log.info(f"[Alibaba] Searching: '{query}'")
    soup = await get_soup(
        page, url,
        wait_selector="div.organic-list-offer-outter, div[class*='offer-list']"
    )

    if not soup:
        log.warning(f"[Alibaba] Could not load page for '{query}'")
        return results

    if is_captcha_page(soup):
        verified_soup = await wait_for_alibaba_verification(page, query)
        if not verified_soup:
            return results
        soup = verified_soup

    results = parse_alibaba_cards(soup, query)
    if not results:
        log.warning(f"[Alibaba] No cards found for '{query}'")
        return results

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
        description="Scrape IndiaMart and Alibaba product listings with Playwright."
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
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show the IndiaMart browser window. Alibaba keeps its configured browser mode.",
    )
    return parser


async def main(
    queries: Optional[list[str]] = None,
    output_file: str = OUTPUT_FILE,
    site: str = "all",
    headless: bool = HEADLESS,
):
    all_products: list[Product] = []
    queries = queries or PRODUCTS_TO_SEARCH

    async with async_playwright() as pw:
        indiamart_browser = None
        alibaba_context = None

        if site in ("all", "indiamart"):
            indiamart_browser = await pw.chromium.launch(headless=headless)
        if site in ("all", "alibaba"):
            alibaba_context = await new_alibaba_context(pw)

        for query in queries:
            if indiamart_browser:
                page = await new_page(indiamart_browser)
                results = await scrape_indiamart(page, query)
                all_products.extend(results)
                await page.context.close()
                await random_delay()

            if alibaba_context:
                page = await alibaba_context.new_page()
                results = await scrape_alibaba(page, query)
                all_products.extend(results)
                await page.close()
                await random_delay()

        if alibaba_context:
            await alibaba_context.close()
        if indiamart_browser:
            await indiamart_browser.close()

    save_to_csv(all_products, output_file)
    print(f"\nDone! {len(all_products)} products saved to '{output_file}'")


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(
        main(
            queries=args.query or None,
            output_file=args.output,
            site=args.site,
            headless=not args.headful,
        )
    )
