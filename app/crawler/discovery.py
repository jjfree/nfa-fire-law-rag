import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from app.config import get_settings


@dataclass(frozen=True)
class DiscoveredLawLink:
    title: str
    url: str
    source_key: str


NOISE_TEXT = {
    "首頁", "回上一頁", "網站導覽", "法規查詢", "最新消息", "相關連結", "English", "TOP", "回頂端"
}
LAW_HINTS = ("法", "規則", "辦法", "標準", "要點", "注意事項", "須知", "規定", "原則", "基準", "作業")


def _source_key(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("id", "no", "lawid", "uid", "sn", "lawno"):
        if key in query and query[key]:
            return f"{parsed.path}?{key}={query[key][0]}"
    return url


def discover_law_links(html: str, base_url: str) -> list[DiscoveredLawLink]:
    settings = get_settings()
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(settings.category_link_selector) if settings.category_link_selector else soup.find_all("a", href=True)
    seen: set[str] = set()
    result: list[DiscoveredLawLink] = []
    base_host = urlparse(base_url).hostname

    for a in anchors:
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname != base_host:
            continue
        if title in NOISE_TEXT or len(title) < 2:
            continue
        lower_path = parsed.path.lower()
        looks_detail = any(token in lower_path for token in ("law", "detail", "content", "show", "view"))
        looks_law_title = any(hint in title for hint in LAW_HINTS)
        has_id = bool(parsed.query)
        if not (looks_detail or (looks_law_title and has_id)):
            continue
        key = _source_key(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(DiscoveredLawLink(title=title, url=url, source_key=key))

    return result
