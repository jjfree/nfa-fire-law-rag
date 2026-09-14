from dataclasses import dataclass

from app.streamlit_app import (
    ANSWER_MODEL_OPTIONS,
    _requested_evidence,
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
        '<a href="?evidence=evidence%3A4#evidence-4">[4]</a>'
        '<a href="?evidence=evidence%3A6#evidence-6">[6]</a>'
    )


def test_linkify_citations_leaves_unvalidated_numbers_untouched():
    answer = "依據[1]及[7]。"

    assert linkify_citations(answer, [1], evidence_count=2) == (
        '依據<a href="?evidence=evidence%3A1#evidence-1">[1]</a>及[7]。'
    )


def test_evidence_anchor_has_stable_id():
    assert evidence_anchor(4, "conversation-2-message-3") == (
        '<span id="conversation-2-message-3-4"></span>'
    )


def test_requested_evidence_reads_message_scoped_target():
    class FakeStreamlit:
        def __init__(self):
            self.query_params = {"evidence": "conversation-2-message-3:4"}

    assert _requested_evidence(FakeStreamlit()) == (
        "conversation-2-message-3",
        4,
    )


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
    monkeypatch.setattr("app.search.hybrid_search", lambda query, top_k, law_title: [hit])
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
