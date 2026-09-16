from dataclasses import asdict

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.answer import answer_question
from app.db import session_scope
from app.models import Law, LawVersion
from app.rerank import retrieve_answer_hits
from app.search import exact_article, hybrid_search

mcp = FastMCP("台灣消防法規 RAG")


@mcp.tool()
def search_fire_law(query: str, top_k: int = 8, law_title: str | None = None) -> list[dict]:
    """Search current NFA fire-law chunks with hybrid lexical + vector retrieval."""
    return [asdict(hit) for hit in hybrid_search(query, top_k, law_title)]


@mcp.tool()
def ask_fire_law(query: str, top_k: int = 8, law_title: str | None = None) -> dict:
    """Answer a fire-law question from current retrieved chunks with citations."""
    hits = retrieve_answer_hits(query, top_k, law_title)
    return {
        "query": query,
        **answer_question(query, hits),
        "results": [asdict(hit) for hit in hits],
    }


@mcp.tool()
def get_fire_law_article(law_title: str, article: str) -> list[dict]:
    """Get an exact current article/point, e.g. law_title='消防法', article='第13條'."""
    return [asdict(hit) for hit in exact_article(law_title, article)]


@mcp.tool()
def list_fire_laws() -> list[dict]:
    """List laws currently stored in the database."""
    with session_scope() as db:
        rows = db.scalars(select(Law).order_by(Law.title)).all()
        return [{"id": x.id, "title": x.title, "source_url": x.source_url} for x in rows]


@mcp.tool()
def list_law_versions(law_id: int) -> list[dict]:
    """List all retained versions for one law, newest first."""
    with session_scope() as db:
        rows = db.scalars(
            select(LawVersion).where(LawVersion.law_id == law_id).order_by(LawVersion.version_no.desc())
        ).all()
        return [
            {
                "id": x.id,
                "version_no": x.version_no,
                "is_current": x.is_current,
                "content_hash": x.content_hash,
                "fetched_at": x.fetched_at.isoformat(),
                "metadata_json": x.metadata_json,
            }
            for x in rows
        ]


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
