import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import Float, case, cast, func, literal, select, text

from app.config import get_settings
from app.db import embedding_from_storage, session_scope
from app.embedding import get_embedder
from app.models import Law, LawChunk, LawVersion

ARTICLE_HINT_RE = re.compile(
    r"(第\s*[一二三四五六七八九十百千萬〇○零兩\d\-之]+\s*條(?:\s*之\s*[一二三四五六七八九十百千\d]+)?)"
)


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


def _cjk_fts_query(query: str) -> str:
    """Create a safe FTS5 OR query, including CJK n-grams."""
    tokens = re.findall(r"[\u3400-\u9fffA-Za-z0-9]+", query.lower())
    terms: set[str] = set(tokens)
    for token in tokens:
        terms.update(token[i : i + n] for n in (2, 3) for i in range(len(token) - n + 1))
    selected = sorted(terms, key=lambda item: (-len(item), item))[:80]
    return " OR ".join(f'"{term}"' for term in selected)


def _text_lexical_score(
    query: str, title: str, article: str | None, heading: str | None, content: str
) -> float:
    query_terms = set(re.findall(r"[\u3400-\u9fffA-Za-z0-9]{2,3}", query.lower()))
    if not query_terms:
        query_terms = {query.lower()}

    def overlap(value: str | None) -> float:
        terms = set(re.findall(r"[\u3400-\u9fffA-Za-z0-9]{2,3}", (value or "").lower()))
        return len(query_terms & terms) / len(query_terms) if terms else 0.0

    score = max(overlap(content), overlap(heading) * 0.9, overlap(title) * 0.8)
    hint = _article_hint(query)
    if hint and re.sub(r"\s+", "", article or "") == hint:
        score = max(score, 1.0)
    return min(score, 1.0)


def _sqlite_hybrid_search(query: str, top_k: int, law_title: str | None) -> list[SearchHit]:
    settings = get_settings()
    query_vector = np.asarray(get_embedder().embed([query])[0], dtype=np.float32)
    query_norm = np.linalg.norm(query_vector) or 1.0
    match_query = _cjk_fts_query(query)

    with session_scope() as db:
        candidate_ids: list[int] = []
        if match_query:
            fts_rows = db.execute(
                text(
                    """
                    SELECT chunk_id FROM law_chunks_fts
                    WHERE law_chunks_fts MATCH :match_query
                    ORDER BY bm25(law_chunks_fts)
                    LIMIT :candidate_limit
                    """
                ),
                {
                    "match_query": match_query,
                    "candidate_limit": settings.sqlite_fts_candidate_limit,
                },
            ).all()
            candidate_ids = [int(row[0]) for row in fts_rows]

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
                LawChunk.embedding,
            )
            .join(LawVersion, LawChunk.version_id == LawVersion.id)
            .join(Law, LawVersion.law_id == Law.id)
            .where(LawVersion.is_current.is_(True))
        )
        if candidate_ids:
            stmt = stmt.where(LawChunk.id.in_(candidate_ids))
        if law_title:
            stmt = stmt.where(Law.title.ilike(f"%{law_title}%"))
        rows = db.execute(stmt).all()

        vector_weight = settings.hybrid_vector_weight
        lexical_weight = 1.0 - vector_weight
        scored: list[tuple[float, SearchHit]] = []
        for row in rows:
            vector = embedding_from_storage(row.embedding)
            denominator = (np.linalg.norm(vector) or 1.0) * query_norm
            vector_score = float(np.dot(vector, query_vector) / denominator)
            vector_score = max(0.0, min(1.0, vector_score))
            lexical_score = _text_lexical_score(
                query, row.title, row.article_label, row.heading, row.content
            )
            hybrid_score = vector_score * vector_weight + lexical_score * lexical_weight
            scored.append(
                (
                    hybrid_score,
                    SearchHit(
                        chunk_id=row.id,
                        law_id=row.law_id,
                        law_title=row.title,
                        version_no=row.version_no,
                        article_label=row.article_label,
                        heading=row.heading,
                        content=row.content,
                        source_url=row.source_url,
                        vector_score=vector_score,
                        lexical_score=lexical_score,
                        hybrid_score=hybrid_score,
                    ),
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]


def hybrid_search(
    query: str, top_k: int | None = None, law_title: str | None = None
) -> list[SearchHit]:
    settings = get_settings()
    top_k = top_k or settings.default_top_k
    if settings.storage_backend.lower() == "sqlite":
        return _sqlite_hybrid_search(query, top_k, law_title)
    query_vector = get_embedder().embed([query])[0]
    vector_weight = settings.hybrid_vector_weight
    lexical_weight = 1.0 - vector_weight

    vector_score = (literal(1.0) - LawChunk.embedding.cosine_distance(query_vector)).label(
        "vector_score"
    )
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
