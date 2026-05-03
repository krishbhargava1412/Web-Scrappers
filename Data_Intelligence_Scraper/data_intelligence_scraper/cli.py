from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .pipeline import run_scraper

DEFAULT_OUTPUT = Path("output") / "data_intelligence.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Data & Intelligence records from SERP, RSS feeds, GitHub, and WHOIS."
    )
    parser.add_argument("--mode", choices=["news", "github", "serp", "whois"], required=True)
    parser.add_argument("-q", "--query", action="append", default=[], help="Search query. Repeat for multiple queries.")
    parser.add_argument("--feed-url", action="append", default=[], help="RSS/Atom feed URL. Repeat for multiple feeds.")
    parser.add_argument("--domain", action="append", default=[], help="Domain for WHOIS lookup. Repeat for multiple domains.")
    parser.add_argument("--github-language", default="", help="Optional GitHub language qualifier.")
    parser.add_argument("--github-topic", default="", help="Optional GitHub topic qualifier.")
    parser.add_argument(
        "--serp-provider",
        choices=["auto", "google", "duckduckgo"],
        default="auto",
        help="SERP provider. Auto tries Google first, then DuckDuckGo HTML.",
    )
    parser.add_argument(
        "--serp-browser",
        choices=["never", "auto", "always"],
        default="never",
        help="Use Chromium for SERP pages. Use with --serp-headed for challenge pages.",
    )
    parser.add_argument("--serp-headed", action="store_true", help="Show Chromium when SERP browser mode is used.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum records per input.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="CSV output path.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Network timeout in seconds.")
    parser.add_argument("--use-env-proxies", action="store_true", help="Honor HTTP(S)_PROXY environment variables.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")
    _validate_inputs(args)

    records = run_scraper(
        mode=args.mode,
        output=args.output,
        limit=args.limit,
        queries=[query.strip() for query in args.query if query.strip()],
        feed_urls=[url.strip() for url in args.feed_url if url.strip()],
        domains=[domain.strip() for domain in args.domain if domain.strip()],
        github_language=args.github_language,
        github_topic=args.github_topic,
        serp_provider=args.serp_provider,
        serp_browser=args.serp_browser,
        serp_headed=args.serp_headed,
        json_output=args.json_output,
        timeout=args.timeout,
        use_env_proxies=args.use_env_proxies,
    )
    print(f"Done! {len(records)} intelligence records saved to '{args.output}'")
    return 0


def _validate_inputs(args: argparse.Namespace) -> None:
    if args.mode in {"github", "serp"} and not [query for query in args.query if query.strip()]:
        raise SystemExit(f"Provide at least one --query for {args.mode} mode.")
    if args.mode == "news" and not [url for url in args.feed_url if url.strip()]:
        raise SystemExit("Provide at least one --feed-url for news mode.")
    if args.mode == "whois" and not [domain for domain in args.domain if domain.strip()]:
        raise SystemExit("Provide at least one --domain for whois mode.")
