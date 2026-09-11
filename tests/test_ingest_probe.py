from app.crawler.discovery import DiscoveredLawLink
from app.crawler.fetch import FetchedPage
from app.ingest import parse_link_without_db


class FakeFetcher:
    def fetch(self, url: str) -> FetchedPage:
        html = """
        <html><body><form id='form1'>
        法規名稱：消防法（112/06/21 修正）
        第 1 條 為預防火災、搶救災害及緊急救護，以維護公共安全，確保人民生命財產，特制定本法。
        第 2 條 本法所稱管理權人，係指依法令或契約對各該場所有實際支配管理權者。
        </form></body></html>
        """
        return FetchedPage(url=url, text=html, content_type="text/html", status_code=200)


def test_parse_link_without_db_prefers_print_view():
    link = DiscoveredLawLink(
        title="消防法",
        url="https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL005007",
        source_key="nfa:lsid:FL005007",
    )
    result = parse_link_without_db(link, FakeFetcher())
    assert result["title"] == "消防法"
    assert result["retrieved_url"].endswith("PrintFLAWDAT02.aspx?lsid=FL005007")
    assert result["chunks"] == 2
    assert result["first_article"] == "第1條"
