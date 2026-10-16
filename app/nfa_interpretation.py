"""Import one explicitly supplied NFA interpretation page into the local index."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import get_settings


class InterpretationImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class Interpretation:
    eid: str
    number: str
    title: str
    text: str
    sections: tuple[tuple[str, str], ...]
    metadata: dict[str, str]


def validate_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise InterpretationImportError("Invalid NFA URL port") from exc
    if (
        parts.scheme != "https"
        or parts.hostname != "law.nfa.gov.tw"
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or parts.path.lower() != "/gnfa/fint/fintqry04.aspx"
    ):
        raise InterpretationImportError("Only a direct HTTPS NFA FINTQRY04 page is accepted")
    values = parse_qs(parts.query, keep_blank_values=True)
    eids = values.get("EID", [])
    if len(eids) != 1:
        raise InterpretationImportError("URL must contain exactly one EID")
    eid = unquote(eids[0])
    fields = eid.split(",")
    if len(fields) != 4 or not re.fullmatch(r"[A-Z]\d{5}", fields[0]):
        raise InterpretationImportError("Unexpected NFA interpretation EID")
    if not re.fullmatch(r"\d{6,12}", fields[2]) or not re.fullmatch(r"\d{8}", fields[3]):
        raise InterpretationImportError("Unexpected NFA interpretation number/date")
    if not fields[1] or len(fields[1]) > 30:
        raise InterpretationImportError("Unexpected NFA interpretation issuing code")
    return eid, fields[2]


def fetch_one_page(url: str) -> tuple[str, str]:
    """One GET, no redirects, retry, pagination, attachment, or challenge handling."""
    settings = get_settings()
    with httpx.Client(
        timeout=settings.http_timeout_seconds,
        follow_redirects=False,
        verify=ssl.create_default_context(),
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    ) as client:
        try:
            with client.stream("GET", url) as response:
                if response.status_code in (403, 429):
                    raise InterpretationImportError(
                        f"NFA returned HTTP {response.status_code}; stop and do not retry"
                    )
                if response.is_redirect:
                    raise InterpretationImportError("NFA redirected the page; no redirect was followed")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    raise InterpretationImportError(f"Expected HTML, received {content_type!r}")
                max_bytes = 1_000_000
                payload = bytearray()
                for block in response.iter_bytes():
                    payload.extend(block)
                    if len(payload) > max_bytes:
                        raise InterpretationImportError("Page exceeds the one-page size limit")
                encoding = response.encoding or "utf-8"
                return bytes(payload).decode(encoding, errors="replace"), str(response.url)
        except httpx.HTTPError as exc:
            raise InterpretationImportError(f"NFA page fetch failed: {type(exc).__name__}") from exc


_SECTION_LABELS = ("要旨", "主旨", "說明", "內容", "函釋內容", "相關法條")
_META_LABELS = ("發文機關", "發文字號", "發文日期", "發布日期", "函釋日期")


def parse_interpretation(html: str, eid: str, number: str) -> Interpretation:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    sections: list[tuple[str, str]] = []
    metadata: dict[str, str] = {"source_type": "nfa_interpretation", "eid": eid, "number": number}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).strip("：: ")
        value = "\n".join(cells[1].stripped_strings).strip()
        if not value:
            continue
        if label in _SECTION_LABELS:
            sections.append((label, value))
        elif label in _META_LABELS:
            metadata[label] = value
    if not sections:
        # Some NFA templates use label/value lines rather than table rows.
        lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
        for index, line in enumerate(lines):
            label = line.strip("：: ")
            if label in _SECTION_LABELS and index + 1 < len(lines):
                end = next(
                    (j for j in range(index + 1, len(lines)) if lines[j].strip("：: ") in _SECTION_LABELS),
                    len(lines),
                )
                sections.append((label, "\n".join(lines[index + 1 : end])))
    body = "\n\n".join(f"{label}：{value}" for label, value in sections)
    compact = re.sub(r"\s+", "", soup.get_text(" "))
    if number not in compact:
        raise InterpretationImportError("The page does not show the requested interpretation number")
    if len(body) < 80:
        raise InterpretationImportError("Interpretation body is missing or too short; no index write")
    if not any(label in {"要旨", "主旨", "說明", "內容", "函釋內容"} for label, _ in sections):
        raise InterpretationImportError("No interpretation body section was recognized")
    title = f"消防署函釋（{number}）"
    return Interpretation(eid, number, title, body, tuple(sections), metadata)


def _chunks(document: Interpretation) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    provenance = "\n".join(
        f"{label}：{document.metadata[label]}"
        for label in _META_LABELS
        if label in document.metadata
    )
    for label, value in document.sections:
        body = f"{label}：{value}"
        if len(body) <= 2600:
            chunks.append((label, f"{provenance}\n{body}" if provenance else body))
        else:
            for offset in range(0, len(body), 2500):
                part = body[offset : offset + 2600]
                chunks.append((
                    f"{label} {offset // 2500 + 1}",
                    f"{provenance}\n{part}" if provenance else part,
                ))
    return chunks


def import_interpretation(url: str, *, html: str | None = None, apply: bool = True) -> dict:
    """Validate, parse, and version one supplied page; no other URL is fetched."""
    eid, number = validate_url(url)
    if get_settings().storage_backend.lower() != "sqlite":
        raise InterpretationImportError("Single-page interpretation import supports SQLite only")
    retrieved_url = url
    if html is None:
        html, retrieved_url = fetch_one_page(url)
    document = parse_interpretation(html, eid, number)
    chunks = _chunks(document)
    stable_payload = json.dumps(
        {"text": document.text, "metadata": document.metadata},
        ensure_ascii=False, sort_keys=True,
    )
    content_hash = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()
    result = {
        "status": "preview" if not apply else "pending",
        "source_key": f"nfa-fint:{eid}",
        "title": document.title,
        "number": number,
        "source_url": url,
        "retrieved_url": retrieved_url,
        "content_hash": content_hash,
        "chunks": len(chunks),
    }
    if not apply:
        return result

    from app.db import embedding_to_storage, init_db, rebuild_fts, session_scope
    from app.embedding import get_embedder
    from app.models import Law, LawChunk, LawVersion

    init_db()
    with session_scope() as db:
        law = db.scalar(select(Law).where(Law.source_key == result["source_key"]))
        current = (
            db.scalar(select(LawVersion).where(LawVersion.law_id == law.id, LawVersion.is_current.is_(True)))
            if law else None
        )
        if current and current.content_hash == content_hash:
            return {**result, "status": "unchanged", "law_id": law.id, "version": current.version_no}

    vectors = get_embedder().embed([f"{document.title} {text}" for _, text in chunks])
    dimension = get_settings().embedding_dim
    if len(vectors) != len(chunks) or any(len(vector) != dimension for vector in vectors):
        raise InterpretationImportError("Embedding count/dimension mismatch; no index write")
    with session_scope() as db:
        law = db.scalar(select(Law).where(Law.source_key == result["source_key"]))
        if law is None:
            law = Law(
                source_key=result["source_key"], title=document.title,
                category="消防署函釋", source_url=url,
            )
            db.add(law)
            db.flush()
        else:
            law.title = document.title
            law.source_url = url
        versions = db.scalars(select(LawVersion).where(LawVersion.law_id == law.id)).all()
        current = next((version for version in versions if version.is_current), None)
        if current and current.content_hash == content_hash:
            return {**result, "status": "unchanged", "law_id": law.id, "version": current.version_no}
        for version in versions:
            version.is_current = False
        metadata = {**document.metadata, "retrieved_url": retrieved_url, "original_source_url": url}
        version = LawVersion(
            law_id=law.id, version_no=max((v.version_no for v in versions), default=0) + 1,
            content_hash=content_hash, raw_text=document.text,
            metadata_json=json.dumps(metadata, ensure_ascii=False), is_current=True,
        )
        db.add(version)
        db.flush()
        for seq, ((label, text), vector) in enumerate(zip(chunks, vectors, strict=True), 1):
            db.add(LawChunk(
                version_id=version.id, seq=seq, article_label=label,
                heading=document.title, content=text, embedding=embedding_to_storage(vector),
            ))
        db.flush()
        rebuild_fts(db)
        return {**result, "status": "inserted", "law_id": law.id, "version": version.version_no}
