import ssl
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass
class FetchedPage:
    url: str
    text: str
    content_type: str
    status_code: int


class CrawlBlockedError(RuntimeError):
    """Raised when the source asks the crawler to stop or slow down."""


class AttachmentTooLargeError(RuntimeError):
    """Raised when an attachment exceeds the configured safety limit."""


class HttpFetcher:
    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            # Use the OS trust store so managed Windows PCs can validate
            # enterprise/intercepting CA chains without disabling TLS checks.
            verify=ssl.create_default_context(),
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
        )
        self._last_fetch = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_fetch
        wait = self.settings.crawl_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _fetch_once(self, url: str) -> FetchedPage:
        self._throttle()
        response = self.client.get(url)
        self._last_fetch = time.monotonic()
        if response.status_code in (403, 429):
            retry_after = response.headers.get("retry-after", "")
            wait_hint = f" Retry-After={retry_after}" if retry_after else ""
            raise CrawlBlockedError(
                f"NFA returned HTTP {response.status_code}; stopping crawl to avoid access blocking.{wait_hint}"
            )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if response.encoding is None:
            response.encoding = response.charset_encoding or "utf-8"
        return FetchedPage(str(response.url), response.text, content_type, response.status_code)

    def fetch_bytes(self, url: str) -> tuple[str, bytes]:
        """Fetch a same-host binary attachment while preserving its content type."""
        self._throttle()
        with self.client.stream("GET", url) as response:
            self._last_fetch = time.monotonic()
            if response.status_code in (403, 429):
                retry_after = response.headers.get("retry-after", "")
                wait_hint = f" Retry-After={retry_after}" if retry_after else ""
                raise CrawlBlockedError(
                    f"NFA returned HTTP {response.status_code}; stopping crawl to avoid access blocking.{wait_hint}"
                )
            response.raise_for_status()
            limit = self.settings.max_attachment_bytes
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > limit:
                raise AttachmentTooLargeError(f"attachment exceeds {limit} bytes: {url}")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > limit:
                    raise AttachmentTooLargeError(f"attachment exceeds {limit} bytes: {url}")
                chunks.append(chunk)
            return response.headers.get("content-type", ""), b"".join(chunks)

    def fetch(self, url: str) -> FetchedPage:
        max_attempts = max(1, self.settings.http_max_retries)
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._fetch_once(url)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise
                time.sleep(min(5.0, 0.7 * (2 ** (attempt - 1))))
        if last_exc:
            raise last_exc
        raise RuntimeError("unreachable")

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
