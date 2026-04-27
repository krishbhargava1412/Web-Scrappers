#!/usr/bin/env python3
"""Fetch latest stock prices for complete supported exchange universes.

Supported universes:
- India: NSE equity list
- US: Nasdaq-listed plus other US exchange-listed symbols from Nasdaq Trader

Price source:
- Yahoo Finance quote endpoint, queried in batches with no API key.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

import requests


NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class StockSymbol:
    symbol: str
    yahoo_symbol: str
    name: str
    exchange: str
    country: str
    source: str


@dataclass
class StockPrice:
    symbol: str
    yahoo_symbol: str
    name: str
    exchange: str
    country: str
    currency: str
    price: str
    change: str
    change_percent: str
    previous_close: str
    open_price: str
    day_high: str
    day_low: str
    volume: str
    market_cap: str
    market_state: str
    quote_time: str
    source: str
    error: str = ""


def make_session(use_env_proxies: bool) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.trust_env = use_env_proxies
    return session


def fetch_yahoo_crumb(session: requests.Session, timeout: int) -> str:
    """Fetch a valid crumb token required by Yahoo Finance API endpoints."""
    try:
        # Hit a Yahoo endpoint to establish session cookies
        session.get("https://fc.yahoo.com/", timeout=timeout)
    except requests.RequestException:
        pass  # Expected to fail with 404, but sets required cookies
    try:
        response = session.get(
            "https://query2.finance.yahoo.com/v1/test/getcrumb",
            timeout=timeout,
        )
        response.raise_for_status()
        crumb = response.text.strip()
        if crumb:
            return crumb
    except requests.RequestException as exc:
        print(f"Warning: Could not fetch Yahoo Finance crumb: {exc}")
    return ""


def fetch_text(session: requests.Session, url: str, timeout: int) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def normalize_yahoo_us_symbol(symbol: str) -> str:
    return symbol.strip().replace(".", "-")


def _strip_fieldnames(reader: csv.DictReader) -> csv.DictReader:
    """Strip whitespace from CSV column headers to handle NSE's leading-space columns."""
    if reader.fieldnames:
        reader.fieldnames = [f.strip() for f in reader.fieldnames]
    return reader


def load_nse_symbols(session: requests.Session, timeout: int) -> list[StockSymbol]:
    text = fetch_text(session, NSE_EQUITY_LIST_URL, timeout)
    reader = _strip_fieldnames(csv.DictReader(io.StringIO(text)))
    symbols: list[StockSymbol] = []
    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip()
        name = (row.get("NAME OF COMPANY") or row.get("NAME") or "").strip()
        series = (row.get("SERIES") or "").strip()
        if not symbol or series not in ("EQ", ""):
            continue
        symbols.append(
            StockSymbol(
                symbol=symbol,
                yahoo_symbol=f"{symbol}.NS",
                name=name,
                exchange="NSE",
                country="India",
                source="NSE equity list",
            )
        )
    return symbols


def load_nasdaq_listed_symbols(session: requests.Session, timeout: int) -> list[StockSymbol]:
    text = fetch_text(session, NASDAQ_LISTED_URL, timeout)
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    symbols: list[StockSymbol] = []
    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        test_issue = (row.get("Test Issue") or "").strip()
        etf = (row.get("ETF") or "").strip()
        if not symbol or symbol.startswith("File Creation Time") or test_issue == "Y" or etf == "Y":
            continue
        symbols.append(
            StockSymbol(
                symbol=symbol,
                yahoo_symbol=normalize_yahoo_us_symbol(symbol),
                name=name,
                exchange="NASDAQ",
                country="United States",
                source="Nasdaq Trader nasdaqlisted",
            )
        )
    return symbols


def load_other_us_symbols(session: requests.Session, timeout: int) -> list[StockSymbol]:
    text = fetch_text(session, NASDAQ_OTHER_LISTED_URL, timeout)
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    exchange_names = {
        "A": "NYSE American",
        "N": "NYSE",
        "P": "NYSE Arca",
        "Z": "Cboe BZX",
        "V": "IEX",
    }
    symbols: list[StockSymbol] = []
    for row in reader:
        symbol = (row.get("ACT Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        exchange_code = (row.get("Exchange") or "").strip()
        test_issue = (row.get("Test Issue") or "").strip()
        etf = (row.get("ETF") or "").strip()
        if not symbol or symbol.startswith("File Creation Time") or test_issue == "Y" or etf == "Y":
            continue
        symbols.append(
            StockSymbol(
                symbol=symbol,
                yahoo_symbol=normalize_yahoo_us_symbol(symbol),
                name=name,
                exchange=exchange_names.get(exchange_code, exchange_code or "US"),
                country="United States",
                source="Nasdaq Trader otherlisted",
            )
        )
    return symbols


def dedupe_symbols(symbols: Iterable[StockSymbol]) -> list[StockSymbol]:
    seen: set[str] = set()
    result: list[StockSymbol] = []
    for item in symbols:
        key = item.yahoo_symbol.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def resolve_universe(args: argparse.Namespace, session: requests.Session) -> list[StockSymbol]:
    selected = set(args.market)
    symbols: list[StockSymbol] = []

    if "all" in selected or "india" in selected:
        print("Loading NSE India symbol universe...")
        try:
            nse = load_nse_symbols(session, args.timeout)
            symbols.extend(nse)
            print(f"  Loaded {len(nse)} NSE symbols.")
        except Exception as exc:
            log.warning("Failed to load NSE symbols: %s", exc)
            print(f"  Warning: Could not load NSE symbols: {exc}")

    if "all" in selected or "us" in selected:
        print("Loading US symbol universe from Nasdaq Trader...")
        try:
            nasdaq = load_nasdaq_listed_symbols(session, args.timeout)
            symbols.extend(nasdaq)
            print(f"  Loaded {len(nasdaq)} Nasdaq-listed symbols.")
        except Exception as exc:
            log.warning("Failed to load Nasdaq-listed symbols: %s", exc)
            print(f"  Warning: Could not load Nasdaq symbols: {exc}")
        try:
            other = load_other_us_symbols(session, args.timeout)
            symbols.extend(other)
            print(f"  Loaded {len(other)} other US-listed symbols.")
        except Exception as exc:
            log.warning("Failed to load other US symbols: %s", exc)
            print(f"  Warning: Could not load other US symbols: {exc}")

    for symbol in args.symbol:
        raw = symbol.strip()
        if not raw:
            continue
        symbols.append(
            StockSymbol(
                symbol=raw,
                yahoo_symbol=raw,
                name="Manual symbol",
                exchange="Manual",
                country="Manual",
                source="manual",
            )
        )

    symbols = dedupe_symbols(symbols)
    if args.limit > 0:
        symbols = symbols[: args.limit]
    return symbols


def chunks(values: list[StockSymbol], size: int) -> Iterable[list[StockSymbol]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def yahoo_quote_batch(
    session: requests.Session,
    symbols: list[StockSymbol],
    timeout: int,
    crumb: str = "",
) -> tuple[dict[str, dict], str]:
    params = {"symbols": ",".join(symbol.yahoo_symbol for symbol in symbols)}
    if crumb:
        params["crumb"] = crumb
    try:
        response = session.get(YAHOO_QUOTE_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {}, str(exc)

    rows = payload.get("quoteResponse", {}).get("result", [])
    return {row.get("symbol", ""): row for row in rows if row.get("symbol")}, ""


def yahoo_chart_fallback(
    session: requests.Session, symbol: str, timeout: int, crumb: str = "",
) -> tuple[dict, str]:
    try:
        params = {}
        if crumb:
            params["crumb"] = crumb
        response = session.get(
            YAHOO_CHART_URL.format(symbol=symbol), params=params, timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("chart", {}).get("result") or []
        if not result:
            return {}, "No chart result"
        meta = result[0].get("meta", {})
        return {
            "symbol": symbol,
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "currency": meta.get("currency"),
            "regularMarketTime": meta.get("regularMarketTime"),
            "regularMarketPreviousClose": meta.get("previousClose"),
            "regularMarketDayHigh": meta.get("regularMarketDayHigh"),
            "regularMarketDayLow": meta.get("regularMarketDayLow"),
            "marketState": meta.get("marketState"),
        }, ""
    except Exception as exc:
        return {}, str(exc)


def value(row: dict, *keys: str) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key])
    return ""


def format_quote_time(raw: object) -> str:
    try:
        return (
            datetime.fromtimestamp(int(raw), tz=timezone.utc)
            .isoformat(sep=" ", timespec="seconds")
        )
    except Exception:
        return ""


def build_price(symbol: StockSymbol, quote: dict, error: str = "") -> StockPrice:
    quote_time = format_quote_time(quote.get("regularMarketTime") or quote.get("postMarketTime"))
    return StockPrice(
        symbol=symbol.symbol,
        yahoo_symbol=symbol.yahoo_symbol,
        name=value(quote, "longName", "shortName") or symbol.name,
        exchange=symbol.exchange,
        country=symbol.country,
        currency=value(quote, "currency"),
        price=value(quote, "regularMarketPrice", "postMarketPrice", "preMarketPrice"),
        change=value(quote, "regularMarketChange"),
        change_percent=value(quote, "regularMarketChangePercent"),
        previous_close=value(quote, "regularMarketPreviousClose"),
        open_price=value(quote, "regularMarketOpen"),
        day_high=value(quote, "regularMarketDayHigh"),
        day_low=value(quote, "regularMarketDayLow"),
        volume=value(quote, "regularMarketVolume"),
        market_cap=value(quote, "marketCap"),
        market_state=value(quote, "marketState"),
        quote_time=quote_time,
        source=symbol.source,
        error=error,
    )


def fetch_prices(
    args: argparse.Namespace,
    session: requests.Session,
    symbols: list[StockSymbol],
    crumb: str = "",
) -> list[StockPrice]:
    prices: list[StockPrice] = []
    total_batches = (len(symbols) + args.batch_size - 1) // args.batch_size
    for batch_index, batch in enumerate(chunks(symbols, args.batch_size), start=1):
        print(f"Fetching price batch {batch_index}/{total_batches} ({len(batch)} symbols)...")
        quote_map, batch_error = yahoo_quote_batch(session, batch, args.timeout, crumb)
        for item in batch:
            quote = quote_map.get(item.yahoo_symbol)
            error = batch_error
            if not quote and args.chart_fallback:
                quote, error = yahoo_chart_fallback(session, item.yahoo_symbol, args.timeout, crumb)
            if quote:
                prices.append(build_price(item, quote))
            else:
                prices.append(build_price(item, {}, error or "No quote returned"))
        if args.delay > 0 and batch_index < total_batches:
            time.sleep(args.delay)
    return prices


def write_csv(path: Path, rows: list[StockSymbol | StockPrice]) -> None:
    if not rows:
        log.warning("No data to write for %s — skipping file creation.", path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_json(path: Path, rows: list[StockSymbol | StockPrice]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(row) for row in rows]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_zip(output_dir: Path, csv_path: Path, symbols_path: Path, timestamp: str = "") -> Path:
    name = f"stock_market_prices_{timestamp}.zip" if timestamp else "stock_market_prices.zip"
    zip_path = output_dir / name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, csv_path.name)
        archive.write(symbols_path, symbols_path.name)
    return zip_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch latest prices for all supported India and US stocks."
    )
    parser.add_argument(
        "--market",
        action="append",
        choices=["all", "india", "us"],
        default=[],
        help="Universe to fetch. Repeatable. Default: all.",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Extra Yahoo symbol to include manually, e.g. TCS.NS, AAPL, 7203.T.",
    )
    parser.add_argument("-o", "--output-dir", default="output", help="Output folder.")
    parser.add_argument("--batch-size", type=int, default=80, help="Yahoo quote batch size (must be >= 1).")
    parser.add_argument("--delay", type=float, default=0.4, help="Delay between quote batches.")
    parser.add_argument("--timeout", type=int, default=25, help="HTTP timeout in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Limit symbol count for testing (0 = no limit).")
    parser.add_argument("--json", action="store_true", help="Also write JSON output.")
    parser.add_argument("--zip", action="store_true", help="Also create a zip archive of CSV outputs.")
    parser.add_argument("--no-chart-fallback", dest="chart_fallback", action="store_false", help="Disable per-symbol fallback lookup.")
    parser.add_argument("--use-env-proxies", action="store_true", help="Honor HTTP(S)_PROXY environment variables.")
    parser.set_defaults(chart_fallback=True)
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args()
    if not args.market and not args.symbol:
        args.market = ["all"]
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1.")

    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = make_session(args.use_env_proxies)

    print("Authenticating with Yahoo Finance...")
    crumb = fetch_yahoo_crumb(session, args.timeout)
    if crumb:
        print("Yahoo Finance crumb obtained successfully.")
    else:
        print("Warning: Running without crumb — some requests may fail with 401/403.")

    symbols = resolve_universe(args, session)
    if not symbols:
        raise SystemExit("No symbols found for the selected market(s).")

    print(f"Resolved {len(symbols)} symbols.")
    symbols_path = output_dir / f"stock_symbols_{timestamp}.csv"
    write_csv(symbols_path, symbols)

    prices = fetch_prices(args, session, symbols, crumb)
    prices_path = output_dir / f"stock_prices_{timestamp}.csv"
    write_csv(prices_path, prices)

    if args.json:
        write_json(output_dir / f"stock_prices_{timestamp}.json", prices)
    if args.zip:
        zip_path = write_zip(output_dir, prices_path, symbols_path, timestamp)
        print(f"Zip archive: {zip_path.resolve()}")

    failures = sum(1 for row in prices if row.error)
    print(f"\nSaved symbols: {symbols_path.resolve()}")
    print(f"Saved prices : {prices_path.resolve()}")
    print(f"Rows: {len(prices)} | Missing/error quotes: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
