from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.answer import AnswerResult, answer_question
from app.web_search import WebSearchResult, WebSearchUnavailable
from app.web_search_mode import parse_answer_request


@pytest.mark.parametrize(
    ("raw", "mode", "expected_query", "expected_mode"),
    [
        ("消防法第13條", "auto", "消防法第13條", "auto"),
        (" /web  消防法第13條 ", "auto", "消防法第13條", "force"),
        ("/WEB\n消防法第13條", "auto", "消防法第13條", "force"),
        ("消防法 /web 第13條", "auto", "消防法 /web 第13條", "auto"),
        ("/website 消防法", "auto", "/website 消防法", "auto"),
        ("消防法", "force", "消防法", "force"),
    ],
)
def test_parse_answer_request(raw, mode, expected_query, expected_mode):
    request = parse_answer_request(raw, mode)
    assert (request.query, request.web_mode) == (expected_query, expected_mode)


def test_parse_answer_request_rejects_empty_directive_and_invalid_mode():
    with pytest.raises(ValueError, match="/web 後輸入問題"):
        parse_answer_request(" /web ")
    with pytest.raises(ValueError, match="auto 或 force"):
        parse_answer_request("問題", "invalid")


def test_force_searches_high_scoring_structural_evidence_and_keeps_citations(monkeypatch):
    hit = SimpleNamespace(retrieval_mode="structural_section", hybrid_score=1.0)
    result = WebSearchResult("官方法規", "https://law.nfa.gov.tw/test", "內容", "2026-10-15")
    searched = []
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=True, web_search_provider="ollama"),
    )
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: searched.append(query) or [result],
    )
    monkeypatch.setattr(
        "app.answer._with_web_evidence",
        lambda query, hits, web_results, model: AnswerResult("官方說明。[2]", "ok", (2,)),
    )

    response = answer_question("消防法第13條", [hit], web_mode="force")

    assert searched == ["消防法第13條"]
    assert response["web_search_mode"] == "force"
    assert response["web_search_status"] == "used"
    assert response["answer_citations"] == [2]
    assert response["web_results"][0]["url"] == result.url


def test_auto_searches_central_authority_announcement_despite_high_local_score(monkeypatch):
    hit = SimpleNamespace(retrieval_mode="hybrid", hybrid_score=0.645)
    result = WebSearchResult(
        "內政部公告", "https://www.moi.gov.tw/News_Content.aspx?n=145&s=314010",
        "一定規模以上之建築物", "2026-10-15",
    )
    searched = []
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=True, web_search_provider="ollama"),
    )
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: searched.append(query) or [result],
    )
    monkeypatch.setattr(
        "app.answer._with_web_evidence",
        lambda query, hits, web_results, model: AnswerResult("內政部公告。[2]", "ok", (2,)),
    )

    response = answer_question("一定規模以上之建築物的中央主管機關公告?", [hit])

    assert searched == ["一定規模以上之建築物的中央主管機關公告?"]
    assert response["web_search_mode"] == "auto"
    assert response["web_search_status"] == "used"
    assert response["web_results"][0]["url"] == result.url


def test_auto_checks_latest_law_even_with_high_local_score(monkeypatch):
    searched = []
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=True, web_search_provider="ollama"),
    )
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: searched.append(query) or [],
    )
    monkeypatch.setattr(
        "app.answer.generate_answer",
        lambda query, hits, model=None: AnswerResult("本機條文。[1]", "ok", (1,)),
    )

    response = answer_question(
        "消防法最新修正條文",
        [SimpleNamespace(retrieval_mode="hybrid", hybrid_score=0.9)],
    )

    assert searched == ["消防法最新修正條文"]
    assert response["web_search_status"] == "no_results"


def test_auto_keeps_high_scoring_ordinary_law_question_local(monkeypatch):
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(
            web_search_enabled=True, web_search_provider="ollama",
            web_search_min_hybrid_score=0.35,
        ),
    )
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: pytest.fail("unexpected web search"),
    )
    monkeypatch.setattr(
        "app.answer.generate_answer",
        lambda query, hits, model=None: AnswerResult("本機條文。[1]", "ok", (1,)),
    )

    response = answer_question(
        "消防法第13條的規定為何？",
        [SimpleNamespace(retrieval_mode="hybrid", hybrid_score=0.645)],
    )

    assert response["web_search_status"] == "not_needed"


def test_auto_rechecks_insufficient_answer_before_returning(monkeypatch):
    hit = SimpleNamespace(retrieval_mode="hybrid", hybrid_score=0.9)
    official = WebSearchResult(
        "消防月刊測驗題與答案",
        "https://www.nfa.gov.tw/ebook/10408/files/basic-html/page21.html",
        "不同場所共同遴用一位防火管理人：Ｘ",
        "2026-10-16T00:00:00+00:00",
    )
    calls = []
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=True, web_search_provider="ollama",
                                web_search_min_hybrid_score=0.35),
    )
    monkeypatch.setattr(
        "app.answer.generate_answer",
        lambda query, hits, model=None: AnswerResult(
            "目前檢索到的法規資料不足以確認防火管理人是否可以被多個場所遴選。[1]",
            "ok", (1,),
        ),
    )
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: calls.append(("search", query)) or [official],
    )
    monkeypatch.setattr(
        "app.answer._with_web_evidence",
        lambda query, hits, web_results, model: (
            calls.append(("generate", web_results[0].url))
            or AnswerResult("官方資料顯示不可共同遴用。[2]", "ok", (2,))
        ),
    )

    response = answer_question("防火管理人是否可以被多個場所遴選?", [hit])

    assert calls == [
        ("search", "防火管理人是否可以被多個場所遴選?"),
        ("generate", official.url),
    ]
    assert response["answer"] == "官方資料顯示不可共同遴用。[2]"
    assert response["answer_citations"] == [2]
    assert response["web_search_status"] == "used"


@pytest.mark.parametrize(
    ("search_result", "expected_status"),
    [([], "no_results"), (WebSearchUnavailable("missing key"), "unavailable")],
)
def test_force_reports_no_web_evidence_without_losing_local_answer(
    monkeypatch, search_result, expected_status
):
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=True, web_search_provider="ollama"),
    )

    def fake_search(self, query):
        if isinstance(search_result, Exception):
            raise search_result
        return search_result

    monkeypatch.setattr("app.answer.OllamaWebSearchClient.search", fake_search)
    monkeypatch.setattr(
        "app.answer.generate_answer",
        lambda query, hits, model=None: AnswerResult("本機證據。[1]", "ok", (1,)),
    )
    hit = SimpleNamespace(retrieval_mode="structural_section", hybrid_score=1.0)

    response = answer_question("問題", [hit], web_mode="force")

    assert response["web_search_status"] == expected_status
    assert response["answer"] == "本機證據。[1]"


def test_force_does_not_override_disabled_server_setting(monkeypatch):
    monkeypatch.setattr(
        "app.answer.get_settings",
        lambda: SimpleNamespace(web_search_enabled=False, web_search_provider="ollama"),
    )
    monkeypatch.setattr(
        "app.answer.generate_answer",
        lambda query, hits, model=None: AnswerResult("本機證據。[1]", "ok", (1,)),
    )
    response = answer_question("問題", [object()], web_mode="force")
    assert response["web_search_status"] == "disabled"
    assert response["web_search_mode"] == "force"


def test_api_and_mcp_parse_directive_before_retrieval(monkeypatch):
    from app import api, mcp_server

    seen = []
    evidence = SimpleNamespace(hits=[], metadata=lambda: {"mode": "hybrid"})

    def fake_retrieve(query, top_k, law_title):
        seen.append((query, top_k, law_title))
        return evidence

    def fake_answer(query, hits, web_mode):
        seen.append((query, web_mode))
        return {"web_search_mode": web_mode, "web_search_status": "no_results"}

    monkeypatch.setattr(api, "retrieve_answer_evidence", fake_retrieve)
    monkeypatch.setattr(api, "answer_question", fake_answer)
    monkeypatch.setattr(mcp_server, "retrieve_answer_evidence", fake_retrieve)
    monkeypatch.setattr(mcp_server, "answer_question", fake_answer)

    api_response = api.api_ask("/web 消防法", 8, None, "auto")
    mcp_response = mcp_server.ask_fire_law("消防法", 8, None, "force")

    assert api_response["query"] == mcp_response["query"] == "消防法"
    assert seen == [
        ("消防法", 8, None),
        ("消防法", "force"),
        ("消防法", 8, None),
        ("消防法", "force"),
    ]
    with pytest.raises(HTTPException) as exc:
        api.api_ask("/web", 8, None, "auto")
    assert exc.value.status_code == 422


def test_streamlit_search_parses_directive_before_retrieval(monkeypatch):
    from app import answer, rerank, streamlit_app

    seen = []
    evidence = SimpleNamespace(hits=[], metadata=lambda: {"mode": "hybrid"})
    monkeypatch.setattr(
        rerank,
        "retrieve_answer_evidence",
        lambda query, top_k, law_title: seen.append(query) or evidence,
    )
    monkeypatch.setattr(
        answer,
        "answer_question",
        lambda query, hits, model, web_mode: seen.append((query, web_mode)) or {},
    )

    response = streamlit_app.search_question("/web 消防法", 8)

    assert response["query"] == "消防法"
    assert seen == ["消防法", ("消防法", "force")]


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        ("used", "已依 /web 指令搜尋"),
        ("no_results", "沒有找到"),
        ("unavailable", "尚未設定 OLLAMA_API_KEY"),
        ("error", "無法連線"),
        ("disabled", "系統已停用"),
    ],
)
def test_streamlit_force_caption_reports_actual_outcome(status, fragment):
    from app.streamlit_app import web_search_caption

    caption = web_search_caption(
        {"web_search_mode": "force", "web_search_status": status}
    )
    assert fragment in caption
    assert "RAG 證據不足" not in caption


def test_streamlit_auto_caption_does_not_assume_low_rag_score():
    from app.streamlit_app import web_search_caption

    caption = web_search_caption(
        {"web_search_mode": "auto", "web_search_status": "used"}
    )
    assert "已自動搜尋" in caption
    assert "RAG 證據不足" not in caption
