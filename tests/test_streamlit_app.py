from dataclasses import dataclass

from app.streamlit_app import (
    ANSWER_MODEL_OPTIONS,
    build_answer_diagnostic,
    build_evidence_cards,
    build_response,
    evidence_anchor,
    linkify_citations,
)


@dataclass
class FakeHit:
    law_title: str
    article_label: str | None
    heading: str | None
    content: str
    source_url: str
    version_no: int
    vector_score: float
    lexical_score: float
    hybrid_score: float


def test_build_answer_diagnostic_shows_actual_tokens_and_completed_status():
    diagnostic = build_answer_diagnostic(
        {
            "answer_model": "gemma4:31b-cloud",
            "answer_eval_count": 567,
            "answer_effective_output_tokens": 8192,
            "answer_done_reason": "stop",
            "answer_status": "ok",
            "answer_retry_count": 0,
        }
    )

    assert diagnostic == (
        "模型：gemma4:31b-cloud · 實際輸出 567／上限 8192 tokens · "
        "生成狀態：已完成"
    )


def test_build_answer_diagnostic_explains_output_limit_truncation():
    diagnostic = build_answer_diagnostic(
        {
            "answer_model": "gemma4:e2b",
            "answer_eval_count": 2048,
            "answer_effective_output_tokens": 2048,
            "answer_done_reason": "length",
            "answer_status": "incomplete",
            "answer_retry_count": 1,
        }
    )

    assert diagnostic == (
        "模型：gemma4:e2b · 實際輸出 2048／上限 2048 tokens · "
        "生成狀態：達到輸出上限，回答未完整 · 重試：1 次"
    )


def test_build_response_preserves_provenance_and_scores():
    response = build_response(
        "管理權人消防安全設備",
        [
            FakeHit(
                law_title="消防法",
                article_label="第13條",
                heading=None,
                content="管理權人應依規定設置消防安全設備。",
                source_url="https://law.nfa.gov.tw/test",
                version_no=2,
                vector_score=0.91,
                lexical_score=1.0,
                hybrid_score=0.94,
            )
        ],
    )

    assert response["results"][0]["law_title"] == "消防法"
    assert response["results"][0]["article_label"] == "第13條"
    assert response["results"][0]["version_no"] == 2
    assert response["results"][0]["source_url"].startswith("https://")
    assert response["results"][0]["hybrid_score"] == 0.94


def test_build_response_handles_empty_retrieval():
    response = build_response("不存在的查詢", [])

    assert response["results"] == []
    assert "沒有找到" in response["summary"]
    assert "gemma4:31b-cloud" in ANSWER_MODEL_OPTIONS


def test_linkify_citations_targets_matching_evidence_anchors():
    answer = "消防安全設備包含多種類別。[4][6]"

    linked = linkify_citations(answer, [4, 6], evidence_count=6)

    assert linked == (
        "消防安全設備包含多種類別。"
        '<a href="#evidence-4">[4]</a>'
        '<a href="#evidence-6">[6]</a>'
    )


def test_linkify_citations_leaves_unvalidated_numbers_untouched():
    answer = "依據[1]及[7]。"

    assert linkify_citations(answer, [1], evidence_count=2) == (
        '依據<a href="#evidence-1">[1]</a>及[7]。'
    )


def test_evidence_anchor_has_stable_id():
    assert evidence_anchor(4, "conversation-2-message-3") == (
        '<span id="conversation-2-message-3-4"></span>'
    )


def test_build_evidence_cards_opens_target_with_fragment_without_query_reload():
    local = {
        "law_title": "消防法",
        "article_label": "第3條",
        "heading": "",
        "content": "本法所稱主管機關。",
        "source_url": "https://law.nfa.gov.tw/test",
        "version_no": 1,
        "vector_score": 0.2,
        "lexical_score": 1.0,
        "hybrid_score": 0.76,
    }
    web = {
        "title": "官方補充",
        "retrieved_at": "2026-09-14T00:00:00+00:00",
        "content_preview": "官方內容",
        "url": "https://law.nfa.gov.tw/official",
    }

    cards = build_evidence_cards([local], [web], "conversation-2-message-3")

    assert 'id="conversation-2-message-3-1"' in cards
    assert 'id="conversation-2-message-3-2"' in cards
    assert "[1] 消防法" in cards
    assert "[2] 官方補充" in cards
    assert cards.index("[1] 消防法") < cards.index("[2] 官方補充")
    assert 'class="rag-evidence-group"' in cards
    assert "消防法（1 筆）" in cards
    assert 'class="rag-evidence-card"' in cards
    assert "?evidence=" not in cards
    assert "本法所稱主管機關。" in cards


def test_search_question_adds_answer_layer(monkeypatch):
    from app import streamlit_app

    hit = FakeHit(
        law_title="消防法",
        article_label="第13條",
        heading=None,
        content="管理權人應依規定設置消防安全設備。",
        source_url="https://law.nfa.gov.tw/test",
        version_no=2,
        vector_score=0.8,
        lexical_score=0.9,
        hybrid_score=0.86,
    )
    monkeypatch.setattr(streamlit_app, "build_response", lambda query, hits: {"results": []})
    monkeypatch.setattr(
        "app.rerank.retrieve_answer_hits", lambda query, top_k, law_title: [hit]
    )
    monkeypatch.setattr(
        "app.answer.answer_question",
        lambda query, hits, model: {
            "answer": f"整理後答案。[1]（{model}）",
            "answer_status": "ok",
            "answer_citations": [1],
        },
    )

    response = streamlit_app.search_question("問題", top_k=5, llm_model="gemma4:e2b")

    assert response["answer"] == "整理後答案。[1]（gemma4:e2b）"
    assert response["answer_status"] == "ok"
