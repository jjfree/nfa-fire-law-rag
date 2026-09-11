import httpx
import pytest

from app.crawler.fetch import CrawlBlockedError, HttpFetcher


def test_fetch_stops_on_waf_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"}, request=request)

    fetcher = HttpFetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CrawlBlockedError, match="Retry-After=60"):
        fetcher.fetch("https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL102597")
    fetcher.close()


def test_fetch_streams_and_rejects_oversized_attachment():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": "5"},
            content=b"12345",
            request=request,
        )

    fetcher = HttpFetcher()
    fetcher.settings.max_attachment_bytes = 4
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="exceeds 4 bytes"):
        fetcher.fetch_bytes("https://law.nfa.gov.tw/downloadFile.ashx?FileId=13720")
    fetcher.close()
