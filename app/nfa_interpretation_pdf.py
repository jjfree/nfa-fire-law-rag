"""Import one user-supplied NFA interpretation PDF without contacting the site."""

from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from pypdf import PdfReader
from sqlalchemy import select

from app.config import get_settings
from app.nfa_interpretation import InterpretationImportError, validate_url

_PDF_NAME_RE = re.compile(r"^[0-9a-f]{64}\.pdf$")
_PAGE_LABEL_RE = re.compile(r"^第(\d+)頁(?:\s+\d+)?$")


def pdf_public_url(metadata_json: str | None, article_label: str | None) -> str | None:
    """Return only a path to an indexed, content-addressed local PDF page."""
    if not metadata_json or not article_label:
        return None
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    name = metadata.get("local_pdf_name")
    page = _PAGE_LABEL_RE.fullmatch(article_label)
    if not isinstance(name, str) or not _PDF_NAME_RE.fullmatch(name) or not page:
        return None
    try:
        page_count = int(metadata.get("pdf_page_count", 0))
    except (TypeError, ValueError):
        return None
    page_number = int(page.group(1))
    if not 1 <= page_number <= page_count:
        return None
    return f"/app/static/local-pdfs/{name}#page={page_number}"


def _clean_page_text(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            continue
        if line.startswith(("列印時間：", "https://law.nfa.gov.tw/GNFA/FINT/")):
            continue
        if "law.nfa.gov.tw/GNFA/FINT/PrintFINTQRY04.aspx" in line:
            continue
        if re.fullmatch(r"\d+/\d+", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_pages(pdf_bytes: bytes, number: str, eid: str) -> tuple[list[str], dict[str, str]]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = reader.pages
        if not 1 <= len(pages) <= get_settings().max_attachment_pages:
            raise InterpretationImportError("PDF page count is outside the configured limit")
        page_texts = [_clean_page_text(page.extract_text() or "") for page in pages]
        title = str((reader.metadata or {}).get("/Title") or "")
    except InterpretationImportError:
        raise
    except Exception as exc:
        raise InterpretationImportError(f"Cannot read PDF: {type(exc).__name__}") from exc

    full_text = "\n".join(page_texts)
    compact = re.sub(r"\s+", "", full_text)
    if number not in compact or "內政部消防署" not in compact:
        raise InterpretationImportError("PDF does not show the requested NFA document number and issuer")
    if len(full_text) < 100 or not any(marker in compact for marker in ("主旨", "說明", "要旨")):
        raise InterpretationImportError("PDF interpretation text is missing or too short")
    date_token = eid.split(",")[3]
    roc_year = int(date_token[:4]) - 1911
    month, day = int(date_token[4:6]), int(date_token[6:8])
    date_pattern = rf"{roc_year}(?:/|年)0?{month}(?:/|月)0?{day}(?:日)?"
    if not re.search(date_pattern, compact):
        raise InterpretationImportError("PDF does not show the date encoded in the official EID")

    metadata = {"發文日期": f"{roc_year:03d}/{month:02d}/{day:02d}", "發文機關": "內政部消防署"}
    if title:
        print_url = title if title.startswith("https://") else f"https://{title}"
        parts = urlsplit(print_url)
        if parts.hostname == "law.nfa.gov.tw" and parts.path.lower() == "/gnfa/fint/printfintqry04.aspx":
            metadata["print_source_url"] = print_url
    return page_texts, metadata


def _page_chunks(page_texts: list[str], number: str, date: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for page_no, page_text in enumerate(page_texts, 1):
        if not page_text.strip():
            continue
        prefix = f"消防署函釋（{number}）\n發文日期：{date}\n第{page_no}頁\n"
        if len(page_text) <= 2600:
            chunks.append((f"第{page_no}頁", prefix + page_text))
        else:
            for offset in range(0, len(page_text), 2500):
                chunks.append((
                    f"第{page_no}頁 {offset // 2500 + 1}",
                    prefix + page_text[offset : offset + 2600],
                ))
    return chunks


def _verified_copy(target: Path, content: bytes, digest: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise InterpretationImportError(f"Existing local PDF has a different hash: {target}")
        return
    temporary = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _same_pdf_version(version, content_hash: str, pdf_hash: str) -> bool:
    if version is None or version.content_hash != content_hash:
        return False
    try:
        metadata = json.loads(version.metadata_json or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(metadata, dict) and metadata.get("pdf_sha256") == pdf_hash


def import_interpretation_pdf(
    pdf_path: Path,
    source_url: str,
    *,
    apply: bool = True,
    storage_dir: Path | None = None,
    public_dir: Path | None = None,
) -> dict:
    """Index exactly one local official PDF and retain a browser-readable copy."""
    eid, number = validate_url(source_url)
    settings = get_settings()
    if settings.storage_backend.lower() != "sqlite":
        raise InterpretationImportError("Single-page PDF import supports SQLite only")
    source_path = pdf_path.resolve(strict=True)
    if source_path.suffix.lower() != ".pdf" or source_path.stat().st_size > settings.max_attachment_bytes:
        raise InterpretationImportError("Expected a PDF within the configured attachment size limit")
    pdf_bytes = source_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise InterpretationImportError("File is not a PDF")
    page_texts, extracted_metadata = _extract_pages(pdf_bytes, number, eid)
    chunks = _page_chunks(page_texts, number, extracted_metadata["發文日期"])
    if not chunks:
        raise InterpretationImportError("PDF has no searchable text; OCR is required before import")
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    content_hash = hashlib.sha256(
        json.dumps(page_texts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    result = {
        "status": "preview" if not apply else "pending",
        "source_key": f"nfa-fint:{eid}",
        "title": f"消防署函釋（{number}）",
        "number": number,
        "source_url": source_url,
        "pdf_sha256": pdf_hash,
        "content_hash": content_hash,
        "pages": len(page_texts),
        "chunks": len(chunks),
    }
    if not apply:
        return result

    from app.db import embedding_to_storage, init_db, rebuild_fts, session_scope
    from app.embedding import get_embedder
    from app.models import Law, LawChunk, LawVersion

    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    storage_root = storage_dir or database_path.parent / "source_pdfs"
    public_root = public_dir or Path(__file__).resolve().parent / "static" / "local-pdfs"
    filename = f"{pdf_hash}.pdf"
    _verified_copy(storage_root / filename, pdf_bytes, pdf_hash)
    _verified_copy(public_root / filename, pdf_bytes, pdf_hash)
    metadata = {
        "source_type": "nfa_interpretation", "source_format": "user_supplied_pdf",
        "eid": eid, "number": number, "original_source_url": source_url,
        "local_pdf_name": filename, "pdf_sha256": pdf_hash,
        "pdf_page_count": len(page_texts), "pdf_storage_path": str(storage_root / filename),
        **extracted_metadata,
    }
    init_db()
    with session_scope() as db:
        law = db.scalar(select(Law).where(Law.source_key == result["source_key"]))
        current = (
            db.scalar(select(LawVersion).where(LawVersion.law_id == law.id, LawVersion.is_current.is_(True)))
            if law else None
        )
        if _same_pdf_version(current, content_hash, pdf_hash):
            return {
                **result, "status": "unchanged", "law_id": law.id,
                "version": current.version_no,
                "local_pdf_url": pdf_public_url(current.metadata_json, chunks[0][0]),
            }

    vectors = get_embedder().embed([f"{result['title']} {text}" for _, text in chunks])
    if len(vectors) != len(chunks) or any(len(vector) != settings.embedding_dim for vector in vectors):
        raise InterpretationImportError("Embedding count/dimension mismatch; no index write")

    with session_scope() as db:
        law = db.scalar(select(Law).where(Law.source_key == result["source_key"]))
        if law is None:
            law = Law(
                source_key=result["source_key"], title=result["title"],
                category="消防署函釋", source_url=source_url,
            )
            db.add(law)
            db.flush()
        versions = db.scalars(select(LawVersion).where(LawVersion.law_id == law.id)).all()
        current = next((version for version in versions if version.is_current), None)
        if _same_pdf_version(current, content_hash, pdf_hash):
            return {
                **result, "status": "unchanged", "law_id": law.id,
                "version": current.version_no,
                "local_pdf_url": pdf_public_url(current.metadata_json, chunks[0][0]),
            }
        for version in versions:
            version.is_current = False
        version = LawVersion(
            law_id=law.id, version_no=max((v.version_no for v in versions), default=0) + 1,
            content_hash=content_hash,
            raw_text="\n\n".join(f"第{i}頁\n{text}" for i, text in enumerate(page_texts, 1)),
            metadata_json=json.dumps(metadata, ensure_ascii=False), is_current=True,
        )
        db.add(version)
        db.flush()
        for seq, ((label, text), vector) in enumerate(zip(chunks, vectors, strict=True), 1):
            db.add(LawChunk(
                version_id=version.id, seq=seq, article_label=label,
                heading=result["title"], content=text, embedding=embedding_to_storage(vector),
            ))
        db.flush()
        rebuild_fts(db)
        return {
            **result, "status": "inserted", "law_id": law.id, "version": version.version_no,
            "local_pdf_url": pdf_public_url(version.metadata_json, chunks[0][0]),
        }
