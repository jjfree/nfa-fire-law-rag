"""Bounded web-search and page-fetch support for evidence fallback.

The local Gemma model does not browse by itself.  This module is the application
controlled tool boundary: it calls Ollama's web-search API, filters results to
configured official domains, and fetches only the allowed pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.query_analysis import extract_focus_terms


class WebSearchError(RuntimeError):
    """Raised when the configured web-search service cannot be used."""


class WebSearchUnavailable(WebSearchError):
    """Raised when web search is enabled but credentials are not configured."""


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    content: str
    retrieved_at: str


def filter_relevant_web_results(
    query: str, results: list[WebSearchResult]
) -> list[WebSearchResult]:
    """Reject web evidence that misses every explicit inclusion target."""
    focus_terms = extract_focus_terms(query)
    if not focus_terms:
        return results
    return [
        result
        for result in results
        if any(
            term.lower() in f"{result.title}\n{result.content}".lower()
            for term in focus_terms
        )
    ]


def _configured_domains(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower().lstrip(".") for item in value.split(",") if item.strip())


def is_allowed_web_url(url: str, allowed_domains: tuple[str, ...]) -> bool:
    """Allow HTTPS pages on configured domains and their subdomains only."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return bool(hostname) and any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains
    )


class OllamaWebSearchClient:
    """Use Ollama's authenticated web search/fetch API with an official-domain allowlist."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.ollama_api_key
        self.search_url = settings.web_search_api_url
        self.fetch_url = settings.web_fetch_api_url
        self.timeout_seconds = settings.web_search_timeout_seconds
        self.max_results = settings.web_search_max_results
        self.max_fetch_results = settings.web_search_max_fetch_results
        self.allowed_domains = _configured_domains(settings.web_search_allowed_domains)

    def _post_json(self, url: str, payload: dict) -> dict:
        if not self.api_key:
            raise WebSearchUnavailable("OLLAMA_API_KEY 未設定，無法使用 web search fallback")
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchError(f"web search 服務失敗：{type(exc).__name__}") from exc
        if not isinstance(data, dict):
            raise WebSearchError("web search 服務回傳格式不正確")
        return data

    def search(self, query: str) -> list[WebSearchResult]:
        data = self._post_json(
            self.search_url,
            {"query": query, "max_results": self.max_results},
        )
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raise WebSearchError("web search 結果不是清單")

        retrieved_at = datetime.now(UTC).isoformat()
        results: list[WebSearchResult] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if not isinstance(url, str) or not is_allowed_web_url(url, self.allowed_domains):
                continue
            title = raw.get("title")
            content = raw.get("content")
            if not isinstance(title, str) or not title.strip():
                title = url
            if not isinstance(content, str):
                content = ""
            results.append(WebSearchResult(title.strip(), url, content.strip(), retrieved_at))
            if len(results) >= self.max_fetch_results:
                break

        enriched: list[WebSearchResult] = []
        for result in results:
            try:
                fetched = self._post_json(self.fetch_url, {"url": result.url})
            except WebSearchError:
                fetched = {}
            content = fetched.get("content") if isinstance(fetched.get("content"), str) else ""
            fetched_title = fetched.get("title")
            if not isinstance(fetched_title, str) or not fetched_title.strip():
                fetched_title = result.title
            enriched.append(
                WebSearchResult(
                    title=fetched_title.strip(),
                    url=result.url,
                    content=(content.strip() or result.content),
                    retrieved_at=result.retrieved_at,
                )
            )
        return filter_relevant_web_results(query, enriched)
