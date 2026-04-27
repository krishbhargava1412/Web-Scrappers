#!/usr/bin/env python3
"""
Master runner for Indian phone number validation + Truecaller scraping.

This script:
  1. Expands every phone-like value from each CSV row.
  2. Runs local validation with phonenumbers.
  3. Runs the Truecaller Scrapy+Playwright spider for all detected numbers.
  4. Merges the output counts into a final report.

Usage:
    python run_scraper.py input.csv
    python run_scraper.py input.csv --column PhoneNumbers --output-dir ./results
    python run_scraper.py input.csv --speed balanced
    python run_scraper.py input.csv --concurrency 4 --delay 1.0 --page-pause 0.5
    python run_scraper.py input.csv --local-only
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


PHONE_COLUMN_HINTS = ["phone", "mobile", "number", "contact", "cell", "tel"]
FAKE_PATTERNS = [
    re.compile(r"^(\d)\1{9}$"),
    re.compile(r"^(0123456789|9876543210|1234567890|0{10})$"),
]
SPEED_PRESETS = {
    "safe": {
        "concurrency": 1,
        "delay": 4.0,
        "page_wait_ms": 8000,
        "page_pause": 1.5,
        "retries": 2,
        "autothrottle": True,
    },
    "balanced": {
        "concurrency": 3,
        "delay": 1.5,
        "page_wait_ms": 5000,
        "page_pause": 0.5,
        "retries": 1,
        "autothrottle": True,
    },
    "fast": {
        "concurrency": 3,
        "delay": 0.5,
        "page_wait_ms": 2500,
        "page_pause": 0.1,
        "retries": 0,
        "autothrottle": False,
    },
}


def banner():
    print(
        """
======================================================
   Indian Phone Number Validator + Scraper
       Truecaller - Scrapy - Playwright
======================================================
"""
    )


def detect_phone_column(df: pd.DataFrame, column: str | None) -> str:
    if column:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' was not found in the CSV")
        return column

    candidates = [
        c for c in df.columns
        if any(kw in c.lower() for kw in PHONE_COLUMN_HINTS)
    ]
    return candidates[0] if candidates else df.columns[0]


def extract_phone_candidates(raw) -> list[str]:
    """Return every phone-like token from a CSV cell, preserving row order."""
    if pd.isna(raw):
        return []

    text = str(raw).strip()
    if not text:
        return []

    candidates = []
    seen = set()
    pieces = re.split(r"[,;|\n]+", text)

    for piece in pieces:
        matches = re.findall(
            r"(?:\+?91|0091)?[\s\-().]*\d[\d\s\-().]{8,}\d",
            piece,
        )
        if not matches and re.search(r"\d", piece):
            matches = [piece]

        for match in matches:
            cleaned = re.sub(r"[^\d+]", "", str(match))
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                candidates.append(cleaned)

    return candidates


def normalize_indian_phone(raw):
    """Normalize a candidate to national digits accepted by libphonenumber."""
    import phonenumbers

    cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
    if not cleaned:
        return None, None

    parse_attempts = []
    if cleaned.startswith("+"):
        parse_attempts.append((cleaned, None))
    else:
        parse_attempts.append((cleaned, "IN"))
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0091"):
            parse_attempts.append(("+" + digits[2:], None))
        elif digits.startswith("91") and len(digits) > 10:
            parse_attempts.append(("+" + digits, None))
        elif len(digits) == 10:
            parse_attempts.append(("+91" + digits, None))

    for value, region in parse_attempts:
        try:
            pn = phonenumbers.parse(value, region)
        except Exception:
            continue
        if pn.country_code == 91:
            return str(pn.national_number), pn

    return None, None


def digits_for_lookup(raw) -> str:
    cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("0091"):
        cleaned = cleaned[4:]
    elif cleaned.startswith("91") and len(cleaned) > 10:
        cleaned = cleaned[2:]
    return cleaned


def is_fake_number(digits: str) -> bool:
    return any(pattern.match(digits) for pattern in FAKE_PATTERNS)


def lookup_value_for_row(row) -> str:
    if row["local_status"] == "VALID" and row["normalized_number"]:
        return row["normalized_number"]
    return digits_for_lookup(row["original_number"])


def run_local_validation(csv_file: str, column: str | None, output_dir: str):
    """Step 1: Fast local pre-validation using phonenumbers library."""
    print("Step 1: Local validation (phonenumbers library)...")

    import phonenumbers
    from phonenumbers import PhoneNumberType, carrier, geocoder, number_type

    df = pd.read_csv(csv_file, dtype=str)
    col = detect_phone_column(df, column)

    print(f"    CSV rows: {len(df)} | Phone column: '{col}'")

    results = []
    expanded_count = 0

    for row_index, row in df.iterrows():
        raw_cell = row[col]
        candidates = extract_phone_candidates(raw_cell)
        if not candidates:
            candidates = [str(raw_cell).strip()]

        expanded_count += len(candidates)

        for candidate_index, raw in enumerate(candidates, start=1):
            digits, pn = normalize_indian_phone(raw)
            rec = {
                "source_row": row_index + 2,
                "candidate_index": candidate_index,
                "original_cell": raw_cell,
                "original_number": raw,
                "normalized_number": "",
                "local_status": "INVALID",
                "local_reason": "",
                "carrier": "",
                "location": "",
                "line_type": "",
            }

            if digits is None or pn is None:
                rec["local_reason"] = "Could not parse as an Indian phone number"
            elif is_fake_number(digits):
                rec["normalized_number"] = digits
                rec["local_reason"] = "Obvious fake pattern"
            elif phonenumbers.is_valid_number(pn):
                rec["normalized_number"] = digits
                rec["local_status"] = "VALID"
                rec["local_reason"] = "Passed local validation"
                rec["carrier"] = carrier.name_for_number(pn, "en") or ""
                rec["location"] = geocoder.description_for_number(pn, "en") or "India"
                rec["line_type"] = {
                    PhoneNumberType.MOBILE: "Mobile",
                    PhoneNumberType.FIXED_LINE: "Landline",
                    PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed/Mobile",
                    PhoneNumberType.TOLL_FREE: "Toll-free",
                }.get(number_type(pn), "Unknown")
            else:
                rec["normalized_number"] = digits
                rec["local_reason"] = "Invalid per libphonenumber"

            for c in df.columns:
                rec[f"csv_{c}"] = row[c]

            results.append(rec)

    result_df = pd.DataFrame(results)
    os.makedirs(output_dir, exist_ok=True)

    valid_local = result_df[result_df["local_status"] == "VALID"]
    invalid_local = result_df[result_df["local_status"] == "INVALID"]

    all_for_scraper = os.path.join(output_dir, "_all_for_scraping.csv")
    scraper_df = result_df.copy()
    scraper_df["phone"] = scraper_df.apply(lookup_value_for_row, axis=1)
    scraper_df = scraper_df[scraper_df["phone"].astype(str).str.len() > 0]
    scraper_df.to_csv(all_for_scraper, index=False, encoding="utf-8-sig")

    valid_for_scraper = os.path.join(output_dir, "_valid_for_scraping.csv")
    valid_scraper_df = valid_local.copy()
    valid_scraper_df["phone"] = valid_scraper_df["normalized_number"]
    valid_scraper_df.to_csv(valid_for_scraper, index=False, encoding="utf-8-sig")

    local_invalid_path = os.path.join(output_dir, "local_invalid.csv")
    invalid_local.to_csv(local_invalid_path, index=False, encoding="utf-8-sig")

    print(f"    Phone candidates found: {expanded_count}")
    print(f"    Locally valid         : {len(valid_local)}")
    print(f"    Locally invalid       : {len(invalid_local)}")
    print(f"    Truecaller queue      : {len(scraper_df)} numbers (all detected candidates)")
    print(f"    Local invalid saved to: {local_invalid_path}")

    return all_for_scraper, col, len(scraper_df), len(invalid_local)


def resolve_speed_options(args) -> dict:
    options = SPEED_PRESETS[args.speed].copy()
    for key in ("concurrency", "delay", "page_wait_ms", "page_pause", "retries"):
        value = getattr(args, key)
        if value is not None:
            options[key] = value
    if args.autothrottle is not None:
        options["autothrottle"] = args.autothrottle
    return options


def run_scraper(csv_file: str, column: str, output_dir: str, speed_options: dict):
    """Step 2: Run Scrapy+Playwright spider on pre-validated numbers."""
    print("\nStep 2: Truecaller scraping (Scrapy + Playwright)...")
    print(
        "    Speed: "
        f"concurrency={speed_options['concurrency']}, "
        f"delay={speed_options['delay']}s, "
        f"page_wait={speed_options['page_wait_ms']}ms, "
        f"page_pause={speed_options['page_pause']}s, "
        f"retries={speed_options['retries']}, "
        f"autothrottle={speed_options['autothrottle']}"
    )
    print("    Note: higher speed may increase blocks/rate limits.\n")

    project_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        "truecaller",
        "-a",
        f"csv_file={csv_file}",
        "-a",
        f"phone_column={column}",
        "-a",
        f"output_dir={output_dir}",
        "-a",
        f"page_wait_ms={speed_options['page_wait_ms']}",
        "-a",
        f"page_pause={speed_options['page_pause']}",
        "-s",
        f"CONCURRENT_REQUESTS={speed_options['concurrency']}",
        "-s",
        f"DOWNLOAD_DELAY={speed_options['delay']}",
        "-s",
        f"AUTOTHROTTLE_ENABLED={str(speed_options['autothrottle'])}",
        "-s",
        f"AUTOTHROTTLE_TARGET_CONCURRENCY={speed_options['concurrency']}",
        "-s",
        f"RETRY_TIMES={speed_options['retries']}",
        "-s",
        f"PLAYWRIGHT_MAX_PAGES_PER_CONTEXT={speed_options['concurrency']}",
        "-s",
        "PLAYWRIGHT_MAX_CONTEXTS=1",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            env=env,
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"\nWarning: Scrapy exited with code {result.returncode}")
    except Exception as e:
        print(f"\nFailed to run Scrapy: {e}")


def merge_and_report(output_dir: str):
    """Step 3: Merge all results into final report."""
    print("\nStep 3: Merging results...")

    files = {
        "local_valid": os.path.join(output_dir, "_valid_for_scraping.csv"),
        "scrape_queue": os.path.join(output_dir, "_all_for_scraping.csv"),
        "scraped_valid": os.path.join(output_dir, "scraped_valid.csv"),
        "scraped_invalid": os.path.join(output_dir, "scraped_invalid.csv"),
        "scraped_blocked": os.path.join(output_dir, "scraped_blocked.csv"),
        "local_invalid": os.path.join(output_dir, "local_invalid.csv"),
    }

    counts = {}
    for key, path in files.items():
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, dtype=str)
                counts[key] = len(df)
            except pd.errors.EmptyDataError:
                counts[key] = 0
        else:
            counts[key] = 0

    scraped_total = counts["scraped_valid"] + counts["scraped_invalid"] + counts["scraped_blocked"]
    total = counts["scrape_queue"] or (counts["local_valid"] + counts["local_invalid"])
    report_path = os.path.join(output_dir, "FINAL_REPORT.txt")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 60,
        "  INDIAN PHONE NUMBER - FINAL VALIDATION REPORT",
        f"  Generated: {ts}",
        "=" * 60,
        f"  Total numbers processed  : {total}",
        "",
        "  Local Validation",
        f"  Passed local check       : {counts['local_valid']}",
        f"  Failed local check       : {counts['local_invalid']}",
        f"  Queued for Truecaller    : {counts['scrape_queue']}",
        "",
        "  Truecaller Scraping",
        f"  Submitted/finished       : {scraped_total} of {counts['scrape_queue']}",
        f"  Valid (confirmed)        : {counts['scraped_valid']}",
        f"  Invalid/Not found        : {counts['scraped_invalid']}",
        f"  Blocked by site          : {counts['scraped_blocked']}",
        "",
        "  Output Files",
        f"  scraped_valid.csv        -> {counts['scraped_valid']} confirmed real numbers",
        f"  scraped_invalid.csv      -> {counts['scraped_invalid']} not found on Truecaller",
        f"  scraped_blocked.csv      -> {counts['scraped_blocked']} blocked/rate-limited",
        f"  local_invalid.csv        -> {counts['local_invalid']} failed local validation",
        "=" * 60,
        "",
        "  NOTES:",
        "  - 'scraped_blocked' rows were rate-limited; re-run later if needed.",
        "  - Truecaller may not have records for all valid numbers.",
        "  - A number being valid does not prove it is active/in-service.",
        "=" * 60,
    ]

    report_text = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(report_text)
    print(f"\n  Report saved to: {report_path}")


def main():
    banner()
    parser = argparse.ArgumentParser(
        description="Validate Indian phone numbers from a CSV using local checks + Truecaller scraping"
    )
    parser.add_argument("csv_file", help="Input CSV file path")
    parser.add_argument("--column", default=None, help="Phone column name (auto-detected if omitted)")
    parser.add_argument("--output-dir", default="./results", help="Output directory (default: ./results)")
    parser.add_argument("--local-only", action="store_true", help="Skip Truecaller scraping")
    parser.add_argument(
        "--speed",
        choices=sorted(SPEED_PRESETS),
        default="balanced",
        help="Scrape speed preset. Use safe if Truecaller blocks; fast if you accept more blocks.",
    )
    parser.add_argument("--concurrency", type=int, default=None, help="Override concurrent Playwright requests")
    parser.add_argument("--delay", type=float, default=None, help="Override delay between requests in seconds")
    parser.add_argument("--page-wait-ms", type=int, default=None, help="Override page network-idle wait in milliseconds")
    parser.add_argument("--page-pause", type=float, default=None, help="Override extra JS render pause in seconds")
    parser.add_argument("--retries", type=int, default=None, help="Override retry count")
    throttle = parser.add_mutually_exclusive_group()
    throttle.add_argument("--autothrottle", dest="autothrottle", action="store_true", default=None)
    throttle.add_argument("--no-autothrottle", dest="autothrottle", action="store_false")
    args = parser.parse_args()

    scrape_csv, _col, n_to_scrape, _n_invalid = run_local_validation(
        args.csv_file,
        args.column,
        args.output_dir,
    )

    if args.local_only:
        print("\n--local-only flag set. Skipping Truecaller scraping.")
        return

    if n_to_scrape == 0:
        print("\nNo numbers to scrape. No phone-like values were detected.")
        return

    speed_options = resolve_speed_options(args)
    run_scraper(scrape_csv, "phone", args.output_dir, speed_options)
    merge_and_report(args.output_dir)


if __name__ == "__main__":
    main()
