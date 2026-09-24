"""Small, deterministic helpers for decomposing composite Chinese queries."""

from __future__ import annotations

import re

_QUESTION_SPLIT_RE = re.compile(r"[?？!！;；。]+")
_INCLUSION_OBJECT_RE = re.compile(
    r"(?:是否|有無|有沒有)?(?:也)?(?:包含|包括|涵蓋|納入)\s*"
    r"(?P<object>[\u3400-\u9fffA-Za-z0-9（）()、與和及]{2,30})"
)
_OBJECT_SPLIT_RE = re.compile(r"[、與和及]")
_TRAILING_PARTICLES_RE = re.compile(r"(?:嗎|呢|之內|在內)$")
_IGNORED_OBJECTS = {"哪些", "什麼", "何者", "何種", "那些", "哪一些"}
_BROAD_TOPIC_MARKERS = ("相關規定", "有哪些規定", "規定為何", "規定有哪些")
_EXHAUSTIVE_MARKERS = ("所有", "全部", "全數", "完整", "逐條", "每一條")
_PENALTY_TOPIC_MARKERS = (
    "懲處",
    "懲罰",
    "處罰",
    "裁罰",
    "罰則",
    "罰鍰",
    "罰金",
    "刑責",
)
_PENALTY_QUERY_EXPANSION = "罰則 處罰 裁罰 罰鍰 罰金 有期徒刑 拘役"
_ARTICLE_HINT_RE = re.compile(
    r"第\s*[一二三四五六七八九十百千萬〇○零兩\d\-之]+\s*條"
)


def extract_focus_terms(query: str) -> tuple[str, ...]:
    """Extract explicit objects from inclusion questions without domain hard-coding."""
    terms: list[str] = []
    for match in _INCLUSION_OBJECT_RE.finditer(query):
        value = _TRAILING_PARTICLES_RE.sub("", match.group("object").strip())
        for part in _OBJECT_SPLIT_RE.split(value):
            term = part.strip(" ，、:：?？!！。")
            if 2 <= len(term) <= 20 and term not in _IGNORED_OBJECTS and term not in terms:
                terms.append(term)
    return tuple(terms)


def split_query_facets(query: str) -> tuple[str, ...]:
    """Return conservative question clauses plus explicit inclusion objects."""
    facets: list[str] = []
    for raw in _QUESTION_SPLIT_RE.split(query):
        facet = raw.strip(" ，、:：")
        if len(facet) >= 2 and facet not in facets:
            facets.append(facet)
    for term in extract_focus_terms(query):
        if term not in facets:
            facets.append(term)
    return tuple(facets)


def is_broad_regulatory_query(query: str) -> bool:
    """Detect topic-level requests that need coverage across governing sources."""
    normalized = re.sub(r"\s+", "", query)
    return not _ARTICLE_HINT_RE.search(normalized) and any(
        marker in normalized for marker in _BROAD_TOPIC_MARKERS
    )


def is_exhaustive_query(query: str) -> bool:
    """Detect requests that claim complete provision coverage rather than relevance."""
    normalized = re.sub(r"\s+", "", query)
    return not _ARTICLE_HINT_RE.search(normalized) and any(
        marker in normalized for marker in _EXHAUSTIVE_MARKERS
    )


def is_penalty_topic_query(query: str) -> bool:
    """Recognize statutory penalty vocabulary, including common user aliases."""
    normalized = re.sub(r"\s+", "", query)
    return any(marker in normalized for marker in _PENALTY_TOPIC_MARKERS)


def exhaustive_section_heading(query: str) -> str | None:
    """Resolve exhaustive topic intent to a stored structural chapter heading."""
    if is_exhaustive_query(query) and is_penalty_topic_query(query):
        return "罰則"
    return None


def expand_regulatory_query(query: str) -> str:
    """Add bounded legal synonyms for lexical retrieval without rewriting intent."""
    if not is_penalty_topic_query(query):
        return query
    return f"{query} {_PENALTY_QUERY_EXPANSION}"
