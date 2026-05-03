from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .pipeline import SITES, run_scraper

DEFAULT_OUTPUT = Path("output") / "property_listings.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape public real estate listings from MagicBricks and 99acres."
    )
    parser.add_argument(
        "--site",
        choices=["all", *SITES],
        action="append",
        default=[],
        help="Site to scrape. Repeat to select multiple sites, or use all.",
    )
    parser.add_argument(
        "-q",
        "--query",
        action="append",
        default=[],
        help="Property search query. Repeat for multiple queries.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Direct MagicBricks/99acres search results URL. Repeat for multiple URLs.",
    )
    parser.add_argument("--location", default="", help="City or area filter, e.g. Mumbai or Bengaluru.")
    parser.add_argument("--max-pages", type=int, default=2, help="Search result pages per query/site.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="CSV output path.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between page requests in seconds.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument("--use-env-proxies", action="store_true", help="Honor HTTP(S)_PROXY environment variables.")
    parser.add_argument(
        "--browser",
        choices=["auto", "always", "never"],
        default="auto",
        help="Use Chromium rendering for blocked pages. Auto falls back for 99acres.",
    )
    parser.add_argument("--headed", action="store_true", help="Show Chromium when browser rendering is used.")
    return parser


def normalize_sites(raw_sites: list[str]) -> list[str]:
    if not raw_sites or "all" in raw_sites:
        return list(SITES)
    return list(dict.fromkeys(raw_sites))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    queries = [query.strip() for query in args.query if query.strip()]
    urls = [url.strip() for url in args.url if url.strip()]
    if not queries and not urls:
        raise SystemExit("Provide at least one --query value or --url.")
    if args.max_pages < 1:
        raise SystemExit("--max-pages must be at least 1.")

    listings = run_scraper(
        sites=normalize_sites(args.site),
        queries=queries,
        location=args.location.strip(),
        max_pages=args.max_pages,
        output=args.output,
        urls=urls,
        json_output=args.json_output,
        delay=max(args.delay, 0),
        timeout=args.timeout,
        use_env_proxies=args.use_env_proxies,
        browser_mode=args.browser,
        headed=args.headed,
    )
    print(f"Done! {len(listings)} property listings saved to '{args.output}'")
    return 0
