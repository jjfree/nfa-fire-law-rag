import json
import re
from dataclasses import dataclass
from hashlib import sha256

from bs4 import BeautifulSoup

from app.config import get_settings


@dataclass
class ParsedChunk:
    seq: int
    article_label: str | None
    heading: str | None
    content: str


@dataclass
class ParsedLaw:
    title: str
    text: str
    metadata: dict[str, str]
    content_hash: str
    chunks: list[ParsedChunk]


ARTICLE_RE = re.compile(r"^(第\s*[一二三四五六七八九十百千〇○零兩\d\-之]+\s*條(?:\s*之\s*[一二三四五六七八九十百千\d]+)?)\s*(.*)$")
POINT_RE = re.compile(r"^([一二三四五六七八九十百千]+、)\s*(.*)$")
ARABIC_POINT_RE = re.compile(r"^(\d+[\.、])\s*(.*)$")
META_PATTERNS = {
    "published_date": re.compile(r"(?:發布|公布)日期[：:]?\s*([^\n]+)"),
    "effective_date": re.compile(r"(?:生效|施行)日期[：:]?\s*([^\n]+)"),
    "amended_date": re.compile(r"(?:修正|異動)日期[：:]?\s*([^\n]+)"),
    "authority": re.compile(r"(?:發布機關|主管機關)[：:]?\s*([^\n]+)"),
}


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\u3000", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _choose_content(soup: BeautifulSoup):
    settings = get_settings()
    if settings.detail_content_selector:
        node = soup.select_one(settings.detail_content_selector)
        if node:
            return node
    for selector in ("main", "article", "#content", ".content", ".law-content", ".detail", "#ctl00_ContentPlaceHolder1"):
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) > 100:
            return node
    return soup.body or soup


def _extract_title(soup: BeautifulSoup, fallback_title: str) -> str:
    for selector in ("h1", "h2", ".title", ".law-title"):
        node = soup.select_one(selector)
        if node:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if 2 <= len(text) <= 500:
                return text
    if fallback_title:
        return fallback_title.strip()
    if soup.title:
        return soup.title.get_text(" ", strip=True)
    return "未命名法規"


def _extract_metadata(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, pattern in META_PATTERNS.items():
        match = pattern.search(text)
        if match:
            meta[key] = match.group(1).strip()[:200]
    return meta


def split_legal_text(text: str) -> list[ParsedChunk]:
    lines = _clean_lines(text)
    if not lines:
        return []

    has_articles = any(ARTICLE_RE.match(line) for line in lines)
    chunks: list[ParsedChunk] = []

    # Statutes/regulations: ignore title/metadata preamble and start at the first 第X條.
    if has_articles:
        current_label: str | None = None
        current: list[str] = []

        def flush_article():
            nonlocal current
            if current_label and current:
                chunks.append(ParsedChunk(len(chunks), current_label, None, "\n".join(current).strip()))
            current = []

        for line in lines:
            match = ARTICLE_RE.match(line)
            if match:
                flush_article()
                current_label = re.sub(r"\s+", "", match.group(1))
                rest = match.group(2).strip()
                current = [current_label if not rest else f"{current_label} {rest}"]
            elif current_label is not None:
                current.append(line)
        flush_article()
    else:
        # Administrative directions often use 一、二、... or 1./2. instead of 第X條.
        has_points = any((POINT_RE.match(line) or ARABIC_POINT_RE.match(line)) for line in lines)
        current_label: str | None = None
        current: list[str] = []

        def flush_point():
            nonlocal current
            if current and (current_label is not None or not has_points):
                chunks.append(ParsedChunk(len(chunks), current_label, None, "\n".join(current).strip()))
            current = []

        for line in lines:
            point = POINT_RE.match(line) or ARABIC_POINT_RE.match(line)
            if point:
                flush_point()
                current_label = point.group(1).strip()
                current = [line]
            elif current_label is not None or not has_points:
                current.append(line)
        flush_point()

    # Fallback: large unstructured pages are chunked by character windows while preserving lines.
    if len(chunks) == 1 and len(chunks[0].content) > 6000:
        full = chunks[0].content
        chunks = []
        window = 1800
        overlap = 180
        start = 0
        while start < len(full):
            end = min(len(full), start + window)
            chunks.append(ParsedChunk(len(chunks), None, None, full[start:end]))
            if end == len(full):
                break
            start = end - overlap
    return chunks


def parse_law_html(html: str, fallback_title: str = "") -> ParsedLaw:
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        bad.decompose()
    content = _choose_content(soup)
    text = "\n".join(_clean_lines(content.get_text("\n", strip=True)))
    title = _extract_title(soup, fallback_title)
    metadata = _extract_metadata(text)
    normalized_for_hash = re.sub(r"\s+", "", text)
    digest = sha256(normalized_for_hash.encode("utf-8")).hexdigest()
    chunks = split_legal_text(text)
    return ParsedLaw(title, text, metadata, digest, chunks)


def metadata_json(metadata: dict[str, str]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)
