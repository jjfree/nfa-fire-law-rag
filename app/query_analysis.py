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
