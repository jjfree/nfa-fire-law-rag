import time
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings


@dataclass
class FetchedPage:
    url: str
    text: str
    content_type: str
    status_code: int


class HttpFetcher:
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"},
        )
        self._last_fetch = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_fetch
        wait = self.settings.crawl_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        wait=wait_exponential(multiplier=0.7, min=0.7, max=5),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def fetch(self, url: str) -> FetchedPage:
        self._throttle()
        response = self.client.get(url)
        self._last_fetch = time.monotonic()
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        # httpx uses charset from header; fall back to UTF-8. NFA pages are usually UTF-8.
        if response.encoding is None:
            response.encoding = "utf-8"
        return FetchedPage(str(response.url), response.text, content_type, response.status_code)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
