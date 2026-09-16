import json
import re
from dataclasses import dataclass
from hashlib import sha256

from bs4 import BeautifulSoup

from app.config import get_settings

# Increment this when parsing or chunk identity changes in a way that requires
# regenerating stored chunks/embeddings. It is deliberately separate from legal
# source version_no: parser-only changes must not pretend that the law changed.
PARSER_REVISION = 3


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
    metadata: dict[str, object]
    content_hash: str
    chunks: list[ParsedChunk]


CN_NUM = "一二三四五六七八九十百千萬〇○零兩壹貳參肆伍陸柒捌玖拾佰仟"
ARTICLE_RE = re.compile(rf"^(第\s*[{CN_NUM}\d\-之]+\s*條(?:\s*之\s*[{CN_NUM}\d]+)?)\s*(.*)$")
ARTICLE_REFERENCE_TAIL_RE = re.compile(rf"^第\s*[{CN_NUM}\d]+\s*項")
CHAPTER_RE = re.compile(rf"^(第\s*[{CN_NUM}\d]+\s*章)\s*(.*)$")
SECTION_RE = re.compile(rf"^(第\s*[{CN_NUM}\d]+\s*節)\s*(.*)$")
POINT_RE = re.compile(rf"^([{CN_NUM}]+、)\s*(.*)$")
PAREN_POINT_RE = re.compile(rf"^([（(][{CN_NUM}]+[）)])\s*(.*)$")
ARABIC_POINT_RE = re.compile(r"^(\d+[\.、])\s*(.*)$")
LAW_NAME_LINE_RE = re.compile(r"法規名稱[：:]\s*([^\n]+)")
TRAILING_DATE_RE = re.compile(
    r"^(?P<title>.+?)\s*[（(](?P<date>\d{2,3}/\d{1,2}/\d{1,2})\s*(?P<verb>公發布|發布|公布|修正|訂定)[）)]\s*$"
)
META_PATTERNS = {
    "published_date": re.compile(r"(?:發布|公布)日期[：:]?\s*([^\n]+)"),
    "effective_date": re.compile(r"(?:生效|施行)日期[：:]?\s*([^\n]+)"),
    "amended_date": re.compile(r"(?:修正|異動)日期[：:]?\s*([^\n]+)"),
    "authority": re.compile(r"(?:發布機關|主管機關)[：:]?\s*([^\n]+)"),
    "law_status": re.compile(r"(?:法規狀態|現行狀態)[：:]?\s*([^\n]+)"),
}

# Dynamic chrome must not enter the legal text or content hash.  The print-view
# timestamp in particular would otherwise create a new version on every crawl.
NOISE_LINE_PATTERNS = [
    re.compile(r"^內政部消防署(?:法令|法規)查詢系統$"),
    re.compile(r"^消防法令查詢系統$"),
    re.compile(r"^列印時間[：:]?"),
    re.compile(r"^所有條文$"),
    re.compile(r"^回首頁$"),
    re.compile(r"^回上一頁$"),
    re.compile(r"^版權所有.*內政部消防署"),
    re.compile(r"^本網站為每月定期更新"),
    re.compile(r"^法規資料更新日期[：:]?"),
    re.compile(r"^如需查詢最新法規"),
    re.compile(r"^部分資料內容.*司法院網站"),
    re.compile(r"^建議最佳瀏覽環境"),
    re.compile(r"^最後更新日期"),
]

GENERIC_TITLES = {
    "消防法令查詢系統",
    "內政部消防署法令查詢系統",
    "法規查詢",
    "法令查詢",
    "所有條文",
}


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\u3000", " ").replace("\xa0", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        if any(pattern.search(line) for pattern in NOISE_LINE_PATTERNS):
            continue
        lines.append(line)
    return lines


def _choose_content(soup: BeautifulSoup):
    settings = get_settings()
    if settings.detail_content_selector:
        node = soup.select_one(settings.detail_content_selector)
        if node:
            return node
    for selector in (
        "main",
        "article",
        "#content",
        ".content",
        ".law-content",
        ".detail",
        "#ctl00_ContentPlaceHolder1",
        "#form1",
    ):
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) > 100:
            return node
    return soup.body or soup


def _parse_legacy_law_name(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (title, date, verb) from the legacy `法規名稱：...` line.

    Only a *trailing* parenthetical containing a ROC date + promulgation verb
    is treated as metadata, so legal names containing parentheses are kept.
    """
    match = LAW_NAME_LINE_RE.search(text)
    if not match:
        return None, None, None
    raw = re.sub(r"\s+", " ", match.group(1)).strip(" ：:")
    dated = TRAILING_DATE_RE.match(raw)
    if dated:
        return dated.group("title").strip(), dated.group("date"), dated.group("verb")
    return raw, None, None


def _title_from_legacy_text(text: str) -> str | None:
    title, _, _ = _parse_legacy_law_name(text)
    return title if title and len(title) >= 2 else None


def _extract_title(soup: BeautifulSoup, text: str, fallback_title: str) -> str:
    legacy = _title_from_legacy_text(text)
    if legacy:
        return legacy

    # The category anchor is normally more trustworthy than generic page chrome
    # such as an H1 saying only "消防法令查詢系統".
    fallback = re.sub(r"\s+", " ", fallback_title).strip() if fallback_title else ""
    for selector in ("h1", "h2", ".title", ".law-title"):
        node = soup.select_one(selector)
        if node:
            candidate = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if candidate not in GENERIC_TITLES and 2 <= len(candidate) <= 500:
                return candidate
    if fallback and fallback not in GENERIC_TITLES:
        return fallback
    if soup.title:
        candidate = soup.title.get_text(" ", strip=True)
        if candidate not in GENERIC_TITLES:
            return candidate
    return fallback or "未命名法規"


def _extract_metadata(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, pattern in META_PATTERNS.items():
        match = pattern.search(text)
        if match:
            meta[key] = match.group(1).strip()[:200]

    _, date, verb = _parse_legacy_law_name(text)
    if date and verb:
        if verb in {"公發布", "發布", "公布", "訂定"}:
            meta.setdefault("published_date", date)
        elif verb == "修正":
            meta.setdefault("amended_date", date)
    return meta


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", "", label)


def split_legal_text(text: str) -> list[ParsedChunk]:
    lines = _clean_lines(text)
    if not lines:
        return []

    has_articles = any(ARTICLE_RE.match(line) for line in lines)
    chunks: list[ParsedChunk] = []

    if has_articles:
        current_label: str | None = None
        current_heading: str | None = None
        pending_heading: str | None = None
        current: list[str] = []

        def flush_article():
            nonlocal current
            if current_label and current:
                chunks.append(
                    ParsedChunk(
                        len(chunks),
                        current_label,
                        current_heading,
                        "\n".join(current).strip(),
                    )
                )
            current = []

        for line in lines:
            chapter = CHAPTER_RE.match(line) or SECTION_RE.match(line)
            if chapter:
                label = _normalize_label(chapter.group(1))
                rest = chapter.group(2).strip()
                pending_heading = label if not rest else f"{label} {rest}"
                continue

            match = ARTICLE_RE.match(line)
            if match:
                # A wrapped paragraph can begin with a cross-reference such as
                # 「第六條第一項所定...」. It belongs to the current article and
                # must not be mistaken for a new 第六條 heading.
                rest = match.group(2).strip()
                if current_label is not None and ARTICLE_REFERENCE_TAIL_RE.match(rest):
                    current.append(line)
                    continue
                flush_article()
                current_label = _normalize_label(match.group(1))
                current_heading = pending_heading
                current = [current_label if not rest else f"{current_label} {rest}"]
            elif current_label is not None:
                current.append(line)
        flush_article()
    else:
        # Administrative directions commonly use 一、二、... or 1./2. rather
        # than 第X條. Formal numerals (壹、貳、...) are accepted as well.
        def admin_marker(line: str) -> tuple[re.Match[str], int] | None:
            for pattern, level in (
                (POINT_RE, 1),
                (PAREN_POINT_RE, 2),
                (ARABIC_POINT_RE, 3),
            ):
                match = pattern.match(line)
                if match:
                    return match, level
            return None

        marker_levels = [marker[1] for line in lines if (marker := admin_marker(line))]
        has_points = bool(marker_levels)
        has_hierarchy = len(set(marker_levels)) > 1
        current_label: str | None = None
        current_heading: str | None = None
        current: list[str] = []
        heading_path: dict[int, str] = {}

        def flush_point():
            nonlocal current
            if current and (current_label is not None or not has_points):
                chunks.append(
                    ParsedChunk(
                        len(chunks),
                        current_label,
                        current_heading,
                        "\n".join(current).strip(),
                    )
                )
            current = []

        for index, line in enumerate(lines):
            marker = admin_marker(line)
            if marker:
                point, level = marker
                flush_point()
                next_level = next(
                    (
                        next_marker[1]
                        for later in lines[index + 1 :]
                        if (next_marker := admin_marker(later))
                    ),
                    None,
                )
                is_heading = has_hierarchy and next_level is not None and next_level > level
                heading_path = {
                    key: value for key, value in heading_path.items() if key < level
                }
                if is_heading:
                    heading_path[level] = line
                    current_label = None
                    current_heading = None
                else:
                    current_label = point.group(1).strip()
                    parents = [heading_path[key] for key in sorted(heading_path) if key < level]
                    current_heading = " / ".join(parents) or None
                    current = [line]
            elif current_label is not None or not has_points:
                current.append(line)
        flush_point()

    # Last-resort character windows for an unstructured long document.
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


def _semantic_hash(
    title: str, metadata: dict[str, str], chunks: list[ParsedChunk], text: str
) -> str:
    stable_meta = {
        key: metadata[key]
        for key in ("published_date", "effective_date", "amended_date", "authority", "law_status")
        if key in metadata
    }
    if chunks:
        legal_body = "\n".join(
            f"{chunk.heading or ''}\n{chunk.article_label or ''}\n{chunk.content}"
            for chunk in chunks
        )
    else:
        legal_body = text
    payload = json.dumps(
        {"title": title, "metadata": stable_meta, "body": legal_body},
        ensure_ascii=False,
        sort_keys=True,
    )
    normalized = re.sub(r"\s+", "", payload)
    return sha256(normalized.encode("utf-8")).hexdigest()


def parse_law_html(html: str, fallback_title: str = "") -> ParsedLaw:
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        bad.decompose()
    content = _choose_content(soup)
    lines = _clean_lines(content.get_text("\n", strip=True))
    text = "\n".join(lines)
    title = _extract_title(soup, text, fallback_title)
    metadata = _extract_metadata(text)
    metadata["parser_revision"] = PARSER_REVISION
    chunks = split_legal_text(text)
    digest = _semantic_hash(title, metadata, chunks, text)
    return ParsedLaw(title, text, metadata, digest, chunks)


def metadata_json(metadata: dict[str, object]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def parse_stored_law_text(
    raw_text: str,
    title: str,
    metadata: dict[str, object] | None = None,
) -> ParsedLaw:
    """Reparse persisted source/attachment text without a network request.

    ``append_attachment_text`` stores attachments behind an ``附件：<label>``
    boundary. Replaying those boundaries preserves their independently searchable
    chunks while allowing parser-only improvements to be applied to current data.
    """
    parts = re.split(r"(?m)^附件：([^\r\n]+)\r?\n", raw_text.strip())
    body = parts[0].strip()
    parsed_metadata = dict(metadata or {})
    parsed_metadata["parser_revision"] = PARSER_REVISION
    chunks = split_legal_text(body)
    parsed = ParsedLaw(
        title=title,
        text=body,
        metadata=parsed_metadata,
        content_hash=_semantic_hash(title, parsed_metadata, chunks, body),
        chunks=chunks,
    )
    for index in range(1, len(parts), 2):
        label = parts[index].strip()
        attachment_text = parts[index + 1].strip()
        append_attachment_text(parsed, attachment_text, label)
    return parsed


def append_attachment_text(parsed: ParsedLaw, text: str, label: str) -> None:
    """Add extracted attachment text as searchable chunks and update the hash."""
    text = text.strip()
    if not text:
        return
    chunks = split_legal_text(text)
    if not chunks:
        chunks = [ParsedChunk(0, None, None, text)]
    start = len(parsed.chunks)
    for offset, chunk in enumerate(chunks):
        chunk.seq = start + offset
        chunk.heading = f"附件：{label}"
        if not chunk.article_label:
            chunk.article_label = f"附件{offset + 1}"
    parsed.chunks.extend(chunks)
    parsed.text = f"{parsed.text}\n\n附件：{label}\n{text}".strip()
    parsed.content_hash = _semantic_hash(parsed.title, parsed.metadata, parsed.chunks, parsed.text)
