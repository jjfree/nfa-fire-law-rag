import httpx
import pytest

from app.config import Settings
from app.web_search import (
    OllamaWebSearchClient,
    WebSearchError,
    WebSearchResult,
    WebSearchUnavailable,
    filter_relevant_web_results,
    is_allowed_web_url,
    official_source_date,
)


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


def test_default_allowlist_keeps_ministry_announcement_from_forced_search(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_ALLOWED_DOMAINS", raising=False)
    settings = Settings(_env_file=None, ollama_api_key="test-key")
    assert "moi.gov.tw" in settings.web_search_allowed_domains.split(",")
    monkeypatch.setattr("app.web_search.get_settings", lambda: settings)

    def fake_post(url, *, json, headers, timeout):
        request = httpx.Request("POST", url)
        if url.endswith("web_search"):
            if json["query"] != "一定規模以上之建築物的中央主管機關公告?":
                assert json["query"] == (
                    "消防法第十三條第一項一定規模以上之建築物 內政部 修正 最新 site:moi.gov.tw"
                )
                return httpx.Response(
                    200,
                    json={"results": [
                        {
                            "title": "修正「消防法第十三條第一項一定規模以上之建築物」",
                            "url": "https://www.moi.gov.tw/News_Content.aspx?n=145&s=331840",
                            "content": "修正公告",
                        },
                        {
                            "title": "訂定「消防法第十三條第一項一定規模以上之建築物」",
                            "url": "https://www.moi.gov.tw/News_Content.aspx?n=145&s=314010",
                            "content": "原公告",
                        },
                    ]},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "訂定「消防法第十三條第一項一定規模以上之建築物」",
                            "url": "https://www.moi.gov.tw/News_Content.aspx?n=145&s=314010",
                            "content": "消防法第十三條公告",
                        },
                        {
                            "title": "民間轉載",
                            "url": "https://www.rootlaw.com.tw/LetterContent.aspx",
                            "content": "轉載",
                        },
                    ]
                },
                request=request,
            )
        if json["url"].endswith("s=331840"):
            return httpx.Response(
                200,
                json={"title": "修正公告", "content": (
                    "法規命令發布(法規公發布)日：114-09-16\n"
                    "修正一定規模以上之建築物，自115年1月1日生效。"
                )},
                request=request,
            )
        return httpx.Response(
            200,
            json={"title": "訂定公告", "content": (
                "法規命令發布(法規公發布)日：113-03-07\n"
                "一定規模以上之建築物應訂定消防防護計畫。"
            )},
            request=request,
        )

    monkeypatch.setattr("app.web_search.httpx.post", fake_post)
    results = OllamaWebSearchClient().search("一定規模以上之建築物的中央主管機關公告?")

    assert len(results) == 2
    assert results[0].url.endswith("s=331840")
    assert results[0].source_date == "2025-09-16"
    assert results[0].source_date_label == "法規命令發布(法規公發布)日"
    assert results[1].source_date == "2024-03-07"
    assert "一定規模以上之建築物" in results[0].content


def test_official_source_date_distinguishes_amendment_from_effective_date():
    assert official_source_date(
        "修正日期： | 民國 113 年 11 月 29 日\n自115年1月1日施行"
    ) == ("2024-11-29", "修正日期")
    assert official_source_date("自115年1月1日生效") == (None, None)


def test_precision_search_failure_keeps_initial_official_result(monkeypatch):
    client = OllamaWebSearchClient()
    calls = []

    def fake_post(url, payload):
        calls.append(payload)
        if "query" in payload and len(calls) == 1:
            return {"results": [{
                "title": "訂定「消防法第十三條第一項一定規模以上之建築物」",
                "url": "https://www.moi.gov.tw/News_Content.aspx?n=145&s=314010",
                "content": "原公告",
            }]}
        if "query" in payload:
            raise WebSearchError("temporary failure")
        return {"content": "法規命令發布日：113-03-07 原公告"}

    monkeypatch.setattr(client, "_post_json", fake_post)
    results = client.search("一定規模以上之建築物的中央主管機關公告?")

    assert len(results) == 1
    assert results[0].source_date == "2024-03-07"
    assert len([payload for payload in calls if "query" in payload]) == 2


def test_latest_law_search_prefers_current_full_text(monkeypatch):
    client = OllamaWebSearchClient()
    queries = []

    def fake_post(url, payload):
        if "query" in payload:
            queries.append(payload["query"])
            if len(queries) == 1:
                return {"results": []}
            return {"results": [{
                "title": "消防法-全國法規資料庫",
                "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=D0120001",
                "content": "消防法",
            }]}
        return {"content": "修正日期：民國 113 年 11 月 29 日\n消防法現行條文"}

    monkeypatch.setattr(client, "_post_json", fake_post)
    results = client.search("消防法最新修正條文")

    assert len(queries) == 2
    assert queries[1].startswith("site:law.moj.gov.tw/LawClass/LawAll.aspx")
    assert results[0].source_date == "2024-11-29"


def test_historical_year_query_skips_latest_version_followup(monkeypatch):
    client = OllamaWebSearchClient()
    queries = []

    def fake_post(url, payload):
        if "query" in payload:
            queries.append(payload["query"])
            return {"results": [{
                "title": "113年主管機關公告",
                "url": "https://www.moi.gov.tw/News_Content.aspx?n=145&s=314010",
                "content": "原公告",
            }]}
        return {"content": "公告日期：113-03-07"}

    monkeypatch.setattr(client, "_post_json", fake_post)
    results = client.search("請找113年中央主管機關公告")

    assert len(queries) == 1
    assert results[0].source_date == "2024-03-07"


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


def test_web_relevance_filter_rejects_results_missing_inclusion_target():
    relevant = WebSearchResult(
        "各類場所消防安全設備設置標準",
        "https://law.nfa.gov.tw/relevant",
        "乙類場所包括寺廟、宗祠及教堂。",
        "2026-09-15T00:00:00+00:00",
    )
    unrelated = WebSearchResult(
        "相關法條",
        "https://law.nfa.gov.tw/unrelated",
        "消防法第十三條規定防火管理人相關事項。",
        "2026-09-15T00:00:00+00:00",
    )

    results = filter_relevant_web_results(
        "請說明消防列管場所包含哪些？是否包含寺廟？",
        [unrelated, relevant],
    )

    assert results == [relevant]
