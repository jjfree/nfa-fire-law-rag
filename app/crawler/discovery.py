import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.config import get_settings
from app.crawler.nfa_urls import canonical_source_key, is_probable_law_detail_url


@dataclass(frozen=True)
class DiscoveredLawLink:
    title: str
    url: str
    source_key: str


NOISE_TEXT = {
    "首頁",
    "回上一頁",
    "網站導覽",
    "法規查詢",
    "最新消息",
    "相關連結",
    "English",
    "TOP",
    "回頂端",
    "列印",
    "所有條文",
}


def _clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Old NFA lists sometimes prefix an item with an ordinal/date marker.
    text = re.sub(r"^\d+[\.、]\s*", "", text)
    return text.strip()


def _is_retired_title(title: str) -> bool:
    """Return whether the NFA list marks a law as retired."""
    normalized = re.sub(r"\s+", "", title)
    return normalized.startswith("廢")


def discover_law_links(html: str, base_url: str) -> list[DiscoveredLawLink]:
    settings = get_settings()
    soup = BeautifulSoup(html, "html.parser")
    anchors = (
        soup.select(settings.category_link_selector)
        if settings.category_link_selector
        else soup.find_all("a", href=True)
    )
    seen: set[str] = set()
    result: list[DiscoveredLawLink] = []
    base_host = (urlparse(base_url).hostname or "").lower()

    for a in anchors:
        title = _clean_title(a.get_text(" ", strip=True) or a.get("title", ""))
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() != base_host:
            continue
        if title in NOISE_TEXT or len(title) < 2:
            continue
        if _is_retired_title(title):
            continue

        # Category/news/navigation pages often have law-like titles and query
        # strings. Only detail-shaped endpoints are valid crawl targets.
        if not is_probable_law_detail_url(url):
            continue

        key = canonical_source_key(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(DiscoveredLawLink(title=title, url=url, source_key=key))

    return result
