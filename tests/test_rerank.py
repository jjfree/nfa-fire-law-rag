from types import SimpleNamespace

import pytest


def _hit(chunk_id: int, content: str):
    return SimpleNamespace(
        chunk_id=chunk_id,
        law_id=1,
        law_title="消防法",
        version_no=1,
        article_label=f"第{chunk_id}條",
        heading=None,
        content=content,
        source_url=f"https://example.test/{chunk_id}",
        vector_score=0.4,
        lexical_score=0.4,
        hybrid_score=0.4,
    )


def _settings(**overrides):
    values = {
        "reranker_enabled": True,
        "reranker_provider": "ollama",
        "reranker_model": "gemma4:31b-cloud",
        "reranker_candidate_limit": 24,
        "reranker_input_limit": 12,
        "reranker_max_chars_per_candidate": 160,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("消防設備師與消防設備士的權限差異?", True),
        ("消防設備師及消防設備士各自可以做什麼？", True),
        ("請說明消防法第7條內容", False),
        ("消防設備師是誰？", False),
    ],
)
def test_is_reranker_query_detects_generic_comparison_intent(query, expected):
    from app.rerank import is_reranker_query

    assert is_reranker_query(query) is expected


def test_ollama_reranker_prioritizes_answering_article(monkeypatch):
    from app import rerank

    mention = _hit(1, "消防設備師與消防設備士薪資資料應定期陳報。")
    authority = _hit(
        7,
        "消防安全設備之設計、監造，應由消防設備師為之；測試及檢修，得由消防設備士為之。",
    )
    captured = {}

    def fake_complete(prompt, model):
        captured["prompt"] = prompt
        captured["model"] = model
        return '```json\n{"ranked_chunk_ids":[7,999,7]}\n```'

    monkeypatch.setattr(rerank, "get_settings", lambda: _settings())
    monkeypatch.setattr(rerank, "_complete_rerank", fake_complete)

    results = rerank.OllamaReranker().rerank(
        "消防設備師與消防設備士的權限差異?", [mention, authority], top_k=2
    )

    assert [hit.chunk_id for hit in results] == [7, 1]
    assert captured["model"] == "gemma4:31b-cloud"
    assert "不要只看人物或名詞是否出現" in captured["prompt"]
    assert "應由消防設備師為之" in captured["prompt"]


def test_rerank_candidate_selection_keeps_leaders_and_answer_bearing_explorer():
    from app.rerank import _select_rerank_candidates

    candidates = [_hit(index, f"僅提到角色 {index}") for index in range(1, 25)]
    candidates[14].content = "設計、監造應由甲為之；測試、檢修得由乙為之。"

    selected = _select_rerank_candidates(candidates, top_k=8, input_limit=12)

    assert [hit.chunk_id for hit in selected[:8]] == list(range(1, 9))
    assert 15 in [hit.chunk_id for hit in selected]


def test_retrieve_answer_hits_expands_and_reranks_candidates(monkeypatch):
    from app import rerank

    candidates = [_hit(index, f"候選條文 {index}") for index in range(1, 25)]
    calls = []

    def fake_search(query, top_k, law_title):
        calls.append((query, top_k, law_title))
        return candidates[:top_k]

    def fake_rerank(self, query, hits, top_k):
        return [hits[14], *hits[: top_k - 1]]

    monkeypatch.setattr(rerank, "get_settings", lambda: _settings())
    monkeypatch.setattr(rerank, "hybrid_search", fake_search)
    monkeypatch.setattr(rerank.OllamaReranker, "rerank", fake_rerank)

    results = rerank.retrieve_answer_hits(
        "消防設備師與消防設備士的權限差異?", top_k=8, law_title="消防法"
    )

    assert calls == [("消防設備師與消防設備士的權限差異?", 24, "消防法")]
    assert len(results) == 8
    assert results[0].chunk_id == 15


def test_retrieve_answer_hits_falls_back_when_reranker_fails(monkeypatch):
    from app import rerank
    from app.answer import AnswerGenerationError

    candidates = [_hit(index, f"候選條文 {index}") for index in range(1, 25)]
    monkeypatch.setattr(rerank, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        rerank,
        "hybrid_search",
        lambda query, top_k, law_title: candidates[:top_k],
    )

    def fail(self, query, hits, top_k):
        raise AnswerGenerationError("Ollama unavailable")

    monkeypatch.setattr(rerank.OllamaReranker, "rerank", fail)

    results = rerank.retrieve_answer_hits(
        "消防設備師與消防設備士的權限差異?", top_k=8
    )

    assert results == candidates[:8]


def test_retrieve_answer_hits_keeps_ordinary_search_deterministic(monkeypatch):
    from app import rerank

    candidates = [_hit(1, "消防法第七條內容")]
    calls = []

    def fake_search(query, top_k, law_title):
        calls.append((query, top_k, law_title))
        return candidates

    monkeypatch.setattr(rerank, "get_settings", lambda: _settings())
    monkeypatch.setattr(rerank, "hybrid_search", fake_search)

    results = rerank.retrieve_answer_hits("請說明消防法第7條內容", top_k=8)

    assert results == candidates
    assert calls == [("請說明消防法第7條內容", 8, None)]
