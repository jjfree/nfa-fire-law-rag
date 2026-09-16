import json
from dataclasses import asdict
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.attachments import (
    PdfTooManyPagesError,
    discover_attachment_urls,
    extract_pdf_text,
)
from app.config import get_settings
from app.crawler.discovery import DiscoveredLawLink, discover_law_links
from app.crawler.fetch import (
    AttachmentTooLargeError,
    CrawlBlockedError,
    FetchedPage,
    HttpFetcher,
)
from app.crawler.nfa_urls import build_print_url, extract_lsid
from app.parser import (
    PARSER_REVISION,
    append_attachment_text,
    metadata_json,
    parse_law_html,
    parse_stored_law_text,
)


class IngestError(RuntimeError):
    pass


def _load_metadata(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parser_revision(metadata: dict[str, object]) -> int | None:
    value = metadata.get("parser_revision")
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _current_parser_revision(metadata: dict[str, object]) -> bool:
    return _parser_revision(metadata) == PARSER_REVISION


def _embedding_inputs(title: str, chunks) -> list[str]:
    return [
        f"{title}\n{chunk.heading or ''}\n{chunk.article_label or ''}\n{chunk.content}"
        for chunk in chunks
    ]


def _validate_source(url: str) -> None:
    settings = get_settings()
    host = urlparse(url).hostname or ""
    if settings.nfa_allowed_host and host.lower() != settings.nfa_allowed_host.lower():
        raise IngestError(f"Refusing source outside allowed host: {host}")


def _fetch_law_page(link: DiscoveredLawLink, fetcher: HttpFetcher) -> tuple[FetchedPage, list[str]]:
    """Fetch a law detail page, preferring NFA's stable print view when possible.

    Returns the page plus a list of failed candidate URLs for observability.
    """
    settings = get_settings()
    print_url = build_print_url(link.url)
    candidates: list[str] = []
    if settings.nfa_prefer_print_view and print_url and print_url != link.url:
        candidates.append(print_url)
    candidates.append(link.url)
    if not settings.nfa_prefer_print_view and print_url and print_url != link.url:
        candidates.append(print_url)

    failed: list[str] = []
    last_exc: Exception | None = None
    for url in dict.fromkeys(candidates):
        _validate_source(url)
        try:
            page = fetcher.fetch(url)
            _validate_source(page.url)
            return page, failed
        except CrawlBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next representation
            failed.append(url)
            last_exc = exc
    if last_exc:
        raise last_exc
    raise IngestError(f"No fetch candidate for {link.url}")


def parse_link_without_db(link: DiscoveredLawLink, fetcher: HttpFetcher) -> dict:
    """Fetch and parse one law without DB/embedding; used by the Phase-2 probe."""
    page, failed_urls = _fetch_law_page(link, fetcher)
    parsed = parse_law_html(page.text, link.title)
    attachment_urls = discover_attachment_urls(page.text, page.url, get_settings().nfa_allowed_host)
    return {
        "title": parsed.title,
        "source_key": link.source_key,
        "source_url": link.url,
        "retrieved_url": page.url,
        "lsid": extract_lsid(link.url),
        "text_chars": len(parsed.text),
        "chunks": len(parsed.chunks),
        "first_article": parsed.chunks[0].article_label if parsed.chunks else None,
        "last_article": parsed.chunks[-1].article_label if parsed.chunks else None,
        "metadata": parsed.metadata,
        "content_hash": parsed.content_hash,
        "fallback_failures": failed_urls,
        "attachment_urls": attachment_urls,
    }


def _ingest_attachments(
    parsed, page: FetchedPage, link: DiscoveredLawLink, fetcher: HttpFetcher
) -> dict:
    """Download same-host PDFs, including one intermediate attachment-list page."""
    settings = get_settings()
    attachment_page = page
    if page.url != link.url:
        try:
            attachment_page = fetcher.fetch(link.url)
        except CrawlBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - record attachment failure and continue
            return {"discovered": 0, "parsed": 0, "errors": [f"detail-page: {exc}"]}

    urls = discover_attachment_urls(
        attachment_page.text, attachment_page.url, settings.nfa_allowed_host
    )
    report = {"discovered": len(urls), "parsed": 0, "skipped": [], "errors": []}
    seen_urls: set[str] = set()

    def process_url(url: str, depth: int = 0) -> None:
        if url in seen_urls:
            return
        seen_urls.add(url)
        try:
            content_type, content = fetcher.fetch_bytes(url)
            is_pdf = (
                "pdf" in content_type.lower()
                or urlparse(url).path.lower().endswith(".pdf")
                or content.startswith(b"%PDF-")
            )
            if not is_pdf:
                # NFA attachment indicators point first to lawfile_list.aspx;
                # that page then exposes GetFile.ashx PDF links. Expand only
                # one same-host HTML hop so arbitrary pages cannot become a
                # crawl graph.
                if depth == 0 and "html" in content_type.lower():
                    nested_urls = discover_attachment_urls(
                        content.decode("utf-8", errors="replace"), url, settings.nfa_allowed_host
                    )
                    nested_urls = [nested for nested in nested_urls if nested not in seen_urls]
                    if nested_urls:
                        report["discovered"] += len(nested_urls)
                        for nested_url in nested_urls:
                            process_url(nested_url, depth + 1)
                        return
                reason = "unsupported content (not detected as PDF)"
                report["skipped"].append({"url": url, "reason": reason})
                report["errors"].append(f"{reason}: {url}")
                return
            text = extract_pdf_text(content, max_pages=settings.max_attachment_pages)
            if len(text) < 20:
                reason = "PDF has no searchable text"
                report["skipped"].append({"url": url, "reason": reason})
                report["errors"].append(f"{reason}: {url}")
                return
            label = PurePosixPath(urlparse(url).path).name or url
            append_attachment_text(parsed, text, label)
            report["parsed"] += 1
        except (AttachmentTooLargeError, PdfTooManyPagesError) as exc:
            reason = str(exc)
            report["skipped"].append({"url": url, "reason": reason})
            report["errors"].append(f"{reason}: {url}")
        except CrawlBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad attachment must not stop the law
            report["errors"].append(f"{url}: {type(exc).__name__}: {exc}")

    for url in urls:
        process_url(url)
    return report


def ingest_link(
    link: DiscoveredLawLink,
    fetcher: HttpFetcher | None = None,
    category_url: str | None = None,
) -> dict:
    # Keep DB/vector dependencies lazy so `nfa-law probe` can run on a fresh
    # machine before PostgreSQL drivers are installed/configured.
    from sqlalchemy import select

    from app.db import embedding_to_storage, rebuild_fts, session_scope
    from app.embedding import get_embedder
    from app.models import Law, LawChunk, LawVersion

    _validate_source(link.url)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher()
    try:
        page, failed_urls = _fetch_law_page(link, fetcher)
        parsed = parse_law_html(page.text, link.title)
        if len(parsed.text) < 20:
            raise IngestError(f"Parsed content too short: {link.url}")
        if not parsed.chunks:
            raise IngestError(f"No legal chunks detected: {link.url}")

        parsed.metadata.setdefault("retrieved_url", page.url)
        if category_url:
            parsed.metadata.setdefault("category_url", category_url)
        lsid = extract_lsid(link.url)
        if lsid:
            parsed.metadata.setdefault("lsid", lsid)

        # Avoid re-downloading and re-parsing unchanged attachments on a
        # resumed crawl. The stored raw text starts with the current detail
        # page text when the law body is unchanged.
        with session_scope() as db:
            cached_law = db.scalar(select(Law).where(Law.source_key == link.source_key))
            cached_current = None
            if cached_law is not None:
                cached_current = db.scalar(
                    select(LawVersion).where(
                        LawVersion.law_id == cached_law.id,
                        LawVersion.is_current.is_(True),
                    )
                )
            cached_metadata = _load_metadata(
                cached_current.metadata_json if cached_current is not None else None
            )
            cached_attachments = cached_metadata and cached_metadata.get("attachments")
            if (
                cached_current is not None
                and cached_attachments is not None
                and (
                    cached_current.raw_text == parsed.text
                    or cached_current.raw_text.startswith(parsed.text + "\n\n附件：")
                )
            ):
                if not _current_parser_revision(cached_metadata):
                    return {
                        "status": "reprocess_required",
                        "law_id": cached_law.id,
                        "title": cached_law.title,
                        "version": cached_current.version_no,
                        "stored_parser_revision": _parser_revision(cached_metadata),
                        "required_parser_revision": PARSER_REVISION,
                        "retrieved_url": page.url,
                        "fallback_failures": failed_urls,
                    }
                cached_metadata = dict(cached_metadata)
                cached_attachments = dict(cached_attachments)
                cached_attachments.setdefault("skipped", [])
                if not cached_attachments["skipped"]:
                    for error in cached_attachments.get("errors", []):
                        marker = error.find("http")
                        if marker >= 0:
                            cached_attachments["skipped"].append(
                                {"url": error[marker:], "reason": error[:marker].rstrip(": ")}
                            )
                cached_metadata["attachments"] = cached_attachments
                parsed.metadata["attachments"] = cached_attachments
                return {
                    "status": "unchanged",
                    "law_id": cached_law.id,
                    "title": cached_law.title,
                    "version": cached_current.version_no,
                    "metadata": cached_metadata,
                    "retrieved_url": page.url,
                    "fallback_failures": failed_urls,
                }

        attachment_report = _ingest_attachments(parsed, page, link, fetcher)
        parsed.metadata["attachments"] = attachment_report

        embedder = get_embedder()
        vectors = embedder.embed(_embedding_inputs(parsed.title, parsed.chunks))

        with session_scope() as db:
            law = db.scalar(select(Law).where(Law.source_key == link.source_key))
            if law is None:
                law = Law(source_key=link.source_key, title=parsed.title, source_url=link.url)
                db.add(law)
                db.flush()
            else:
                law.title = parsed.title
                # Preserve the human-facing law URL rather than replacing it with print view.
                law.source_url = link.url

            existing_current = db.scalar(
                select(LawVersion).where(
                    LawVersion.law_id == law.id,
                    LawVersion.content_hash == parsed.content_hash,
                    LawVersion.is_current.is_(True),
                )
            )
            if existing_current:
                existing_metadata = _load_metadata(existing_current.metadata_json)
                if not _current_parser_revision(existing_metadata):
                    return {
                        "status": "reprocess_required",
                        "law_id": law.id,
                        "title": law.title,
                        "version": existing_current.version_no,
                        "stored_parser_revision": _parser_revision(existing_metadata),
                        "required_parser_revision": PARSER_REVISION,
                        "retrieved_url": page.url,
                        "fallback_failures": failed_urls,
                    }
                return {
                    "status": "unchanged",
                    "law_id": law.id,
                    "title": law.title,
                    "version": existing_current.version_no,
                    "metadata": parsed.metadata,
                    "retrieved_url": page.url,
                    "fallback_failures": failed_urls,
                }

            current_versions = db.scalars(
                select(LawVersion).where(
                    LawVersion.law_id == law.id,
                    LawVersion.is_current.is_(True),
                )
            ).all()
            max_version = db.scalars(
                select(LawVersion.version_no).where(LawVersion.law_id == law.id)
            ).all()
            for old in current_versions:
                old.is_current = False

            version = LawVersion(
                law_id=law.id,
                version_no=(max(max_version) if max_version else 0) + 1,
                content_hash=parsed.content_hash,
                raw_text=parsed.text,
                metadata_json=metadata_json(parsed.metadata),
                is_current=True,
            )
            db.add(version)
            db.flush()
            for chunk, vector in zip(parsed.chunks, vectors, strict=True):
                db.add(
                    LawChunk(
                        version_id=version.id,
                        seq=chunk.seq,
                        article_label=chunk.article_label,
                        heading=chunk.heading,
                        content=chunk.content,
                        embedding=embedding_to_storage(vector),
                    )
                )
            rebuild_fts(db)
            return {
                "status": "inserted",
                "law_id": law.id,
                "title": law.title,
                "version": version.version_no,
                "chunks": len(parsed.chunks),
                "metadata": parsed.metadata,
                "retrieved_url": page.url,
                "fallback_failures": failed_urls,
            }
    finally:
        if own_fetcher:
            fetcher.close()


def _discover_category(
    category_url: str, fetcher: HttpFetcher
) -> tuple[FetchedPage, list[DiscoveredLawLink]]:
    _validate_source(category_url)
    category = fetcher.fetch(category_url)
    _validate_source(category.url)
    links = discover_law_links(category.text, category.url)
    return category, links


def _crawl_one_category(
    category_url: str, fetcher: HttpFetcher, max_laws: int | None = None
) -> dict:
    category, all_links = _discover_category(category_url, fetcher)
    links = all_links[:max_laws] if max_laws is not None else all_links
    results = []
    for link in links:
        try:
            results.append(
                {
                    "link": asdict(link),
                    "result": ingest_link(link, fetcher, category_url=category.url),
                }
            )
        except CrawlBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - report one-law failures and continue
            results.append({"link": asdict(link), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "category_url": category.url,
        "discovered_total": len(all_links),
        "selected": len(links),
        "inserted": sum(1 for r in results if r.get("result", {}).get("status") == "inserted"),
        "unchanged": sum(
            1 for r in results if r.get("result", {}).get("status") == "unchanged"
        ),
        "reprocess_required": sum(
            1
            for r in results
            if r.get("result", {}).get("status") == "reprocess_required"
        ),
        "errors": sum(1 for r in results if "error" in r),
        "results": results,
    }


def probe_category(category_url: str | None = None, max_laws: int = 3) -> dict:
    """Network/parser smoke test that does not require PostgreSQL or embeddings."""
    settings = get_settings()
    category_url = category_url or settings.nfa_category_url
    with HttpFetcher() as fetcher:
        category, all_links = _discover_category(category_url, fetcher)
        selected = all_links[:max_laws]
        results = []
        for link in selected:
            try:
                results.append(
                    {"link": asdict(link), "parse": parse_link_without_db(link, fetcher)}
                )
            except Exception as exc:  # noqa: BLE001 - report one-law probe failures
                results.append({"link": asdict(link), "error": f"{type(exc).__name__}: {exc}"})
        return {
            "category_url": category.url,
            "discovered_total": len(all_links),
            "selected": len(selected),
            "parsed": sum(1 for r in results if "parse" in r),
            "errors": sum(1 for r in results if "error" in r),
            "results": results,
        }


def crawl_category(category_url: str | None = None, max_laws: int | None = None) -> dict:
    settings = get_settings()
    category_url = category_url or settings.nfa_category_url
    with HttpFetcher() as fetcher:
        return _crawl_one_category(category_url, fetcher, max_laws=max_laws)


def crawl_categories(category_urls: list[str], max_laws: int | None = None) -> dict:
    """Incrementally ingest several category pages with one bounded fetcher."""
    if not category_urls:
        raise ValueError("At least one category URL is required")
    with HttpFetcher() as fetcher:
        categories = [
            _crawl_one_category(category_url, fetcher, max_laws=max_laws)
            for category_url in category_urls
        ]
    return {
        "category_urls": [item["category_url"] for item in categories],
        "categories": categories,
        "discovered_total": sum(item["discovered_total"] for item in categories),
        "selected": sum(item["selected"] for item in categories),
        "inserted": sum(item["inserted"] for item in categories),
        "unchanged": sum(item["unchanged"] for item in categories),
        "reprocess_required": sum(item["reprocess_required"] for item in categories),
        "errors": sum(item["errors"] for item in categories),
    }


def reprocess_current_laws(*, apply: bool = False, law_ids: list[int] | None = None) -> dict:
    """Rebuild current derived chunks from stored raw text, without crawling.

    Dry-run is the default. Applying keeps legal ``version_no`` and history intact,
    replacing only each selected current version's parser-derived chunks, embeddings,
    metadata/hash, and current-only FTS entries in one database transaction.
    """
    from sqlalchemy import select

    from app.db import embedding_to_storage, rebuild_fts, session_scope
    from app.embedding import get_embedder
    from app.models import Law, LawChunk, LawVersion

    requested_ids = set(law_ids or [])
    report_items: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    with session_scope() as db:
        statement = (
            select(LawVersion, Law)
            .join(Law, Law.id == LawVersion.law_id)
            .where(LawVersion.is_current.is_(True))
            .order_by(Law.id)
        )
        rows = db.execute(statement).all()
        embedder = None
        for version, law in rows:
            if requested_ids and law.id not in requested_ids:
                continue
            old_metadata = _load_metadata(version.metadata_json)
            old_revision = _parser_revision(old_metadata)
            if old_revision is not None and old_revision >= PARSER_REVISION:
                continue

            parsed = parse_stored_law_text(version.raw_text, law.title, old_metadata)
            if not parsed.chunks:
                errors.append(
                    {
                        "law_id": law.id,
                        "title": law.title,
                        "version": version.version_no,
                        "error": "No legal chunks detected in stored raw text",
                    }
                )
                continue
            item: dict[str, object] = {
                "law_id": law.id,
                "title": law.title,
                "version": version.version_no,
                "stored_parser_revision": old_revision,
                "required_parser_revision": PARSER_REVISION,
                "old_chunks": len(version.chunks),
                "new_chunks": len(parsed.chunks),
                "hash_changed": version.content_hash != parsed.content_hash,
            }
            report_items.append(item)
            if not apply:
                continue

            if embedder is None:
                embedder = get_embedder()
            vectors = embedder.embed(_embedding_inputs(law.title, parsed.chunks))
            for old_chunk in list(version.chunks):
                db.delete(old_chunk)
            db.flush()
            for chunk, vector in zip(parsed.chunks, vectors, strict=True):
                db.add(
                    LawChunk(
                        version_id=version.id,
                        seq=chunk.seq,
                        article_label=chunk.article_label,
                        heading=chunk.heading,
                        content=chunk.content,
                        embedding=embedding_to_storage(vector),
                    )
                )
            version.content_hash = parsed.content_hash
            version.metadata_json = metadata_json(parsed.metadata)

        if apply and report_items:
            db.flush()
            rebuild_fts(db)

    return {
        "mode": "apply" if apply else "dry-run",
        "parser_revision": PARSER_REVISION,
        "selected_law_ids": sorted(requested_ids),
        "affected": len(report_items),
        "errors": len(errors),
        "items": report_items,
        "error_items": errors,
    }
