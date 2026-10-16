"""Bounded web-search and page-fetch support for evidence fallback.

The local Gemma model does not browse by itself.  This module is the application
controlled tool boundary: it calls Ollama's web-search API, filters results to
configured official domains, and fetches only the allowed pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.query_analysis import (
    extract_focus_terms,
    requests_latest_law,
    requests_official_announcement,
)


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
    source_date: str | None = None
    source_date_label: str | None = None


_SOURCE_DATE_RE = re.compile(
    r"(?P<label>法規命令發布(?:\([^)]*\))?日|發文日期|公告日期|發布日期|修正日期)"
    r"[^0-9\n]{0,24}(?:中華民國|民國)?\s*"
    r"(?P<year>\d{2,4})\s*(?:年|[-/.])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
)
_EXPLICIT_YEAR_RE = re.compile(r"(?:民國|中華民國)?\s*\d{2,4}\s*年")
_QUOTED_TITLE_RE = re.compile(r"[「『]([^」』]{4,80})[」』]")
_SAFE_TOPIC_RE = re.compile(r"^[\u3400-\u9fffA-Za-z0-9（）()、\s]+$")
_MULTIPLE_SITES_RE = re.compile(r"(?:多個|不同|數個|兩個|二個|多處|兩處|二處|2處|２處)場所|跨場所")


def official_source_date(content: str) -> tuple[str | None, str | None]:
    """Read an explicit source publication/amendment date, never a fetch date."""
    for match in _SOURCE_DATE_RE.finditer(content[:4000]):
        year = int(match.group("year"))
        if year < 1911:
            year += 1911
        try:
            value = date(year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            continue
        return value.isoformat(), match.group("label")
    return None, None


def _announcement_topic(query: str) -> str:
    topic = re.sub(r"^(?:請)?(?:搜尋|查詢|查找|找出|提供)", "", query.strip())
    topic = re.sub(r"(?:的)?(?:中央|地方)?主管機關公告.*$", "", topic)
    return topic.strip(" ？?，,。")[:80]


def _followup_query(
    query: str, first_results: list[dict], allowed_domains: tuple[str, ...]
) -> str | None:
    """Use a second bounded query to find later official versions of a named source."""
    if _EXPLICIT_YEAR_RE.search(query) and "最新" not in query:
        return None
    if requests_official_announcement(query):
        topic = _announcement_topic(query)
        source_domain: str | None = None
        for raw in first_results:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if not isinstance(url, str) or not is_allowed_web_url(url, allowed_domains):
                continue
            hostname = (urlparse(url).hostname or "").lower()
            domain = next(
                (
                    item for item in sorted(allowed_domains, key=len, reverse=True)
                    if hostname == item or hostname.endswith(f".{item}")
                ),
                None,
            )
            source_domain = source_domain or domain
            title = raw.get("title", "")
            if not isinstance(title, str):
                continue
            match = _QUOTED_TITLE_RE.search(title)
            if (
                match
                and _SAFE_TOPIC_RE.fullmatch(match.group(1))
                and (len(topic) < 4 or topic in match.group(1))
            ):
                topic = match.group(1)
                source_domain = domain
                break
        if len(topic) < 4:
            return None
        topic = " ".join(re.sub(r"[^\u3400-\u9fffA-Za-z0-9（）()、\s]", " ", topic).split())
        if len(topic) < 4:
            return None
        authority = "內政部" if "中央主管機關" in query or "內政部" in query else ""
        site = f" site:{source_domain}" if source_domain else ""
        return f"{topic} {authority} 修正 最新{site}".strip()
    if requests_latest_law(query):
        return f"site:law.moj.gov.tw/LawClass/LawAll.aspx {query} 現行 修正日期"
    # A generic question often returns only Article 13, which states appointment
    # qualifications but does not decide whether one person may cover two sites.
    # Search the authority's explanatory material for the exact disputed act.
    if "防火管理人" in query and _MULTIPLE_SITES_RE.search(query):
        return "防火管理人 不同場所 共同遴用 一位 site:nfa.gov.tw"
    return None


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
        first = self._post_json(self.search_url, {"query": query, "max_results": self.max_results})
        first_results = first.get("results", [])
        if not isinstance(first_results, list):
            raise WebSearchError("web search 結果不是清單")

        focused_results: list[dict] = []
        followup = _followup_query(query, first_results, self.allowed_domains)
        if followup:
            try:
                focused = self._post_json(
                    self.search_url, {"query": followup, "max_results": self.max_results}
                )
                if isinstance(focused.get("results"), list):
                    focused_results = focused["results"]
            except WebSearchError:
                pass  # Keep the initial official results if the precision search fails.

        retrieved_at = datetime.now(UTC).isoformat()
        results: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        for raw in [*focused_results, *first_results]:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if (
                not isinstance(url, str)
                or url in seen_urls
                or not is_allowed_web_url(url, self.allowed_domains)
            ):
                continue
            seen_urls.add(url)
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
            final_content = content.strip() or result.content
            source_date, source_date_label = official_source_date(final_content)
            enriched.append(
                WebSearchResult(
                    title=fetched_title.strip(),
                    url=result.url,
                    content=final_content,
                    retrieved_at=result.retrieved_at,
                    source_date=source_date,
                    source_date_label=source_date_label,
                )
            )
        relevant = filter_relevant_web_results(query, enriched)
        if followup and (requests_official_announcement(query) or requests_latest_law(query)):
            relevant.sort(key=lambda result: result.source_date or "", reverse=True)
        return relevant
