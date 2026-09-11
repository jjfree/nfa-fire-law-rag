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
