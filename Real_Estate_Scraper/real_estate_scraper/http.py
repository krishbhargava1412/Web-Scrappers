from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def create_session(use_env_proxies: bool = False) -> requests.Session:
    session = requests.Session()
    session.trust_env = use_env_proxies
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        }
    )
    return session


def fetch_html(session: requests.Session, url: str, timeout: float = 20.0, retries: int = 2) -> str | None:
    for attempt in range(1, retries + 2):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code in {403, 429}:
                log.warning("Blocked or rate-limited by %s with HTTP %s", url, response.status_code)
                return None
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            if attempt > retries:
                log.warning("Failed to fetch %s: %s", url, exc)
                return None
            time.sleep(attempt)
    return None


def fetch_rendered_html(url: str, timeout: float = 20.0, headless: bool = True) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for browser fallback. Install dependencies and run: "
            "python -m playwright install chromium"
        )
        return None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-IN",
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            page.wait_for_timeout(2500)
            return page.content()
        except Exception as exc:
            log.warning("Browser fetch failed for %s: %s", url, exc)
            return None
        finally:
            browser.close()
