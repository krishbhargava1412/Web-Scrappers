from __future__ import annotations

import logging
import socket
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def fetch_text(session: requests.Session, url: str, timeout: float = 20.0, retries: int = 2) -> str | None:
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


def query_whois_server(domain: str, timeout: float = 20.0) -> str | None:
    try:
        with socket.create_connection(("whois.iana.org", 43), timeout=timeout) as sock:
            sock.sendall((domain + "\r\n").encode("ascii", errors="ignore"))
            data = sock.recv(65535).decode("utf-8", errors="replace")
    except OSError as exc:
        log.warning("Failed to query IANA WHOIS for %s: %s", domain, exc)
        return None

    referral = _extract_referral_server(data)
    if not referral:
        return data

    try:
        chunks: list[bytes] = []
        with socket.create_connection((referral, 43), timeout=timeout) as sock:
            sock.sendall((domain + "\r\n").encode("ascii", errors="ignore"))
            while True:
                chunk = sock.recv(65535)
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as exc:
        log.warning("Failed to query WHOIS server %s for %s: %s", referral, domain, exc)
        return data


def _extract_referral_server(text: str) -> str | None:
    for line in text.splitlines():
        if line.lower().startswith("refer:"):
            return line.split(":", 1)[1].strip()
        if line.lower().startswith("whois:"):
            return line.split(":", 1)[1].strip()
    return None


def fetch_rendered_html(url: str, timeout: float = 20.0, headless: bool = True) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(
            "Playwright is required for SERP browser mode. Install dependencies and run: "
            "python -m playwright install chromium"
        )
        return None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            if not headless:
                log.info("Browser is visible. Complete any challenge page, then wait for results to load.")
                page.wait_for_timeout(15000)
            else:
                page.wait_for_timeout(4000)
            return page.content()
        except Exception as exc:
            log.warning("Browser fetch failed for %s: %s", url, exc)
            return None
        finally:
            browser.close()
