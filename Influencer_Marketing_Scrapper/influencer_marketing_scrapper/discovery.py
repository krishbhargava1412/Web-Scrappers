from __future__ import annotations

import logging
from dataclasses import dataclass
from xml.etree import ElementTree
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from bs4 import BeautifulSoup

from .http import HttpClient
from .models import MarketConfig, SearchDebugRecord, SearchResult

log = logging.getLogger(__name__)


PLATFORM_DOMAINS = {
    "instagram": "instagram.com",
    "facebook": "facebook.com",
    "tiktok": "tiktok.com",
    "youtube": "youtube.com",
    "x": "x.com",
    "linkedin": "linkedin.com",
}

SEARCH_ENGINES = {"duckduckgo", "bing", "bing_rss", "bing_browser", "youtube_native"}


@dataclass(frozen=True)
class SearchEngineSpec:
    name: str
    url: str
    query_param: str


ENGINE_SPECS = {
    "duckduckgo": SearchEngineSpec(
        name="duckduckgo",
        url="https://html.duckduckgo.com/html/",
        query_param="q",
    ),
    "bing": SearchEngineSpec(
        name="bing",
        url="https://www.bing.com/search",
        query_param="q",
    ),
    "bing_rss": SearchEngineSpec(
        name="bing_rss",
        url="https://www.bing.com/search",
        query_param="q",
    ),
    "bing_browser": SearchEngineSpec(
        name="bing_browser",
        url="https://www.bing.com/search",
        query_param="q",
    ),
    "youtube_native": SearchEngineSpec(
        name="youtube_native",
        url="https://www.youtube.com/results",
        query_param="search_query",
    ),
}

PROFILE_PATH_HINTS = {
    "instagram": [],
    "facebook": ["people", "profile.php", "pages", "public"],
    "tiktok": ["@"],
    "youtube": ["@", "channel", "c", "user"],
    "x": [],
    "linkedin": ["in", "company"],
}


def build_queries(market: MarketConfig, platform: str) -> list[str]:
    geo_parts = market.countries or [market.name]
    city_parts = market.cities or [""]
    niches = market.niches or [""]
    search_terms = market.search_terms or ["influencer"]

    queries: list[str] = []
    seen: set[str] = set()

    for geo in geo_parts:
        for city in city_parts:
            for niche in niches:
                for term in search_terms:
                    parts = [part for part in [niche, term, city, geo] if part]
                    query = " ".join(parts)
                    if query and query not in seen:
                        seen.add(query)
                        queries.append(query)

    return queries


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [])
        if target:
            return target[0]
    if parsed.netloc.endswith("bing.com"):
        target = parse_qs(parsed.query).get("r", [])
        if target:
            return unquote(target[0])
        target = parse_qs(parsed.query).get("u", [])
        if target:
            return unquote(target[0])
        target = parse_qs(parsed.query).get("url", [])
        if target:
            return unquote(target[0])
    return url


def _absolute_platform_url(platform: str, href: str) -> str:
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if platform == "youtube":
        return "https://www.youtube.com" + href
    return href


def _build_search_phrases(platform: str, domain: str, query: str) -> list[str]:
    exclusions = {
        "instagram": " -site:instagram.com/p/ -site:instagram.com/reel/ -site:instagram.com/reels/ -site:instagram.com/explore/",
        "facebook": " -site:facebook.com/reel/ -site:facebook.com/watch/ -site:facebook.com/groups/",
        "tiktok": " -site:tiktok.com/tag/",
        "youtube": " -site:youtube.com/watch",
        "x": " -site:x.com/search",
        "linkedin": " -site:linkedin.com/jobs/ -site:linkedin.com/feed/",
    }
    variants = [
        f"site:{domain} {query}{exclusions.get(platform, '')}",
        f"site:{domain} {query} influencer",
        f"site:{domain} {query} creator",
    ]
    seen: set[str] = set()
    phrases: list[str] = []
    for item in variants:
        normalized = " ".join(item.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            phrases.append(normalized)
    return phrases


def _is_profile_like_url(platform: str, url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if not path:
        return False

    if platform == "instagram":
        blocked = {"explore", "accounts", "reel", "reels", "p", "stories", "tv", "about"}
        first = path.split("/", 1)[0].lower()
        return first not in blocked and "." not in first

    if platform == "facebook":
        blocked = {"watch", "reel", "share", "groups", "marketplace", "gaming", "events"}
        first = path.split("/", 1)[0].lower()
        return first not in blocked

    if platform == "tiktok":
        return "/@" in parsed.path or path.startswith("@")

    if platform == "youtube":
        first = path.split("/", 1)[0].lower()
        return first in {"@", "channel", "c", "user"} or path.startswith("@")

    if platform == "x":
        blocked = {"home", "explore", "search", "i", "settings", "messages", "intent", "share"}
        first = path.split("/", 1)[0].lower()
        return first not in blocked

    if platform == "linkedin":
        first = path.split("/", 1)[0].lower()
        return first in {"in", "company"}

    return host.endswith(PLATFORM_DOMAINS[platform])


def _parse_duckduckgo_results(
    soup: BeautifulSoup,
    query: str,
    platform: str,
    market_name: str,
    engine_name: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for node in soup.select("div.result"):
        link = node.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        results.append(
            SearchResult(
                title=link.get_text(" ", strip=True),
                url=_normalize_url(link["href"].strip()),
                snippet=(node.select_one(".result__snippet") or node).get_text(" ", strip=True),
                query=query,
                platform=platform,
                market=market_name,
                engine=engine_name,
            )
        )
    return results


def _parse_bing_results(
    soup: BeautifulSoup,
    query: str,
    platform: str,
    market_name: str,
    engine_name: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    nodes = soup.select("li.b_algo, .b_algo, main li, #b_results > li")
    if not nodes:
        nodes = soup.select("a[href]")

    for node in nodes:
        link = node if getattr(node, "name", "") == "a" else node.select_one("h2 a, a[href]")
        if not link or not link.get("href"):
            continue
        href = _normalize_url(link["href"].strip())
        if not href.startswith("http"):
            continue
        snippet_node = None
        if getattr(node, "name", "") != "a":
            snippet_node = node.select_one(".b_caption p, .b_snippet, p")
        results.append(
            SearchResult(
                title=link.get_text(" ", strip=True),
                url=href,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                query=query,
                platform=platform,
                market=market_name,
                engine=engine_name,
            )
        )
    return results


def _parse_youtube_native_results(
    soup: BeautifulSoup,
    query: str,
    market_name: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    selectors = [
        'a[href^="/@"]',
        'a[href^="/channel/"]',
        'a[href^="/c/"]',
        'a[href^="/user/"]',
    ]

    for selector in selectors:
        for link in soup.select(selector):
            href = link.get("href", "").strip()
            if not href:
                continue
            url = _absolute_platform_url("youtube", href)
            if url in seen:
                continue
            seen.add(url)
            title = link.get("title", "").strip() or link.get_text(" ", strip=True) or url
            if not title:
                title = url
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet="",
                    query=query,
                    platform="youtube",
                    market=market_name,
                    engine="youtube_native",
                )
            )
    return results


def _extract_direct_domain_links(
    soup: BeautifulSoup,
    query: str,
    platform: str,
    market_name: str,
    domain: str,
    engine_name: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        href = _normalize_url(link.get("href", "").strip())
        if not href.startswith("http"):
            continue
        if domain not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        title = link.get_text(" ", strip=True) or href
        results.append(
            SearchResult(
                title=title,
                url=href,
                snippet="",
                query=query,
                platform=platform,
                market=market_name,
                engine=engine_name,
            )
        )
    return results


def _parse_bing_rss_results(
    xml_text: str,
    query: str,
    platform: str,
    market_name: str,
    engine_name: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return results

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        if not link:
            continue
        results.append(
            SearchResult(
                title=title,
                url=link,
                snippet=description,
                query=query,
                platform=platform,
                market=market_name,
                engine=engine_name,
            )
        )
    return results


class BrowserSearchSession:
    def __init__(self) -> None:
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BrowserSearchSession | None":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.warning("Playwright is not installed, so browser-based discovery is unavailable.")
            return None

        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
            self.context = self.browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="Asia/Kolkata",
                java_script_enabled=True,
            )
            self.page = self.context.new_page()
            self.page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,avi}",
                lambda route: route.abort(),
            )
            return self
        except Exception as exc:
            log.warning("Failed to start Playwright browser discovery: %s", exc)
            self.close()
            return None

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self.page is not None:
            self.page.close()
            self.page = None
        if self.context is not None:
            self.context.close()
            self.context = None
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

    def search_bing(
        self,
        search_phrase: str,
        platform: str,
        market_name: str,
        source_query: str,
        domain: str,
    ) -> list[SearchResult]:
        if self.page is None:
            return []

        url = f"https://www.bing.com/search?{urlencode({'q': search_phrase})}"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            try:
                self.page.wait_for_selector("li.b_algo, #b_results, main", timeout=10_000)
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        except Exception as exc:
            log.warning("[%s/%s] bing_browser navigation failed for query '%s': %s", market_name, platform, source_query, exc)
            return []

        html = self.page.content()
        soup = BeautifulSoup(html, "lxml")
        results = _parse_bing_results(soup, source_query, platform, market_name, "bing_browser")
        if results:
            return results
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        log.info("[%s/%s] bing_browser page title for '%s': %s", market_name, platform, source_query, title)
        return _extract_direct_domain_links(soup, source_query, platform, market_name, domain, "bing_browser")

    def search_youtube(
        self,
        search_phrase: str,
        market_name: str,
        source_query: str,
    ) -> list[SearchResult]:
        if self.page is None:
            return []

        url = f"https://www.youtube.com/results?{urlencode({'search_query': search_phrase})}"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            try:
                self.page.wait_for_selector(
                    'a[href^="/@"], a[href^="/channel/"], a[href^="/c/"], a[href^="/user/"]',
                    timeout=10_000,
                )
            except Exception:
                pass
            self.page.wait_for_timeout(2000)
        except Exception as exc:
            log.warning("[youtube_native] navigation failed for query '%s': %s", source_query, exc)
            return []

        html = self.page.content()
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        log.info("[youtube_native] page title for '%s': %s", source_query, title)
        return _parse_youtube_native_results(soup, source_query, market_name)


def _search_with_engine(
    client: HttpClient,
    engine_name: str,
    domain: str,
    query: str,
    platform: str,
    market_name: str,
    browser_session: BrowserSearchSession | None = None,
) -> list[SearchResult]:
    phrases = _build_search_phrases(platform, domain, query)
    for search_phrase in phrases:
        if engine_name == "youtube_native":
            if platform != "youtube":
                return []
            if browser_session is None:
                log.warning("[%s/%s] youtube_native is unavailable because the browser session did not start.", market_name, platform)
                return []
            results = browser_session.search_youtube(search_phrase.replace(f"site:{domain} ", ""), market_name, query)
            if results:
                return results
            continue
        if engine_name == "bing_browser":
            if browser_session is None:
                log.warning("[%s/%s] bing_browser is unavailable because the browser session did not start.", market_name, platform)
                return []
            results = browser_session.search_bing(search_phrase, platform, market_name, query, domain)
            if results:
                return results
            continue

        spec = ENGINE_SPECS[engine_name]
        html = client.get_text(
            spec.url,
            params={
                spec.query_param: search_phrase,
                **({"format": "rss"} if engine_name == "bing_rss" else {}),
            },
        )
        client.pause()
        if not html:
            continue

        if engine_name == "duckduckgo":
            soup = BeautifulSoup(html, "lxml")
            results = _parse_duckduckgo_results(soup, query, platform, market_name, engine_name)
        elif engine_name == "bing_rss":
            results = _parse_bing_rss_results(html, query, platform, market_name, engine_name)
        else:
            soup = BeautifulSoup(html, "lxml")
            results = _parse_bing_results(soup, query, platform, market_name, engine_name)

        if results:
            return results

    log.warning("[%s/%s] %s returned no HTML or no parseable results for query: %s", market_name, platform, engine_name, query)
    return []


def discover_profiles(
    client: HttpClient,
    market: MarketConfig,
    platform: str,
    limit_per_query: int,
    search_engines: list[str],
    max_queries_per_platform: int | None = None,
    stop_after_empty_queries: int | None = None,
) -> tuple[list[SearchResult], list[SearchDebugRecord]]:
    domain = PLATFORM_DOMAINS[platform]
    results: list[SearchResult] = []
    debug_records: list[SearchDebugRecord] = []
    seen_urls: set[str] = set()
    queries = build_queries(market, platform)
    if max_queries_per_platform is not None:
        queries = queries[:max_queries_per_platform]
    consecutive_empty_queries = 0

    needs_browser = "bing_browser" in search_engines or "youtube_native" in search_engines
    with BrowserSearchSession() if needs_browser else _null_browser_session() as browser_session:
        for query in queries:
            log.info("[%s/%s] Searching query: %s", market.name, platform, query)
            count = 0
            skipped_domain: list[str] = []
            skipped_profile: list[str] = []
            saw_raw_results = False
            for engine_name in search_engines:
                log.info("[%s/%s] Trying search engine: %s", market.name, platform, engine_name)
                engine_results = _search_with_engine(
                    client=client,
                    engine_name=engine_name,
                    domain=domain,
                    query=query,
                    platform=platform,
                    market_name=market.name,
                    browser_session=browser_session,
                )
                if engine_results:
                    saw_raw_results = True
                    log.info(
                        "[%s/%s] %s returned %s raw result(s) for query: %s",
                        market.name,
                        platform,
                        engine_name,
                        len(engine_results),
                        query,
                    )
                else:
                    log.info(
                        "[%s/%s] %s returned 0 raw result(s) for query: %s",
                        market.name,
                        platform,
                        engine_name,
                        query,
                    )
                engine_count = 0
                for result in engine_results:
                    if result.url in seen_urls:
                        debug_records.append(
                            SearchDebugRecord(
                                market=market.name,
                                platform=platform,
                                engine=result.engine or engine_name,
                                query=query,
                                title=result.title,
                                raw_url=result.url,
                                normalized_url=result.url,
                                reason="duplicate_url",
                            )
                        )
                        continue
                    if domain not in result.url:
                        if len(skipped_domain) < 3:
                            skipped_domain.append(result.url)
                        debug_records.append(
                            SearchDebugRecord(
                                market=market.name,
                                platform=platform,
                                engine=result.engine or engine_name,
                                query=query,
                                title=result.title,
                                raw_url=result.url,
                                normalized_url=result.url,
                                reason="non_target_domain",
                            )
                        )
                        continue
                    if not _is_profile_like_url(platform, result.url):
                        if len(skipped_profile) < 3:
                            skipped_profile.append(result.url)
                        debug_records.append(
                            SearchDebugRecord(
                                market=market.name,
                                platform=platform,
                                engine=result.engine or engine_name,
                                query=query,
                                title=result.title,
                                raw_url=result.url,
                                normalized_url=result.url,
                                reason="non_profile_like_url",
                            )
                        )
                        continue

                    seen_urls.add(result.url)
                    results.append(result)
                    debug_records.append(
                        SearchDebugRecord(
                            market=market.name,
                            platform=platform,
                            engine=result.engine or engine_name,
                            query=query,
                            title=result.title,
                            raw_url=result.url,
                            normalized_url=result.url,
                            reason="accepted",
                        )
                    )
                    count += 1
                    engine_count += 1
                    if count >= limit_per_query:
                        break

                if engine_count > 0 or count >= limit_per_query:
                    log.info(
                        "[%s/%s] %s yielded %s usable profile URL(s) for query: %s",
                        market.name,
                        platform,
                        engine_name,
                        engine_count,
                        query,
                    )
                    break

            log.info("[%s/%s] Collected %s result(s) for query: %s", market.name, platform, count, query)
            if count == 0 and saw_raw_results:
                if skipped_domain:
                    log.info(
                        "[%s/%s] Sample skipped non-domain URL(s): %s",
                        market.name,
                        platform,
                        " | ".join(skipped_domain),
                    )
                if skipped_profile:
                    log.info(
                        "[%s/%s] Sample skipped non-profile URL(s): %s",
                        market.name,
                        platform,
                        " | ".join(skipped_profile),
                    )
            if count == 0:
                consecutive_empty_queries += 1
            else:
                consecutive_empty_queries = 0
            if stop_after_empty_queries is not None and consecutive_empty_queries >= stop_after_empty_queries:
                log.info(
                    "[%s/%s] Stopping early after %s consecutive empty querie(s).",
                    market.name,
                    platform,
                    consecutive_empty_queries,
                )
                break

    return results, debug_records


class _null_browser_session:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        return None
