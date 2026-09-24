import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import Float, case, cast, func, literal, or_, select, text

from app.config import get_settings
from app.db import embedding_from_storage, session_scope
from app.embedding import get_embedder
from app.models import Law, LawChunk, LawVersion
from app.query_analysis import expand_regulatory_query, extract_focus_terms

ARTICLE_HINT_RE = re.compile(
    r"(第\s*[一二三四五六七八九十百千萬〇○零兩\d\-之]+\s*條(?:\s*之\s*[一二三四五六七八九十百千\d]+)?)"
)
_TEXT_TOKEN_RE = re.compile(r"[\u3400-\u9fffA-Za-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_EXPLICIT_DEFINITION_QUERY_MARKERS = ("定義", "何謂", "所稱", "係指", "是指")
_IDENTITY_QUERY_MARKERS = ("是誰", "什麼是", "指誰")
_ACTION_QUERY_MARKERS = (
    "應如何",
    "應負",
    "應辦",
    "義務",
    "責任",
    "程序",
    "期限",
    "罰鍰",
    "處罰",
    "申請",
    "設置",
    "維護",
    "辦理",
)
_QUERY_PREFIXES = (
    "請再次協助查詢",
    "請再次協助說明",
    "請再次查詢",
    "請再次說明",
    "請協助查詢",
    "請協助說明",
    "麻煩查詢",
    "麻煩說明",
    "想請問",
    "請查詢",
    "請說明",
    "請問",
)
_TITLE_CONNECTOR_RE = re.compile(r"[\s、，,及與和暨（）()《》「」『』]+")
_TITLE_SUFFIXES = (
    "消防安全設備相關規定",
    "相關規定",
    "自治條例",
    "注意事項",
    "作業要點",
    "處理原則",
    "管理辦法",
    "實施辦法",
    "申報辦法",
    "辦法",
    "規則",
    "標準",
    "規程",
    "要點",
)
_DEFINITION_TERM_RE = re.compile(
    r"(?:本法|本條例|本辦法|本規則|本須知|本標準)?所稱\s*"
    r"(?P<term>[\u3400-\u9fffA-Za-z0-9（）()]{2,24}?)\s*"
    r"(?:，|、|：|:|係指|是指)"
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
    retrieval_mode: str = "hybrid"


@dataclass(frozen=True)
class SectionSearchResult:
    hits: list[SearchHit]
    law_title: str
    heading: str
    total_matches: int


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


def _normalize_query(query: str) -> str:
    """Remove conversational wrappers without changing legal terminology."""
    normalized = query.strip()
    for prefix in _QUERY_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].lstrip(" ，、:：")
            break
    normalized = re.sub(r"[?？!！。]+$", "", normalized).strip()
    return re.sub(r"\s+", " ", normalized)


def _matched_law_titles(query: str, titles: list[str]) -> tuple[str, ...]:
    """Route a query to exact or unambiguously normalized law-title intent."""

    def intent_key(value: str) -> str:
        key = _TITLE_CONNECTOR_RE.sub("", value)
        for suffix in _TITLE_SUFFIXES:
            if key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        return key

    query_key = intent_key(_normalize_query(query))
    matches = {
        title
        for title in titles
        if len(title) >= 3
        and (
            title in query
            or (len(intent_key(title)) >= 6 and intent_key(title) in query_key)
        )
    }
    if not matches:
        return ()
    return tuple(
        sorted(
            title
            for title in matches
            if not any(title != other and title in other for other in matches)
        )
    )


def _lexical_terms(value: str) -> set[str]:
    """Return overlapping CJK n-grams and whole alphanumeric terms."""
    terms: set[str] = set()
    for token in _TEXT_TOKEN_RE.findall(value.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            terms.update(
                token[index : index + size]
                for size in (2, 3)
                for index in range(len(token) - size + 1)
            )
        else:
            terms.add(token)
    return terms


def _defined_terms(content: str) -> tuple[str, ...]:
    """Extract terms from common Taiwanese legal definition clauses."""
    return tuple(dict.fromkeys(match.group("term") for match in _DEFINITION_TERM_RE.finditer(content)))


def _is_definition_query(query: str) -> bool:
    if any(marker in query for marker in _EXPLICIT_DEFINITION_QUERY_MARKERS):
        return True
    if any(marker in query for marker in _ACTION_QUERY_MARKERS):
        return False
    if any(marker in query for marker in _IDENTITY_QUERY_MARKERS):
        return True
    # Short noun-phrase questions such as「消防法規的主管機關」normally ask
    # for identity/meaning even when they do not literally say「定義」.
    return "的" in query and 0 < len("".join(_CJK_RUN_RE.findall(query))) <= 30


def _definition_score(query: str, content: str) -> float:
    """Score a clause only when it defines the term actually being asked about."""
    terms = _defined_terms(content)
    if not terms or not _is_definition_query(query):
        return 0.0

    query_text = "".join(_CJK_RUN_RE.findall(query))
    if any(term in query_text for term in terms):
        return 1.0
    if any(marker in query for marker in _EXPLICIT_DEFINITION_QUERY_MARKERS):
        return 0.55
    return 0.0


def _text_lexical_score(
    query: str, title: str, article: str | None, heading: str | None, content: str
) -> float:
    query_terms = _lexical_terms(query)
    if not query_terms:
        query_terms = {query.lower()}

    def overlap(value: str | None) -> float:
        terms = _lexical_terms(value or "")
        return len(query_terms & terms) / len(query_terms) if terms else 0.0

    score = max(overlap(content), overlap(heading) * 0.9, overlap(title) * 0.8)
    searchable_text = " ".join(value for value in (title, article, heading, content) if value).lower()
    if any(term.lower() in searchable_text for term in extract_focus_terms(query)):
        # Inclusion questions often contain one decisive noun surrounded by
        # generic wording. Exact coverage of that noun must not be diluted by
        # the long-query n-gram denominator.
        score = max(score, 1.0)
    score = max(score, _definition_score(query, content))
    hint = _article_hint(query)
    if hint and re.sub(r"\s+", "", article or "") == hint:
        score = max(score, 1.0)
    return min(score, 1.0)


def _is_deleted_only(article_label: str | None, content: str) -> bool:
    """Return true only for a provision whose body is merely a deletion marker."""
    compact = re.sub(r"\s+", "", content)
    label = re.sub(r"\s+", "", article_label or "")
    if label and compact.startswith(label):
        compact = compact[len(label) :]
    return compact in {"刪除", "（刪除）", "(刪除)"}


def exhaustive_section_search(
    query: str,
    heading_term: str,
    law_title: str | None = None,
) -> SectionSearchResult | None:
    """Return one exact law section in stored provision order, without top-k loss."""
    with session_scope() as db:
        titles = list(db.scalars(select(Law.title).distinct()))
        if law_title:
            scoped_titles = (law_title,) if law_title in titles else ()
        else:
            scoped_titles = _matched_law_titles(query, titles)
        if len(scoped_titles) != 1:
            return None

        scoped_title = scoped_titles[0]
        rows = db.execute(
            select(LawChunk, LawVersion, Law)
            .join(LawVersion, LawChunk.version_id == LawVersion.id)
            .join(Law, LawVersion.law_id == Law.id)
            .where(
                LawVersion.is_current.is_(True),
                Law.title == scoped_title,
                LawChunk.heading.contains(heading_term),
            )
            .order_by(LawChunk.seq)
        ).all()

        hits = [
            SearchHit(
                chunk_id=chunk.id,
                law_id=law.id,
                law_title=law.title,
                version_no=version.version_no,
                article_label=chunk.article_label,
                heading=chunk.heading,
                content=chunk.content,
                source_url=law.source_url,
                vector_score=0.0,
                lexical_score=0.0,
                hybrid_score=0.0,
                retrieval_mode="structural_section",
            )
            for chunk, version, law in rows
            if not _is_deleted_only(chunk.article_label, chunk.content)
        ]
        if not hits:
            return None
        return SectionSearchResult(
            hits=hits,
            law_title=scoped_title,
            heading=hits[0].heading or heading_term,
            total_matches=len(hits),
        )


def _sqlite_hybrid_search(query: str, top_k: int, law_title: str | None) -> list[SearchHit]:
    settings = get_settings()
    query = _normalize_query(query) or query
    query_vector = np.asarray(get_embedder().embed([query])[0], dtype=np.float32)
    query_norm = np.linalg.norm(query_vector) or 1.0
    lexical_query = expand_regulatory_query(query)
    match_query = _cjk_fts_query(lexical_query)

    with session_scope() as db:
        titles = list(db.scalars(select(Law.title).distinct()))
        matched_titles = _matched_law_titles(query, titles)
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
        if candidate_ids and matched_titles:
            stmt = stmt.where(
                or_(LawChunk.id.in_(candidate_ids), Law.title.in_(matched_titles))
            )
        elif candidate_ids:
            stmt = stmt.where(LawChunk.id.in_(candidate_ids))
        elif matched_titles:
            stmt = stmt.where(Law.title.in_(matched_titles))
        if law_title:
            stmt = stmt.where(Law.title.ilike(f"%{law_title}%"))
        rows = db.execute(stmt).all()

        vector_weight = (
            settings.hash_vector_weight
            if settings.embedding_provider.lower() == "hash"
            else settings.hybrid_vector_weight
        )
        lexical_weight = 1.0 - vector_weight
        scored: list[tuple[float, SearchHit]] = []
        for row in rows:
            vector = embedding_from_storage(row.embedding)
            denominator = (np.linalg.norm(vector) or 1.0) * query_norm
            vector_score = float(np.dot(vector, query_vector) / denominator)
            vector_score = max(0.0, min(1.0, vector_score))
            lexical_score = _text_lexical_score(
                lexical_query, row.title, row.article_label, row.heading, row.content
            )
            if row.title in matched_titles:
                lexical_score = min(1.0, lexical_score + settings.law_title_match_boost)
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
    query = _normalize_query(query) or query
    if settings.storage_backend.lower() == "sqlite":
        return _sqlite_hybrid_search(query, top_k, law_title)
    query_vector = get_embedder().embed([query])[0]
    lexical_query = expand_regulatory_query(query)
    vector_weight = settings.hybrid_vector_weight
    lexical_weight = 1.0 - vector_weight

    vector_score = (literal(1.0) - LawChunk.embedding.cosine_distance(query_vector)).label(
        "vector_score"
    )
    content_sim = func.similarity(LawChunk.content, lexical_query)
    title_sim = func.similarity(Law.title, lexical_query)
    title_article_sim = func.similarity(
        func.concat(Law.title, func.coalesce(LawChunk.article_label, "")), lexical_query
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
