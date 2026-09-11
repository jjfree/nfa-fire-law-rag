from dataclasses import asdict
from urllib.parse import urlparse

from sqlalchemy import select

from app.config import get_settings
from app.crawler.discovery import DiscoveredLawLink, discover_law_links
from app.crawler.fetch import HttpFetcher
from app.db import session_scope
from app.embedding import get_embedder
from app.models import Law, LawChunk, LawVersion
from app.parser import metadata_json, parse_law_html


class IngestError(RuntimeError):
    pass


def _validate_source(url: str) -> None:
    settings = get_settings()
    host = urlparse(url).hostname or ""
    if settings.nfa_allowed_host and host.lower() != settings.nfa_allowed_host.lower():
        raise IngestError(f"Refusing source outside allowed host: {host}")


def ingest_link(link: DiscoveredLawLink, fetcher: HttpFetcher | None = None) -> dict:
    _validate_source(link.url)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher()
    try:
        page = fetcher.fetch(link.url)
        _validate_source(page.url)
        parsed = parse_law_html(page.text, link.title)
        if len(parsed.text) < 20:
            raise IngestError(f"Parsed content too short: {link.url}")
        embedder = get_embedder()
        vectors = embedder.embed([f"{parsed.title}\n{c.article_label or ''}\n{c.content}" for c in parsed.chunks])

        with session_scope() as db:
            law = db.scalar(select(Law).where(Law.source_key == link.source_key))
            if law is None:
                law = Law(source_key=link.source_key, title=parsed.title, source_url=page.url)
                db.add(law)
                db.flush()
            else:
                law.title = parsed.title
                law.source_url = page.url

            existing = db.scalar(
                select(LawVersion).where(
                    LawVersion.law_id == law.id,
                    LawVersion.content_hash == parsed.content_hash,
                )
            )
            if existing:
                return {"status": "unchanged", "law_id": law.id, "title": law.title, "version": existing.version_no}

            current_versions = db.scalars(select(LawVersion).where(LawVersion.law_id == law.id, LawVersion.is_current.is_(True))).all()
            max_version = db.scalars(select(LawVersion.version_no).where(LawVersion.law_id == law.id)).all()
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
                        embedding=vector,
                    )
                )
            return {
                "status": "inserted",
                "law_id": law.id,
                "title": law.title,
                "version": version.version_no,
                "chunks": len(parsed.chunks),
                "metadata": parsed.metadata,
            }
    finally:
        if own_fetcher:
            fetcher.close()


def crawl_category(category_url: str | None = None, max_laws: int | None = None) -> dict:
    settings = get_settings()
    category_url = category_url or settings.nfa_category_url
    _validate_source(category_url)
    with HttpFetcher() as fetcher:
        category = fetcher.fetch(category_url)
        _validate_source(category.url)
        links = discover_law_links(category.text, category.url)
        if max_laws is not None:
            links = links[:max_laws]
        results = []
        for link in links:
            try:
                results.append({"link": asdict(link), "result": ingest_link(link, fetcher)})
            except Exception as exc:  # continue one-law failures; report them explicitly
                results.append({"link": asdict(link), "error": f"{type(exc).__name__}: {exc}"})
        return {
            "category_url": category.url,
            "discovered": len(links),
            "inserted": sum(1 for r in results if r.get("result", {}).get("status") == "inserted"),
            "unchanged": sum(1 for r in results if r.get("result", {}).get("status") == "unchanged"),
            "errors": sum(1 for r in results if "error" in r),
            "results": results,
        }
