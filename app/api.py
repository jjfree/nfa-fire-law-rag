from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select

from app import __version__
from app.db import init_db, session_scope
from app.ingest import crawl_category
from app.models import Law, LawVersion
from app.search import exact_article, hybrid_search

app = FastAPI(title="NFA Fire Law RAG API", version=__version__)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.post("/v1/admin/init-db")
def api_init_db():
    init_db()
    return {"status": "ok"}


@app.post("/v1/admin/crawl")
def api_crawl(max_laws: int | None = Query(default=None, ge=1, le=1000)):
    try:
        return crawl_category(max_laws=max_laws)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"crawl failed: {type(exc).__name__}: {exc}") from exc


@app.get("/v1/search")
def api_search(q: str = Query(min_length=1), top_k: int = Query(default=8, ge=1, le=50), law_title: str | None = None):
    return {"query": q, "results": [asdict(x) for x in hybrid_search(q, top_k, law_title)]}


@app.get("/v1/article")
def api_article(law_title: str, article: str):
    return {"results": [asdict(x) for x in exact_article(law_title, article)]}


@app.get("/v1/laws")
def api_laws():
    with session_scope() as db:
        rows = db.scalars(select(Law).order_by(Law.title)).all()
        return [
            {"id": x.id, "title": x.title, "category": x.category, "source_url": x.source_url}
            for x in rows
        ]


@app.get("/v1/laws/{law_id}/versions")
def api_versions(law_id: int):
    with session_scope() as db:
        rows = db.scalars(
            select(LawVersion).where(LawVersion.law_id == law_id).order_by(LawVersion.version_no.desc())
        ).all()
        return [
            {
                "id": x.id,
                "version_no": x.version_no,
                "content_hash": x.content_hash,
                "is_current": x.is_current,
                "fetched_at": x.fetched_at,
                "metadata_json": x.metadata_json,
            }
            for x in rows
        ]
