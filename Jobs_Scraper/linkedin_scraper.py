#!/usr/bin/env python3
"""LinkedIn Job Scraper
========================
Scrapes public job listings from LinkedIn's guest-accessible job search.
No login or API key required — uses Playwright to render the JS-heavy
page and extracts structured job data from the DOM.

Usage:
    python linkedin_scraper.py --query "python developer" --location "India"
    python linkedin_scraper.py --query "data scientist" --location "Remote" --limit 50
    python linkedin_scraper.py --query "devops engineer" --location "New York" --headed

Requirements:
    pip install playwright beautifulsoup4 lxml
    python -m playwright install chromium

Architecture:
    LinkedIn's public job search (linkedin.com/jobs/search) is accessible
    without login and returns up to ~1000 results per query.  The page
    is JS-rendered, so Playwright loads it in headless Chromium.  Job
    cards are extracted using stable CSS selectors
    (``div.base-card``, ``h3.base-search-card__title``, etc.) that have
    remained consistent across LinkedIn's public job pages.

    Pagination is handled by scrolling the results list and clicking
    "See more jobs" to load additional pages.

Data extracted per job:
    - Title, company, location, posted date
    - Job URL, LinkedIn job ID
    - Employment type, experience level (when available)
    - Description snippet
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

from bs4 import BeautifulSoup

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_DIR = "output"

LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/search"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

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
class JobListing:
    search_query: str
    title: str
    company: str
    location: str
    posted_date: str
    job_url: str
    job_id: str
    employment_type: str
    experience_level: str
    description_snippet: str
    source: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_print(text: str) -> None:
    """Print with fallback for terminals that choke on Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def clean_text(value: object) -> str:
    """Clean and normalize text."""
    if value is None:
        return "N/A"
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text or "N/A"


# ── LinkedIn Jobs Scraper ─────────────────────────────────────────────────────

def scrape_linkedin_jobs(
    query: str,
    location: str = "",
    limit: int = 25,
    headless: bool = True,
) -> list[JobListing]:
    """Scrape public LinkedIn job listings for a given query and location.

    Opens LinkedIn's guest job search in headless Chromium, scrolls to
    load results, and parses job cards from the rendered DOM.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for LinkedIn scraping.\n"
            "Install: pip install playwright && python -m playwright install chromium"
        )
        return []

    # Build search URL
    params = [f"keywords={query.replace(' ', '+')}"]
    if location:
        params.append(f"location={location.replace(' ', '+')}")
    url = f"{LINKEDIN_JOBS_URL}?{'&'.join(params)}"

    log.info(f"[LinkedIn] Searching: '{query}' in '{location or 'Anywhere'}'")

    jobs: list[JobListing] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"[LinkedIn] Navigation timeout (may still work): {e}")

        # Wait for job cards to appear
        try:
            page.wait_for_selector("div.base-card, div.job-search-card", timeout=10000)
        except Exception:
            log.warning("[LinkedIn] No job cards loaded within timeout")
            browser.close()
            return jobs

        page.wait_for_timeout(2000)

        # Scroll to load more results
        loaded = 0
        max_scroll_attempts = max(limit // 25, 3)
        for scroll_round in range(max_scroll_attempts):
            # Scroll the page down
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

            # Check current card count
            current_count = page.locator("div.base-card, div.job-search-card").count()
            log.info(f"[LinkedIn] Loaded {current_count} job cards (scroll {scroll_round + 1})")

            if current_count >= limit:
                break

            if current_count == loaded:
                # No new cards loaded — try clicking "See more jobs"
                see_more = page.locator("button.infinite-scroller__show-more-button, button[aria-label*='more jobs']").first
                if see_more.count() > 0 and see_more.is_visible():
                    see_more.click()
                    page.wait_for_timeout(2000)
                else:
                    break  # No more results available
            loaded = current_count

        # Parse the rendered HTML with BeautifulSoup
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.base-card, div.job-search-card")
    log.info(f"[LinkedIn] Parsing {len(cards)} job cards")

    for card in cards[:limit]:
        try:
            # Title
            title_tag = card.select_one(
                "h3.base-search-card__title, "
                "h3.job-search-card__title, "
                "h3"
            )
            title = clean_text(title_tag.get_text()) if title_tag else "N/A"
            if title == "N/A":
                continue

            # Company
            company_tag = card.select_one(
                "h4.base-search-card__subtitle, "
                "a.hidden-nested-link, "
                "h4"
            )
            company = clean_text(company_tag.get_text()) if company_tag else "N/A"

            # Location
            location_tag = card.select_one(
                "span.job-search-card__location, "
                "span.base-search-card__metadata"
            )
            job_location = clean_text(location_tag.get_text()) if location_tag else "N/A"

            # Posted date
            time_tag = card.select_one("time")
            posted_date = "N/A"
            if time_tag:
                posted_date = time_tag.get("datetime", "") or clean_text(time_tag.get_text())

            # Job URL and ID
            link_tag = card.select_one(
                "a.base-card__full-link, "
                "a[href*='/jobs/view/']"
            )
            job_url = ""
            job_id = ""
            if link_tag:
                href = link_tag.get("href", "")
                job_url = href.split("?")[0]  # Clean tracking params
                id_match = re.search(r"/jobs/view/[^/]*?-(\d+)", href)
                if id_match:
                    job_id = id_match.group(1)
                elif re.search(r"/jobs/view/(\d+)", href):
                    job_id = re.search(r"/jobs/view/(\d+)", href).group(1)

            # Employment type and level from metadata/badges
            employment_type = "N/A"
            experience_level = "N/A"
            metadata_tags = card.select(
                "span.result-benefits__text, "
                "li.result-benefits__text, "
                "span.job-search-card__benefits"
            )
            for meta in metadata_tags:
                text = meta.get_text(strip=True).lower()
                if any(w in text for w in ["full-time", "part-time", "contract", "internship", "temporary"]):
                    employment_type = clean_text(meta.get_text())
                elif any(w in text for w in ["entry", "mid", "senior", "associate", "director", "executive"]):
                    experience_level = clean_text(meta.get_text())

            # Description snippet (if available in card)
            desc_tag = card.select_one(
                "p.base-search-card__snippet, "
                "div.base-search-card__snippet"
            )
            description = clean_text(desc_tag.get_text()) if desc_tag else "N/A"

            jobs.append(JobListing(
                search_query=query,
                title=title,
                company=company,
                location=job_location,
                posted_date=posted_date,
                job_url=job_url,
                job_id=job_id,
                employment_type=employment_type,
                experience_level=experience_level,
                description_snippet=description[:300],
                source="LinkedIn",
            ))

        except Exception as e:
            log.debug(f"[LinkedIn] Error parsing job card: {e}")
            continue

    log.info(f"[LinkedIn] Extracted {len(jobs)} jobs for '{query}'")
    return jobs


# ── CSV Writer ────────────────────────────────────────────────────────────────

def save_jobs_csv(jobs: list[JobListing], filepath: Path) -> None:
    """Save job listings to a CSV file."""
    if not jobs:
        log.warning("No jobs to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [f.name for f in fields(JobListing)]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            writer.writerow(asdict(job))
    log.info(f"Saved {len(jobs)} jobs to '{filepath}'")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape job listings from LinkedIn (Playwright-based)."
    )
    parser.add_argument(
        "-q", "--query", action="append", default=[],
        help="Job search query (e.g. 'python developer'). Repeat for multiple.",
    )
    parser.add_argument(
        "-l", "--location", default="",
        help="Job location filter (e.g. 'India', 'Remote', 'New York').",
    )
    parser.add_argument(
        "--limit", type=int, default=25,
        help="Maximum jobs per query (default: 25).",
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
    limit: int = 25,
    headless: bool = True,
    output_dir: str = OUTPUT_DIR,
) -> int:
    if not queries:
        _safe_print("No queries specified. Use --query <job title>.")
        return 1

    output_path = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_jobs: list[JobListing] = []

    for query in queries:
        jobs = scrape_linkedin_jobs(
            query=query,
            location=location,
            limit=limit,
            headless=headless,
        )
        all_jobs.extend(jobs)

        if len(queries) > 1:
            time.sleep(random.uniform(3, 6))

    # Save
    if all_jobs:
        save_jobs_csv(all_jobs, output_path / f"linkedin_jobs_{timestamp}.csv")

    # Summary
    _safe_print(f"\n{'=' * 70}")
    _safe_print("  LinkedIn Job Scraper Results")
    _safe_print(f"{'=' * 70}")

    for query in queries:
        query_jobs = [j for j in all_jobs if j.search_query == query]
        _safe_print(f"\n  '{query}': {len(query_jobs)} jobs found")

        # Group by company
        companies: dict[str, int] = {}
        for j in query_jobs:
            companies[j.company] = companies.get(j.company, 0) + 1

        # Show top companies
        top = sorted(companies.items(), key=lambda x: x[1], reverse=True)[:5]
        if top:
            _safe_print("  Top hiring companies:")
            for comp, count in top:
                _safe_print(f"    {comp}: {count} openings")

        # Show sample listings
        _safe_print(f"\n  Sample listings:")
        for j in query_jobs[:5]:
            title_safe = j.title[:45].encode("ascii", errors="replace").decode("ascii")
            _safe_print(f"    {j.company[:20]:<22s} {title_safe}")
            _safe_print(f"      {j.location}  |  Posted: {j.posted_date}")

    _safe_print(f"\n  Total: {len(all_jobs)} jobs scraped")
    _safe_print(f"  Output: {output_path.resolve()}")
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
