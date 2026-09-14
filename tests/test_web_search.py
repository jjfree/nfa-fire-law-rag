import httpx
import pytest

from app.web_search import OllamaWebSearchClient, WebSearchUnavailable, is_allowed_web_url


def test_allowed_web_url_requires_https_and_configured_domain():
    domains = ("law.nfa.gov.tw", "nfa.gov.tw")

    assert is_allowed_web_url("https://law.nfa.gov.tw/article", domains)
    assert is_allowed_web_url("https://sub.nfa.gov.tw/article", domains)
    assert not is_allowed_web_url("http://law.nfa.gov.tw/article", domains)
    assert not is_allowed_web_url("https://example.com/article", domains)
    assert not is_allowed_web_url("https://law.nfa.gov.tw.evil.example/article", domains)
    assert not is_allowed_web_url("https://user:pass@law.nfa.gov.tw/article", domains)


def test_ollama_web_search_filters_and_fetches_official_results(monkeypatch):
    class FakeSettings:
        ollama_api_key = "test-key"
        web_search_api_url = "https://ollama.com/api/web_search"
        web_fetch_api_url = "https://ollama.com/api/web_fetch"
        web_search_timeout_seconds = 30.0
        web_search_max_results = 5
        web_search_max_fetch_results = 3
        web_search_allowed_domains = "law.nfa.gov.tw"

    monkeypatch.setattr("app.web_search.get_settings", lambda: FakeSettings())

    def fake_post(url, *, json, headers, timeout):
        request = httpx.Request("POST", url)
        if url.endswith("web_search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "官方法規",
                            "url": "https://law.nfa.gov.tw/article",
                            "content": "搜尋摘要",
                        },
                        {
                            "title": "不在允許清單",
                            "url": "https://example.com/article",
                            "content": "不應送入模型",
                        },
                    ]
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"title": "官方法規全文", "content": "擷取到的正式頁面內容"},
            request=request,
        )

    monkeypatch.setattr("app.web_search.httpx.post", fake_post)

    results = OllamaWebSearchClient().search("消防設備人員")

    assert len(results) == 1
    assert results[0].title == "官方法規全文"
    assert results[0].url == "https://law.nfa.gov.tw/article"
    assert results[0].content == "擷取到的正式頁面內容"
    assert results[0].retrieved_at


def test_ollama_web_search_requires_api_key(monkeypatch):
    class FakeSettings:
        ollama_api_key = ""
        web_search_api_url = "https://ollama.com/api/web_search"
        web_fetch_api_url = "https://ollama.com/api/web_fetch"
        web_search_timeout_seconds = 30.0
        web_search_max_results = 5
        web_search_max_fetch_results = 3
        web_search_allowed_domains = "law.nfa.gov.tw"

    monkeypatch.setattr("app.web_search.get_settings", lambda: FakeSettings())

    with pytest.raises(WebSearchUnavailable):
        OllamaWebSearchClient().search("消防設備人員")
