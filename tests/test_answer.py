from dataclasses import dataclass

import pytest

from app.answer import (
    AnswerGenerationError,
    answer_question,
    build_answer_prompt,
    build_evidence_context,
    generate_answer,
    validate_citations,
)
from app.web_search import WebSearchResult


@dataclass
class FakeHit:
    law_title: str
    article_label: str | None
    heading: str | None
    content: str
    source_url: str
    version_no: int
    hybrid_score: float = 0.0


def _hit(article: str = "第13條", hybrid_score: float = 0.0) -> FakeHit:
    return FakeHit(
        law_title="消防法",
        article_label=article,
        heading=None,
        content="管理權人應依規定設置消防安全設備並負責維護。",
        source_url="https://law.nfa.gov.tw/test",
        version_no=2,
        hybrid_score=hybrid_score,
    )


def test_evidence_context_keeps_stable_provenance_labels():
    context = build_evidence_context([_hit()])

    assert "[1] 法規名稱：消防法" in context
    assert "條號：第13條" in context
    assert "版本：2" in context
    assert "https://law.nfa.gov.tw/test" in context


def test_prompt_requires_evidence_only_citations():
    prompt = build_answer_prompt("消防設備人員包含哪些？", build_evidence_context([_hit()]))

    assert "只能依據 <evidence>" in prompt
    assert "每一個重要法律主張句末都必須附上證據編號" in prompt


def test_validate_citations_rejects_missing_or_unknown_references():
    assert validate_citations("答案內容。[1]", 1) == (1,)
    with pytest.raises(AnswerGenerationError):
        validate_citations("答案內容。", 1)
    with pytest.raises(AnswerGenerationError):
        validate_citations("答案內容。[2]", 1)


def test_generate_answer_uses_local_answerer_and_returns_citations(monkeypatch):
    class FakeSettings:
        llm_provider = "ollama"
        llm_base_url = "http://127.0.0.1:11434"
        llm_model = "gemma4:e4b"
        llm_timeout_seconds = 180.0
        llm_temperature = 0.1
        llm_think = False
        llm_max_output_tokens = 512

    monkeypatch.setattr("app.answer.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "app.answer.OllamaAnswerer.complete",
        lambda self, prompt: "管理權人應設置並維護消防安全設備。[1]",
    )

    result = generate_answer("消防設備人員包含哪些？", [_hit()])

    assert result.status == "ok"
    assert result.citations == (1,)
    assert "消防安全設備" in result.answer


def test_generate_answer_accepts_per_request_model_override(monkeypatch):
    class FakeSettings:
        llm_provider = "ollama"
        llm_base_url = "http://127.0.0.1:11434"
        llm_model = "gemma4:e4b"
        llm_timeout_seconds = 180.0
        llm_temperature = 0.1
        llm_think = False
        llm_max_output_tokens = 512
        llm_cloud_base_url = "https://ollama.com"

    captured = {}
    monkeypatch.setattr("app.answer.get_settings", lambda: FakeSettings())

    def fake_complete(self, prompt):
        captured["model"] = self.model
        return "快速回答。[1]"

    monkeypatch.setattr("app.answer.OllamaAnswerer.complete", fake_complete)

    result = generate_answer("問題", [_hit()], model="gemma4:e2b")

    assert result.status == "ok"
    assert captured["model"] == "gemma4:e2b"


def test_generate_answer_does_not_expose_uncited_model_output(monkeypatch):
    class FakeSettings:
        llm_provider = "ollama"
        llm_base_url = "http://127.0.0.1:11434"
        llm_model = "gemma4:e4b"
        llm_timeout_seconds = 180.0
        llm_temperature = 0.1
        llm_think = False
        llm_max_output_tokens = 512
        llm_cloud_base_url = "https://ollama.com"

    monkeypatch.setattr("app.answer.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.answer.OllamaAnswerer.complete", lambda self, prompt: "沒有引用的答案")

    result = generate_answer("問題", [_hit()])

    assert result.status == "llm_error"
    assert result.answer != "沒有引用的答案"
    assert result.error is not None


def test_generate_answer_handles_no_evidence_without_calling_llm():
    result = generate_answer("不存在的查詢", [])

    assert result.status == "no_evidence"
    assert result.citations == ()


def test_answer_question_uses_official_web_evidence_when_rag_score_is_low(monkeypatch):
    class FakeSettings:
        llm_provider = "ollama"
        llm_base_url = "http://127.0.0.1:11434"
        llm_model = "gemma4:e4b"
        llm_timeout_seconds = 180.0
        llm_temperature = 0.1
        llm_think = False
        llm_max_output_tokens = 512
        llm_cloud_base_url = "https://ollama.com"
        web_search_enabled = True
        web_search_provider = "ollama"
        ollama_api_key = "test-key"
        web_search_api_url = "https://ollama.com/api/web_search"
        web_fetch_api_url = "https://ollama.com/api/web_fetch"
        web_search_timeout_seconds = 30.0
        web_search_max_results = 5
        web_search_max_fetch_results = 3
        web_search_min_hybrid_score = 0.30
        web_search_allowed_domains = "law.nfa.gov.tw,web.law.ntpc.gov.tw,laws.gov.taipei"

    captured = {}
    monkeypatch.setattr("app.answer.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.web_search.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: [
            WebSearchResult(
                title="消防法規官方資料",
                url="https://law.nfa.gov.tw/official",
                content="官方補充內容。",
                retrieved_at="2026-09-14T00:00:00+00:00",
            )
        ],
    )

    def fake_complete(self, prompt):
        captured["prompt"] = prompt
        captured["model"] = self.model
        return "依官方補充資料回答。[2]"

    monkeypatch.setattr("app.answer.OllamaAnswerer.complete", fake_complete)

    response = answer_question("問題", [_hit(hybrid_score=0.1)], model="gemma4:e2b")

    assert response["answer_status"] == "ok"
    assert response["answer_citations"] == [2]
    assert response["web_search_status"] == "used"
    assert response["web_results"][0]["url"] == "https://law.nfa.gov.tw/official"
    assert "官方網頁補充資料" in captured["prompt"]
    assert captured["model"] == "gemma4:e2b"


def test_cloud_model_uses_cloud_endpoint_and_api_key(monkeypatch):
    class FakeSettings:
        llm_provider = "ollama"
        llm_base_url = "http://127.0.0.1:11434"
        llm_cloud_base_url = "https://ollama.com"
        llm_model = "gemma4:e4b"
        llm_timeout_seconds = 180.0
        llm_temperature = 0.1
        llm_think = False
        llm_max_output_tokens = 512
        ollama_api_key = "test-key"
        web_search_enabled = True
        web_search_provider = "ollama"
        web_search_api_url = "https://ollama.com/api/web_search"
        web_fetch_api_url = "https://ollama.com/api/web_fetch"
        web_search_timeout_seconds = 30.0
        web_search_max_results = 5
        web_search_max_fetch_results = 3
        web_search_min_hybrid_score = 0.30
        web_search_allowed_domains = "law.nfa.gov.tw"

    captured = {}
    monkeypatch.setattr("app.answer.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.web_search.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "app.answer.OllamaWebSearchClient.search",
        lambda self, query: [
            WebSearchResult(
                title="官方法規",
                url="https://law.nfa.gov.tw/official",
                content="官方資料。",
                retrieved_at="2026-09-14T00:00:00+00:00",
            )
        ],
    )

    def fake_complete(self, prompt):
        captured["base_url"] = self.base_url
        captured["model"] = self.model
        captured["api_key"] = self.api_key
        return "雲端回答。[1]"

    monkeypatch.setattr("app.answer.OllamaAnswerer.complete", fake_complete)

    result = answer_question("問題", [], model="gemma4:31b-cloud")

    assert result["answer_status"] == "ok"
    assert result["answer_citations"] == [1]
    assert result["web_search_status"] == "used"
    assert captured == {
        "base_url": "https://ollama.com",
        "model": "gemma4:31b-cloud",
        "api_key": "test-key",
    }
