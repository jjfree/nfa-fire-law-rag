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
from app.search import SearchHit, hybrid_search

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
    return OllamaAnswerer(
        base_url=base_url,
        model=model,
        timeout_seconds=settings.reranker_timeout_seconds,
        temperature=0.0,
        think=False,
        max_output_tokens=settings.reranker_max_output_tokens,
        api_key=api_key,
    ).complete(prompt)


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
        return hybrid_search(query, top_k=top_k, law_title=law_title)

    candidate_limit = max(top_k, settings.reranker_candidate_limit)
    candidates = hybrid_search(query, top_k=candidate_limit, law_title=law_title)
    if len(candidates) <= top_k:
        return candidates
    try:
        return OllamaReranker().rerank(query, candidates, top_k)
    except (AnswerGenerationError, RerankError):
        return candidates[:top_k]
