from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_market_configs
from .discovery import PLATFORM_DOMAINS, SEARCH_ENGINES
from .http import FetchSettings
from .pipeline import run_market_scrape

AUTO_DISCOVERY_PLATFORMS = {"youtube", "linkedin", "x"}
WEAK_DISCOVERY_PLATFORMS = {"instagram", "facebook", "tiktok"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover public influencer profiles across multiple social platforms."
    )
    parser.add_argument(
        "--config",
        default="markets.sample.json",
        help="Path to the markets JSON config file.",
    )
    parser.add_argument(
        "--market",
        action="append",
        default=[],
        help="Market name from the config. Repeat to run multiple markets.",
    )
    parser.add_argument(
        "--all-markets",
        action="store_true",
        help="Run every market defined in the config.",
    )
    parser.add_argument(
        "--platform",
        nargs="+",
        default=[],
        help=f"Override platforms. Supported: {', '.join(sorted(PLATFORM_DOMAINS))}",
    )
    parser.add_argument(
        "--limit-per-query",
        type=int,
        default=10,
        help="Maximum search hits to keep for each generated query.",
    )
    parser.add_argument(
        "--max-queries-per-platform",
        type=int,
        default=12,
        help="Cap generated market queries per platform to reduce rate-limits.",
    )
    parser.add_argument(
        "--search-engine",
        nargs="+",
        default=["youtube_native", "bing_browser", "bing_rss", "bing"],
        help=f"Search engine fallback order. Supported: {', '.join(sorted(SEARCH_ENGINES))}",
    )
    parser.add_argument(
        "--stop-after-empty-queries",
        type=int,
        default=2,
        help="Stop a platform early after this many consecutive queries return zero usable profile URLs.",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=1.0,
        help="Minimum delay between HTTP requests in seconds.",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=2.5,
        help="Maximum delay between HTTP requests in seconds.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Read timeout in seconds after a connection is established.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=6,
        help="Connection timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry count for transient HTTP errors like 429 or 503.",
    )
    parser.add_argument(
        "--use-env-proxies",
        action="store_true",
        help="Honor HTTP(S)_PROXY environment variables if your network requires them.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Root output directory for generated runs.",
    )
    parser.add_argument(
        "--seed-file",
        default="",
        help="Optional CSV or JSON file of known public profile URLs to process directly.",
    )
    parser.add_argument(
        "--history-file",
        default="output/seen_profiles.csv",
        help="CSV file used to avoid repeating the same profile URLs across runs.",
    )
    parser.add_argument(
        "--allow-weak-discovery",
        action="store_true",
        help="Allow auto-discovery attempts on weaker public-discovery platforms like instagram and facebook.",
    )
    return parser.parse_args()


def _resolve_market_names(args: argparse.Namespace, available: set[str]) -> list[str]:
    if args.all_markets:
        return sorted(available)
    if args.market:
        return args.market
    raise SystemExit("Choose --market MARKET_NAME or use --all-markets.")


def _validate_platforms(platforms: list[str]) -> list[str]:
    invalid = [platform for platform in platforms if platform not in PLATFORM_DOMAINS]
    if invalid:
        raise SystemExit(f"Unsupported platforms: {', '.join(invalid)}")
    return platforms


def _validate_search_engines(search_engines: list[str]) -> list[str]:
    invalid = [engine for engine in search_engines if engine not in SEARCH_ENGINES]
    if invalid:
        raise SystemExit(f"Unsupported search engines: {', '.join(invalid)}")
    return search_engines


def _resolve_discovery_platforms(
    requested_platforms: list[str],
    seed_file: str,
    allow_weak_discovery: bool,
) -> list[str]:
    if seed_file or allow_weak_discovery:
        return requested_platforms

    auto_platforms = [platform for platform in requested_platforms if platform in AUTO_DISCOVERY_PLATFORMS]
    skipped_platforms = [platform for platform in requested_platforms if platform in WEAK_DISCOVERY_PLATFORMS]
    if skipped_platforms:
        logging.info(
            "Skipping weaker auto-discovery platform(s) without a seed file: %s",
            ", ".join(skipped_platforms),
        )
    return auto_platforms


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    configs = load_market_configs(args.config)
    market_names = _resolve_market_names(args, set(configs))
    fetch_settings = FetchSettings(
        timeout_seconds=args.timeout,
        connect_timeout_seconds=args.connect_timeout,
        delay_min_seconds=args.delay_min,
        delay_max_seconds=args.delay_max,
        use_env_proxies=args.use_env_proxies,
        max_retries=args.retries,
    )
    output_root = Path(args.output_dir)

    try:
        for market_name in market_names:
            if market_name not in configs:
                raise SystemExit(f"Unknown market '{market_name}'. Available: {', '.join(sorted(configs))}")

            market = configs[market_name]
            requested_platforms = _validate_platforms(args.platform or market.platforms)
            platforms = _resolve_discovery_platforms(
                requested_platforms=requested_platforms,
                seed_file=args.seed_file,
                allow_weak_discovery=args.allow_weak_discovery,
            )
            if not platforms:
                raise SystemExit(
                    "No eligible platforms remain for auto-discovery. "
                    "Use --seed-file for instagram/facebook/tiktok or pass --allow-weak-discovery."
                )
            search_engines = _validate_search_engines(args.search_engine)
            output_dir = run_market_scrape(
                market=market,
                output_root=output_root,
                platforms=platforms,
                limit_per_query=args.limit_per_query,
                fetch_settings=fetch_settings,
                search_engines=search_engines,
                max_queries_per_platform=args.max_queries_per_platform,
                seed_file=Path(args.seed_file) if args.seed_file else None,
                history_file=Path(args.history_file) if args.history_file else None,
                stop_after_empty_queries=args.stop_after_empty_queries,
            )
            print(f"[{market.name}] Saved results to {output_dir}")
    except KeyboardInterrupt:
        print("\nScrape interrupted by user.")
        return 130

    return 0
