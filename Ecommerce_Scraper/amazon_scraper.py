#!/usr/bin/env python3
"""Amazon Product & Review Scraper
===================================
Scrapes product listings, prices, ratings, and customer reviews from
Amazon India (amazon.in) and Amazon US (amazon.com).

Usage:
    python amazon_scraper.py --query "wireless earbuds" --region india
    python amazon_scraper.py --query "gaming laptop" --region us --reviews --output results.csv

Requirements:
    pip install requests beautifulsoup4 lxml

Limitations:
    - Amazon has aggressive anti-bot measures; rotating user agents are used.
    - Some pages may return CAPTCHA responses; retry with delay usually works.
    - Review scraping is limited to the first page of reviews per product.
"""

from __future__ import annotations

import csv
import html as html_lib
import json
import logging
import random
import re
import time
import argparse
from dataclasses import dataclass, fields, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

PRODUCTS_TO_SEARCH = [
    "wireless earbuds",
    "gaming laptop",
]

OUTPUT_FILE = "amazon_products.csv"
REVIEWS_FILE = "amazon_reviews.csv"

DOMAINS = {
    "india": "https://www.amazon.in",
    "us": "https://www.amazon.com",
}

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
    ),
]

DELAY_BETWEEN_REQUESTS = (2, 5)
MAX_RESULTS_PER_PAGE = 20
MAX_PAGES = 3
MAX_REVIEWS_PER_PRODUCT = 10

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class AmazonProduct:
    search_query: str
    region: str
    asin: str
    name: str
    price: str
    mrp: str
    discount: str
    rating: str
    review_count: str
    seller: str
    url: str
    image_url: str
    is_prime: str
    is_sponsored: str


@dataclass
class AmazonReview:
    asin: str
    product_name: str
    region: str
    reviewer: str
    rating: str
    title: str
    body: str
    date: str
    verified: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_headers() -> dict[str, str]:
    """Return request headers with a random user agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def get_page(
    session: requests.Session,
    url: str,
    params: Optional[dict] = None,
    max_retries: int = 3,
) -> Optional[BeautifulSoup]:
    """Fetch a page and return a BeautifulSoup object, or None on failure."""
    for attempt in range(1, max_retries + 1):
        try:
            session.headers.update(get_headers())
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()

            # Detect CAPTCHA pages
            if "captcha" in response.text.lower() or "robot" in response.text.lower()[:500]:
                log.warning(f"CAPTCHA detected on attempt {attempt}/{max_retries}")
                if attempt < max_retries:
                    time.sleep(random.uniform(5, 10))
                    continue
                return None

            return BeautifulSoup(response.text, "lxml")

        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP error {e.response.status_code} for {url} (attempt {attempt})")
            if e.response.status_code == 503 and attempt < max_retries:
                time.sleep(random.uniform(3, 7))
                continue
        except requests.exceptions.RequestException as e:
            log.warning(f"Request failed for {url}: {e} (attempt {attempt})")
            if attempt < max_retries:
                time.sleep(random.uniform(2, 5))
                continue
    return None


def random_delay() -> None:
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))


def clean_text(value: object) -> str:
    if value is None:
        return "N/A"
    text = html_lib.unescape(str(value)).strip()
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text or "N/A"


def extract_price(text: str) -> str:
    """Extract a numeric price from a string like '₹1,299.00' or '$49.99'."""
    if not text or text == "N/A":
        return "N/A"
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        return match.group(0)
    return text.strip()


def extract_asin(url: str) -> str:
    """Extract ASIN from an Amazon product URL."""
    match = re.search(r"/dp/([A-Z0-9]{10})", url, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"/gp/product/([A-Z0-9]{10})", url, re.IGNORECASE)
    if match:
        return match.group(1)
    return "N/A"


# ── Amazon Product Scraper ────────────────────────────────────────────────────

def scrape_amazon_search(
    session: requests.Session,
    query: str,
    region: str,
    max_pages: int = MAX_PAGES,
    max_results: int = MAX_RESULTS_PER_PAGE,
) -> list[AmazonProduct]:
    """Scrape Amazon search results for a given product query."""
    domain = DOMAINS.get(region, DOMAINS["us"])
    all_products: list[AmazonProduct] = []

    for page in range(1, max_pages + 1):
        url = f"{domain}/s"
        params = {"k": query, "page": str(page), "ref": f"sr_pg_{page}"}

        log.info(f"[Amazon {region.upper()}] Searching '{query}' — page {page}")
        soup = get_page(session, url, params=params)
        if not soup:
            log.warning(f"[Amazon {region.upper()}] Failed to fetch page {page} for '{query}'")
            break

        # Product cards
        cards = soup.select(
            "div[data-component-type='s-search-result']"
        )

        if not cards:
            # Fallback selectors
            cards = soup.select("div.s-result-item[data-asin]")
            cards = [c for c in cards if c.get("data-asin", "").strip()]

        if not cards:
            log.warning(
                f"[Amazon {region.upper()}] No product cards on page {page} for '{query}' "
                "— site structure may have changed or request was blocked."
            )
            break

        page_count = 0
        for card in cards:
            if page_count >= max_results:
                break

            asin = card.get("data-asin", "").strip()
            if not asin:
                continue

            # Detect sponsored
            is_sponsored = "No"
            sponsored_tag = card.select_one("span.puis-label-popover-default span")
            if sponsored_tag and "sponsored" in sponsored_tag.get_text(strip=True).lower():
                is_sponsored = "Yes"
            elif card.select_one("[data-component-type='sp-sponsored-result']"):
                is_sponsored = "Yes"

            # Product name — Amazon now puts the title in h2's aria-label
            name = "N/A"
            h2_tag = card.select_one("h2")
            if h2_tag:
                # Best source: aria-label has the full clean title
                aria = h2_tag.get("aria-label", "")
                if aria:
                    # Strip "Sponsored Ad - " prefix if present
                    name = re.sub(r"^Sponsored\s+Ad\s*-\s*", "", aria).strip()
                if not name or name == "N/A":
                    # Fallback: text content of h2
                    name = clean_text(h2_tag.get_text())
            if name == "N/A":
                # Legacy selectors for older layouts
                name_tag = card.select_one(
                    "span.a-size-medium.a-color-base.a-text-normal, "
                    "span.a-size-base-plus.a-color-base.a-text-normal"
                )
                name = clean_text(name_tag.get_text()) if name_tag else "N/A"

            # URL
            link_tag = card.select_one("h2 a.a-link-normal, a.a-link-normal.s-no-outline")
            href = "N/A"
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                if not href.startswith("http"):
                    href = domain + href

            # Price
            price_whole = card.select_one("span.a-price-whole")
            price_fraction = card.select_one("span.a-price-fraction")
            if price_whole:
                price = price_whole.get_text(strip=True).rstrip(".")
                if price_fraction:
                    price += "." + price_fraction.get_text(strip=True)
            else:
                price_tag = card.select_one("span.a-price span.a-offscreen")
                price = clean_text(price_tag.get_text()) if price_tag else "N/A"

            # MRP (original price / strikethrough)
            mrp_tag = card.select_one(
                "span.a-price.a-text-price span.a-offscreen, "
                "span.a-text-price span.a-offscreen"
            )
            mrp = clean_text(mrp_tag.get_text()) if mrp_tag else "N/A"

            # Discount
            discount = "N/A"
            if price != "N/A" and mrp != "N/A":
                try:
                    p = float(extract_price(price))
                    m = float(extract_price(mrp))
                    if m > 0:
                        discount = f"{round((1 - p / m) * 100)}%"
                except (ValueError, ZeroDivisionError):
                    pass

            # Rating
            rating_tag = card.select_one(
                "span.a-icon-alt, "
                "i.a-icon-star-small span.a-icon-alt"
            )
            rating = "N/A"
            if rating_tag:
                rating_text = rating_tag.get_text(strip=True)
                match = re.search(r"[\d.]+", rating_text)
                if match:
                    rating = match.group(0)

            # Review count
            review_tag = card.select_one(
                "span.a-size-base.s-underline-text, "
                "span.a-size-small span.a-size-base"
            )
            review_count = clean_text(review_tag.get_text()) if review_tag else "N/A"

            # Seller / brand (often in "by Brand" line)
            seller = "N/A"
            brand_tag = card.select_one(
                "span.a-size-base-plus.a-color-base, "
                "h5 span.a-color-base"
            )
            if brand_tag:
                seller = clean_text(brand_tag.get_text())

            # Image
            img_tag = card.select_one("img.s-image")
            image_url = img_tag["src"] if img_tag and img_tag.get("src") else "N/A"

            # Prime
            is_prime = "No"
            if card.select_one("i.a-icon-prime, span.aok-relative.s-icon-text-medium"):
                is_prime = "Yes"

            all_products.append(AmazonProduct(
                search_query=query,
                region=region,
                asin=asin,
                name=name,
                price=price,
                mrp=mrp,
                discount=discount,
                rating=rating,
                review_count=review_count,
                seller=seller,
                url=href,
                image_url=image_url,
                is_prime=is_prime,
                is_sponsored=is_sponsored,
            ))
            page_count += 1

        log.info(f"[Amazon {region.upper()}] Page {page}: found {page_count} products")
        if page < max_pages:
            random_delay()

    log.info(
        f"[Amazon {region.upper()}] Total: {len(all_products)} products for '{query}'"
    )
    return all_products


# ── Amazon Review Scraper ─────────────────────────────────────────────────────

def scrape_amazon_reviews(
    session: requests.Session,
    product: AmazonProduct,
    max_reviews: int = MAX_REVIEWS_PER_PRODUCT,
) -> list[AmazonReview]:
    """Scrape customer reviews for a given Amazon product."""
    if product.asin == "N/A":
        return []

    domain = DOMAINS.get(product.region, DOMAINS["us"])
    url = f"{domain}/product-reviews/{product.asin}"
    params = {"reviewerType": "all_reviews", "sortBy": "recent"}

    log.info(f"[Reviews] Fetching reviews for ASIN {product.asin}")
    soup = get_page(session, url, params=params)
    if not soup:
        log.warning(f"[Reviews] Failed to fetch reviews for ASIN {product.asin}")
        return []

    reviews: list[AmazonReview] = []
    review_cards = soup.select("div[data-hook='review']")

    if not review_cards:
        review_cards = soup.select("div.review")

    for card in review_cards[:max_reviews]:
        try:
            # Reviewer name
            reviewer_tag = card.select_one("span.a-profile-name")
            reviewer = clean_text(reviewer_tag.get_text()) if reviewer_tag else "N/A"

            # Rating
            rating_tag = card.select_one(
                "i[data-hook='review-star-rating'] span.a-icon-alt, "
                "i.a-icon-star span.a-icon-alt"
            )
            rating = "N/A"
            if rating_tag:
                match = re.search(r"[\d.]+", rating_tag.get_text(strip=True))
                if match:
                    rating = match.group(0)

            # Review title
            title_tag = card.select_one(
                "a[data-hook='review-title'] span:not(.a-letter-space), "
                "a[data-hook='review-title']"
            )
            title = clean_text(title_tag.get_text()) if title_tag else "N/A"

            # Review body
            body_tag = card.select_one(
                "span[data-hook='review-body'] span"
            )
            body = clean_text(body_tag.get_text()) if body_tag else "N/A"

            # Date
            date_tag = card.select_one("span[data-hook='review-date']")
            review_date = clean_text(date_tag.get_text()) if date_tag else "N/A"

            # Verified purchase
            verified_tag = card.select_one(
                "span[data-hook='avp-badge'], span.a-color-link"
            )
            verified = "No"
            if verified_tag and "verified" in verified_tag.get_text(strip=True).lower():
                verified = "Yes"

            reviews.append(AmazonReview(
                asin=product.asin,
                product_name=product.name[:100],
                region=product.region,
                reviewer=reviewer,
                rating=rating,
                title=title,
                body=body,
                date=review_date,
                verified=verified,
            ))
        except Exception as e:
            log.debug(f"[Reviews] Error parsing review card: {e}")
            continue

    log.info(f"[Reviews] Found {len(reviews)} reviews for ASIN {product.asin}")
    return reviews


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_products_csv(products: list[AmazonProduct], filename: str) -> None:
    if not products:
        log.warning("No products to save.")
        return
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(AmazonProduct)]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in products:
            writer.writerow(asdict(p))
    log.info(f"Saved {len(products)} products to '{path}'")


def save_reviews_csv(reviews: list[AmazonReview], filename: str) -> None:
    if not reviews:
        log.warning("No reviews to save.")
        return
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(AmazonReview)]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reviews:
            writer.writerow(asdict(r))
    log.info(f"Saved {len(reviews)} reviews to '{path}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape Amazon product listings and reviews."
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
        help=f"CSV output file for products (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--reviews-output",
        default=REVIEWS_FILE,
        help=f"CSV output file for reviews (default: {REVIEWS_FILE})",
    )
    parser.add_argument(
        "--region",
        choices=["india", "us", "both"],
        default="both",
        help="Amazon region to scrape (default: both).",
    )
    parser.add_argument(
        "--reviews",
        action="store_true",
        help="Also scrape customer reviews for each product.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=MAX_PAGES,
        help=f"Maximum search result pages per query (default: {MAX_PAGES}).",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=MAX_REVIEWS_PER_PRODUCT,
        help=f"Maximum reviews per product (default: {MAX_REVIEWS_PER_PRODUCT}).",
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
    reviews_output: str = REVIEWS_FILE,
    region: str = "both",
    scrape_reviews: bool = False,
    max_pages: int = MAX_PAGES,
    max_reviews: int = MAX_REVIEWS_PER_PRODUCT,
    use_env_proxies: bool = False,
) -> int:
    queries = queries or PRODUCTS_TO_SEARCH
    all_products: list[AmazonProduct] = []
    all_reviews: list[AmazonReview] = []

    session = requests.Session()
    session.headers.update(get_headers())
    session.trust_env = use_env_proxies

    regions = ["india", "us"] if region == "both" else [region]

    for r in regions:
        for query in queries:
            products = scrape_amazon_search(
                session, query, r,
                max_pages=max_pages,
                max_results=MAX_RESULTS_PER_PAGE,
            )
            all_products.extend(products)
            random_delay()

            if scrape_reviews:
                for product in products[:5]:  # Limit review scraping per query
                    reviews = scrape_amazon_reviews(
                        session, product, max_reviews=max_reviews
                    )
                    all_reviews.extend(reviews)
                    if reviews:
                        random_delay()

    save_products_csv(all_products, output_file)
    if scrape_reviews and all_reviews:
        save_reviews_csv(all_reviews, reviews_output)

    print(f"\nDone! {len(all_products)} products saved to '{output_file}'")
    if scrape_reviews:
        print(f"     {len(all_reviews)} reviews saved to '{reviews_output}'")
    return 0


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(
        main(
            queries=args.query or None,
            output_file=args.output,
            reviews_output=args.reviews_output,
            region=args.region,
            scrape_reviews=args.reviews,
            max_pages=args.max_pages,
            max_reviews=args.max_reviews,
            use_env_proxies=args.use_env_proxies,
        )
    )
