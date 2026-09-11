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
from app.parser import append_attachment_text, metadata_json, parse_law_html


class IngestError(RuntimeError):
    pass


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
    """Download same-host PDFs linked by the detail page and append searchable text."""
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
    for url in urls:
        try:
            content_type, content = fetcher.fetch_bytes(url)
            is_pdf = (
                "pdf" in content_type.lower()
                or urlparse(url).path.lower().endswith(".pdf")
                or content.startswith(b"%PDF-")
            )
            if not is_pdf:
                reason = "unsupported content (not detected as PDF)"
                report["skipped"].append({"url": url, "reason": reason})
                report["errors"].append(f"{reason}: {url}")
                continue
            text = extract_pdf_text(content, max_pages=settings.max_attachment_pages)
            if len(text) < 20:
                reason = "PDF has no searchable text"
                report["skipped"].append({"url": url, "reason": reason})
                report["errors"].append(f"{reason}: {url}")
                continue
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
    return report


def ingest_link(link: DiscoveredLawLink, fetcher: HttpFetcher | None = None) -> dict:
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
            cached_metadata = None
            if cached_current is not None and cached_current.metadata_json:
                try:
                    cached_metadata = json.loads(cached_current.metadata_json)
                except (TypeError, json.JSONDecodeError):
                    cached_metadata = None
            cached_attachments = cached_metadata and cached_metadata.get("attachments")
            if (
                cached_current is not None
                and cached_attachments is not None
                and (
                    cached_current.raw_text == parsed.text
                    or cached_current.raw_text.startswith(parsed.text + "\n\n附件：")
                )
            ):
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
        vectors = embedder.embed(
            [
                f"{parsed.title}\n{c.heading or ''}\n{c.article_label or ''}\n{c.content}"
                for c in parsed.chunks
            ]
        )

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

            existing = db.scalar(
                select(LawVersion).where(
                    LawVersion.law_id == law.id,
                    LawVersion.content_hash == parsed.content_hash,
                )
            )
            if existing:
                return {
                    "status": "unchanged",
                    "law_id": law.id,
                    "title": law.title,
                    "version": existing.version_no,
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
        category, all_links = _discover_category(category_url, fetcher)
        links = all_links[:max_laws] if max_laws is not None else all_links
        results = []
        for link in links:
            try:
                results.append({"link": asdict(link), "result": ingest_link(link, fetcher)})
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
            "errors": sum(1 for r in results if "error" in r),
            "results": results,
        }
