import re
from dataclasses import dataclass

from sqlalchemy import Float, case, cast, func, literal, select

from app.config import get_settings
from app.db import session_scope
from app.embedding import get_embedder
from app.models import Law, LawChunk, LawVersion


ARTICLE_HINT_RE = re.compile(r"(第\s*[一二三四五六七八九十百千萬〇○零兩\d\-之]+\s*條(?:\s*之\s*[一二三四五六七八九十百千\d]+)?)")


@dataclass
class SearchHit:
    chunk_id: int
    law_id: int
    law_title: str
    version_no: int
    article_label: str | None
    heading: str | None
    content: str
    source_url: str
    vector_score: float
    lexical_score: float
    hybrid_score: float


def _article_hint(query: str) -> str | None:
    match = ARTICLE_HINT_RE.search(query)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def hybrid_search(query: str, top_k: int | None = None, law_title: str | None = None) -> list[SearchHit]:
    settings = get_settings()
    top_k = top_k or settings.default_top_k
    query_vector = get_embedder().embed([query])[0]
    vector_weight = settings.hybrid_vector_weight
    lexical_weight = 1.0 - vector_weight

    vector_score = (literal(1.0) - LawChunk.embedding.cosine_distance(query_vector)).label("vector_score")
    content_sim = func.similarity(LawChunk.content, query)
    title_sim = func.similarity(Law.title, query)
    title_article_sim = func.similarity(
        func.concat(Law.title, func.coalesce(LawChunk.article_label, "")), query
    )
    article_hint = _article_hint(query)
    if article_hint:
        article_exact = case(
            (
                func.replace(func.coalesce(LawChunk.article_label, ""), " ", "") == article_hint,
                1.0,
            ),
            else_=0.0,
        )
        lexical_score = func.greatest(
            content_sim, title_sim, title_article_sim, article_exact
        ).label("lexical_score")
    else:
        lexical_score = func.greatest(content_sim, title_sim, title_article_sim).label(
            "lexical_score"
        )

    hybrid_score = (
        cast(vector_score, Float) * vector_weight + cast(lexical_score, Float) * lexical_weight
    ).label("hybrid_score")

    stmt = (
        select(
            LawChunk.id,
            Law.id.label("law_id"),
            Law.title,
            LawVersion.version_no,
            LawChunk.article_label,
            LawChunk.heading,
            LawChunk.content,
            Law.source_url,
            vector_score,
            lexical_score,
            hybrid_score,
        )
        .join(LawVersion, LawChunk.version_id == LawVersion.id)
        .join(Law, LawVersion.law_id == Law.id)
        .where(LawVersion.is_current.is_(True))
        .order_by(hybrid_score.desc())
        .limit(top_k)
    )
    if law_title:
        stmt = stmt.where(Law.title.ilike(f"%{law_title}%"))

    with session_scope() as db:
        rows = db.execute(stmt).all()
        return [
            SearchHit(
                chunk_id=r.id,
                law_id=r.law_id,
                law_title=r.title,
                version_no=r.version_no,
                article_label=r.article_label,
                heading=r.heading,
                content=r.content,
                source_url=r.source_url,
                vector_score=float(r.vector_score or 0.0),
                lexical_score=float(r.lexical_score or 0.0),
                hybrid_score=float(r.hybrid_score or 0.0),
            )
            for r in rows
        ]


def exact_article(law_title: str, article_label: str) -> list[SearchHit]:
    normalized = "".join(article_label.split())
    with session_scope() as db:
        rows = db.execute(
            select(LawChunk, LawVersion, Law)
            .join(LawVersion, LawChunk.version_id == LawVersion.id)
            .join(Law, LawVersion.law_id == Law.id)
            .where(
                LawVersion.is_current.is_(True),
                Law.title.ilike(f"%{law_title}%"),
                func.replace(LawChunk.article_label, " ", "") == normalized,
            )
            .order_by(Law.title, LawChunk.seq)
        ).all()
        return [
            SearchHit(
                chunk_id=chunk.id,
                law_id=law.id,
                law_title=law.title,
                version_no=version.version_no,
                article_label=chunk.article_label,
                heading=chunk.heading,
                content=chunk.content,
                source_url=law.source_url,
                vector_score=1.0,
                lexical_score=1.0,
                hybrid_score=1.0,
            )
            for chunk, version, law in rows
        ]
