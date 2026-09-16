"""Conditional Ollama reranking for answer-facing retrieval.

Raw search remains deterministic.  This module only broadens and reranks
candidates for questions whose comparison/scope intent is difficult to express
with literal Chinese n-gram overlap.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from app.answer import AnswerGenerationError, OllamaAnswerer
from app.config import get_settings
from app.query_analysis import (
    extract_focus_terms,
    is_broad_regulatory_query,
    split_query_facets,
)
from app.search import SearchHit, _matched_law_titles, hybrid_search

_COMPARISON_MARKERS = ("差異", "不同", "區別", "比較", "各自", "分別", "有何差別")
_SCOPE_MARKERS = ("權限", "職權", "業務範圍", "執業範圍", "可以做", "能做", "得從事")
_ANSWERABILITY_MARKERS = (
    "應由",
    "得由",
    "不得",
    "僅限",
    "為之",
    "負責",
    "執行",
    "辦理",
    "設計",
    "監造",
    "測試",
    "檢修",
    "職務",
    "業務",
)
_ENTITY_CONNECTOR_RE = re.compile(
    r"[\u3400-\u9fffA-Za-z0-9（）()]{2,24}(?:與|和|及|跟|、|vs\.?)"
    r"[\u3400-\u9fffA-Za-z0-9（）()]{2,24}",
    re.IGNORECASE,
)


class RerankError(RuntimeError):
    """Raised when an LLM rerank response cannot be safely applied."""


def is_reranker_query(query: str) -> bool:
    """Detect entity comparison/scope questions without role-specific terms."""
    has_entities = bool(_ENTITY_CONNECTOR_RE.search("".join(query.split())))
    has_intent = any(marker in query for marker in (*_COMPARISON_MARKERS, *_SCOPE_MARKERS))
    return has_entities and has_intent


def build_rerank_prompt(
    query: str,
    candidates: list[SearchHit],
    max_chars_per_candidate: int,
    top_k: int,
) -> str:
    def compact(content: str) -> str:
        return re.sub(r"\s+", " ", content)[:max_chars_per_candidate]

    passages = "\n".join(
        f"[{hit.chunk_id}] {hit.law_title}|{hit.article_label or hit.heading or '-'}|"
        f"{compact(hit.content)}"
        for hit in candidates
    )
    return f"""你是台灣法規檢索排序器。依問題選出最能直接回答的 {top_k} 筆條文。

規則：
1. 不要只看人物或名詞是否出現；比較權限時，優先選實際分配行為、職務或限制的條文。
2. 只可使用候選的數字 ID，不得猜測條文。
3. 只輸出 JSON，不要 markdown 或說明：{{"ranked_chunk_ids":[ID,...]}}

問題：{query}
候選：
{passages}
"""


def _select_rerank_candidates(
    candidates: list[SearchHit], top_k: int, input_limit: int
) -> list[SearchHit]:
    """Keep the original leaders plus lower-ranked, answer-bearing clauses."""
    leaders = candidates[: min(top_k, input_limit)]
    remaining_slots = max(0, input_limit - len(leaders))
    if not remaining_slots:
        return leaders

    leader_ids = {hit.chunk_id for hit in leaders}
    explorers = sorted(
        (hit for hit in candidates if hit.chunk_id not in leader_ids),
        key=lambda hit: sum(marker in hit.content for marker in _ANSWERABILITY_MARKERS),
        reverse=True,
    )[:remaining_slots]
    return [*leaders, *explorers]


def _parse_ranked_ids(raw: str, valid_ids: set[int]) -> list[int]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise RerankError("reranker did not return a JSON object")
    try:
        data = json.loads(raw[start : end + 1])
    except (TypeError, ValueError) as exc:
        raise RerankError("reranker returned invalid JSON") from exc
    values = data.get("ranked_chunk_ids") if isinstance(data, dict) else None
    if not isinstance(values, list):
        raise RerankError("reranker JSON is missing ranked_chunk_ids")

    ranked: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            chunk_id = int(value)
        except (TypeError, ValueError):
            continue
        if chunk_id in valid_ids and chunk_id not in ranked:
            ranked.append(chunk_id)
    if not ranked:
        raise RerankError("reranker did not select any valid candidate")
    return ranked


@lru_cache(maxsize=128)
def _complete_rerank(prompt: str, model: str) -> str:
    settings = get_settings()
    is_cloud_model = model.endswith(("-cloud", ":cloud"))
    base_url = settings.llm_cloud_base_url if is_cloud_model else settings.llm_base_url
    api_key = settings.ollama_api_key if is_cloud_model else ""
    completion = OllamaAnswerer(
        base_url=base_url,
        model=model,
        timeout_seconds=settings.reranker_timeout_seconds,
        temperature=0.0,
        think=False,
        max_output_tokens=settings.reranker_max_output_tokens,
        api_key=api_key,
    ).complete(prompt)
    return completion.content if hasattr(completion, "content") else completion


class OllamaReranker:
    def rerank(
        self, query: str, candidates: list[SearchHit], top_k: int
    ) -> list[SearchHit]:
        settings = get_settings()
        rerank_candidates = _select_rerank_candidates(
            candidates, top_k, settings.reranker_input_limit
        )
        prompt = build_rerank_prompt(
            query,
            rerank_candidates,
            settings.reranker_max_chars_per_candidate,
            top_k,
        )
        raw = _complete_rerank(prompt, settings.reranker_model)
        ranked_ids = _parse_ranked_ids(raw, {hit.chunk_id for hit in rerank_candidates})
        by_id = {hit.chunk_id: hit for hit in candidates}
        ordered = [by_id[chunk_id] for chunk_id in ranked_ids]
        ordered.extend(hit for hit in candidates if hit.chunk_id not in ranked_ids)
        return ordered[:top_k]


def _evidence_key(hit: SearchHit) -> tuple[int, str | int, str, str]:
    """Deduplicate identical evidence without collapsing repeated section labels."""
    label = "".join((hit.article_label or "").split())
    heading = "".join((hit.heading or "").split())
    content = "".join(hit.content.split())
    return (hit.law_id, label or hit.chunk_id, heading, content)


def _dedupe_provisions(hits: list[SearchHit]) -> list[SearchHit]:
    unique: list[SearchHit] = []
    seen: set[tuple[int, str | int, str, str]] = set()
    for hit in hits:
        key = _evidence_key(hit)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _select_diverse_provisions(hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    """Prefer distinct laws, then allow two per law before an unrestricted fill."""
    unique = _dedupe_provisions(hits)
    selected: list[SearchHit] = []
    selected_keys: set[tuple[int, str | int, str, str]] = set()
    seen_laws: set[int] = set()
    diversity_slots = min(top_k, max(1, (top_k * 3 + 3) // 4))
    for hit in unique:
        if hit.law_id in seen_laws:
            continue
        selected.append(hit)
        selected_keys.add(_evidence_key(hit))
        seen_laws.add(hit.law_id)
        if len(selected) == diversity_slots:
            break
    law_counts = {hit.law_id: 1 for hit in selected}
    for hit in unique:
        key = _evidence_key(hit)
        if key in selected_keys or law_counts.get(hit.law_id, 0) >= 2:
            continue
        selected.append(hit)
        selected_keys.add(key)
        law_counts[hit.law_id] = law_counts.get(hit.law_id, 0) + 1
        if len(selected) == top_k:
            return selected
    for hit in unique:
        key = _evidence_key(hit)
        if key in selected_keys:
            continue
        selected.append(hit)
        selected_keys.add(key)
        if len(selected) == top_k:
            break
    return selected


def _replacement_index(selected: list[SearchHit]) -> int:
    """Prefer replacing a repeated-law result before removing source diversity."""
    law_counts: dict[int, int] = {}
    for hit in selected:
        law_counts[hit.law_id] = law_counts.get(hit.law_id, 0) + 1
    for index in range(len(selected) - 1, -1, -1):
        if law_counts[selected[index].law_id] > 1:
            return index
    return len(selected) - 1


def _is_primary_statute(hit: SearchHit) -> bool:
    """Identify acts and statutes without treating subordinate 辦法 as the parent law."""
    title = hit.law_title.strip()
    return title.endswith("條例") or (title.endswith("法") and not title.endswith("辦法"))


def _reserve_candidate(
    selected: list[SearchHit],
    selected_keys: set[tuple[int, str | int, str, str]],
    candidate: SearchHit,
) -> None:
    key = _evidence_key(candidate)
    if key in selected_keys:
        return
    if len(selected) < 1:
        selected.append(candidate)
    else:
        index = _replacement_index(selected)
        selected_keys.discard(_evidence_key(selected[index]))
        selected[index] = candidate
    selected_keys.add(key)


def _promote_candidate(
    selected: list[SearchHit], candidate: SearchHit, target_index: int
) -> None:
    """Move reserved evidence forward without changing its retrieval scores."""
    key = _evidence_key(candidate)
    current_index = next(
        (index for index, hit in enumerate(selected) if _evidence_key(hit) == key),
        None,
    )
    if current_index is None or current_index <= target_index:
        return
    selected.insert(min(target_index, len(selected) - 1), selected.pop(current_index))


def _promote_focus_evidence(selected: list[SearchHit], focus_terms: tuple[str, ...]) -> None:
    """Place the first provision that directly names the queried object first."""
    for index, hit in enumerate(selected):
        searchable = (
            f"{hit.law_title}\n{hit.article_label or ''}\n"
            f"{hit.heading or ''}\n{hit.content}"
        ).lower()
        if any(term.lower() in searchable for term in focus_terms):
            if index > 0:
                selected.insert(0, selected.pop(index))
            return


def _retrieve_with_facet_coverage(
    query: str, top_k: int, law_title: str | None
) -> list[SearchHit]:
    """Keep broad-query leaders while reserving evidence for distinct facets."""
    settings = get_settings()
    candidate_limit = max(top_k, settings.reranker_candidate_limit)
    base = hybrid_search(query, top_k=candidate_limit, law_title=law_title)
    selected = _select_diverse_provisions(base, top_k)
    selected_keys = {_evidence_key(hit) for hit in selected}

    direct_titles = set(_matched_law_titles(query, [hit.law_title for hit in base]))
    direct_regulation = next((hit for hit in base if hit.law_title in direct_titles), None)
    if direct_regulation is not None:
        _reserve_candidate(selected, selected_keys, direct_regulation)

    # A long composite query can rank many administrative directions ahead of
    # the governing act. Keep the best matching parent statute when one is in
    # the bounded candidate set; this is authority-aware, not title-specific.
    primary_statute = next((hit for hit in base if _is_primary_statute(hit)), None)
    if primary_statute is not None:
        _reserve_candidate(selected, selected_keys, primary_statute)

    focus_terms = extract_focus_terms(query)
    facets = focus_terms or split_query_facets(query)[1:]
    for facet in facets:
        if any(
            facet.lower()
            in f"{hit.law_title}\n{hit.article_label or ''}\n{hit.heading or ''}\n{hit.content}".lower()
            for hit in selected
        ):
            continue
        facet_hits = hybrid_search(facet, top_k=min(max(top_k, 3), 8), law_title=law_title)
        candidate = next(
            (hit for hit in facet_hits if _evidence_key(hit) not in selected_keys),
            None,
        )
        if candidate is None:
            continue
        if len(selected) < top_k:
            selected.append(candidate)
            selected_keys.add(_evidence_key(candidate))
        else:
            _reserve_candidate(selected, selected_keys, candidate)

    # Evidence order is separate from the raw retrieval score: direct object
    # coverage comes first, followed by the governing statute when distinct.
    if direct_regulation is not None:
        _promote_candidate(selected, direct_regulation, target_index=0)
    else:
        _promote_focus_evidence(selected, focus_terms)
    if primary_statute is not None and (
        direct_regulation is None
        or _evidence_key(primary_statute) != _evidence_key(direct_regulation)
    ):
        _promote_candidate(selected, primary_statute, target_index=1)
    return selected


def retrieve_answer_hits(
    query: str, top_k: int, law_title: str | None = None
) -> list[SearchHit]:
    """Retrieve answer evidence and conditionally rerank ambiguous comparisons."""
    settings = get_settings()
    should_rerank = (
        settings.reranker_enabled
        and settings.reranker_provider.lower() == "ollama"
        and is_reranker_query(query)
    )
    if not should_rerank:
        if (
            extract_focus_terms(query)
            or len(split_query_facets(query)) > 1
            or is_broad_regulatory_query(query)
        ):
            return _retrieve_with_facet_coverage(query, top_k, law_title)
        return hybrid_search(query, top_k=top_k, law_title=law_title)

    candidate_limit = max(top_k, settings.reranker_candidate_limit)
    candidates = hybrid_search(query, top_k=candidate_limit, law_title=law_title)
    if len(candidates) <= top_k:
        return candidates
    try:
        return OllamaReranker().rerank(query, candidates, top_k)
    except (AnswerGenerationError, RerankError):
        return candidates[:top_k]
