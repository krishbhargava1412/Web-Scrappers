from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

log = logging.getLogger(__name__)


@dataclass
class FetchSettings:
    timeout_seconds: int = 20
    connect_timeout_seconds: int = 6
    delay_min_seconds: float = 1.0
    delay_max_seconds: float = 2.5
    use_env_proxies: bool = False
    max_retries: int = 1


class HttpClient:
    def __init__(self, settings: FetchSettings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.trust_env = settings.use_env_proxies
        retry = Retry(
            total=settings.max_retries,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_text(self, url: str, params: dict[str, str] | None = None) -> str | None:
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=(
                    self.settings.connect_timeout_seconds,
                    self.settings.timeout_seconds,
                ),
            )
            response.raise_for_status()
        except requests.Timeout:
            log.warning("Timed out fetching %s", url)
            return None
        except requests.RequestException as exc:
            log.warning("Request failed for %s: %s", url, exc)
            return None

        return response.text

    def pause(self) -> None:
        time.sleep(
            random.uniform(
                self.settings.delay_min_seconds,
                self.settings.delay_max_seconds,
            )
        )
