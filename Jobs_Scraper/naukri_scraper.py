#!/usr/bin/env python3
"""Naukri Job Scraper
========================
Scrapes job listings from Naukri.com using Playwright in headed mode 
with stealth patches to bypass bot detection.

Usage:
    python naukri_scraper.py --query "python developer" --location "Bangalore"
    python naukri_scraper.py --query "data scientist" --limit 50
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

OUTPUT_DIR = "output"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

@dataclass
class NaukriJob:
    search_query: str
    title: str
    company: str
    location: str
    experience: str
    salary: str
    job_url: str
    source: str

def clean_text(value: object) -> str:
    if value is None:
        return "N/A"
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text or "N/A"

def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))

def scrape_naukri_jobs(query: str, location: str = "", limit: int = 20, headless: bool = False) -> list[NaukriJob]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright is required. Run: pip install playwright && python -m playwright install chromium")
        return []

    # Build Naukri URL structure: "query-jobs-in-location"
    q_part = query.strip().replace(" ", "-").lower()
    loc_part = f"-in-{location.strip().replace(' ', '-').lower()}" if location else ""
    base_url = f"https://www.naukri.com/{q_part}-jobs{loc_part}"

    log.info(f"[Naukri] Searching: '{query}' in '{location}'")
    jobs: list[NaukriJob] = []

    with sync_playwright() as pw:
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        if headless:
            args.extend(["--window-position=-2000,-2000", "--window-size=1366,768"])
            
        browser = pw.chromium.launch(headless=False if headless else False, args=args)
        
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=USER_AGENT,
        )
        page = ctx.new_page()
        
        # Apply stealth scripts
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            delete navigator.__proto__.webdriver;
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        # Warm up by visiting homepage
        try:
            page.goto("https://www.naukri.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(random.uniform(2000, 4000))
        except Exception:
            pass

        page_num = 1
        while len(jobs) < limit:
            current_url = f"{base_url}-{page_num}" if page_num > 1 else base_url
            try:
                page.goto(current_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(random.uniform(3000, 5000))
            except Exception as e:
                log.warning(f"[Naukri] Navigation issue: {e}")

            if "Access Denied" in page.title():
                log.error("[Naukri] Blocked by Akamai 'Access Denied'.")
                break

            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            cards = soup.select("div.srp-jobtuple-wrapper, article.jobTuple, div[class*='jobTuple']")
            
            if not cards:
                log.info("[Naukri] No more job cards found.")
                break

            for card in cards:
                if len(jobs) >= limit:
                    break
                    
                title_tag = card.select_one("a.title, h2 a, a[class*='title']")
                title = clean_text(title_tag.get_text()) if title_tag else "N/A"
                if title == "N/A":
                    continue
                    
                comp_tag = card.select_one("a.comp-name, span.comp-name, a[class*='comp-name']")
                company = clean_text(comp_tag.get_text()) if comp_tag else "N/A"
                
                loc_tag = card.select_one("span.locWdth, span[class*='loc']")
                job_loc = clean_text(loc_tag.get_text()) if loc_tag else "N/A"
                
                exp_tag = card.select_one("span.expwdth, span[class*='exp']")
                exp = clean_text(exp_tag.get_text()) if exp_tag else "N/A"

                sal_tag = card.select_one("span.sal, span[class*='salary']")
                salary = clean_text(sal_tag.get_text()) if sal_tag else "N/A"
                
                href = ""
                if title_tag and title_tag.name == "a":
                    href = title_tag.get("href", "")
                
                job_url = href if href.startswith("http") else f"https://www.naukri.com{href}"

                jobs.append(NaukriJob(
                    search_query=query,
                    title=title,
                    company=company,
                    location=job_loc,
                    experience=exp,
                    salary=salary,
                    job_url=job_url,
                    source="Naukri"
                ))

            log.info(f"[Naukri] Extracted {len(jobs)}/{limit} jobs...")
            page_num += 1

        browser.close()
        
    return jobs

def save_jobs_csv(jobs: list[NaukriJob], filepath: Path) -> None:
    if not jobs:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[f.name for f in fields(NaukriJob)])
        writer.writeheader()
        for j in jobs:
            writer.writerow(asdict(j))
    log.info(f"Saved {len(jobs)} jobs to '{filepath}'")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Naukri Job Scraper")
    parser.add_argument("-q", "--query", action="append", default=[], help="Job search query")
    parser.add_argument("-l", "--location", default="", help="Location filter")
    parser.add_argument("--limit", type=int, default=20, help="Max jobs")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("-o", "--output-dir", default=OUTPUT_DIR, help="Output directory")
    return parser

def main() -> int:
    args = build_parser().parse_args()
    queries = args.query or []
    if not queries:
        _safe_print("No queries specified.")
        return 1

    all_jobs: list[NaukriJob] = []
    for q in queries:
        jobs = scrape_naukri_jobs(query=q, location=args.location, limit=args.limit, headless=not args.headed)
        all_jobs.extend(jobs)

    if all_jobs:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(args.output_dir)
        save_jobs_csv(all_jobs, out / f"naukri_jobs_{ts}.csv")
        
        for j in all_jobs[:5]:
            _safe_print(f"{j.company[:20]:<22s} {j.title[:45]} ({j.location})")
            
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
