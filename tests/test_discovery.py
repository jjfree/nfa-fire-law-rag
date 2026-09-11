from pathlib import Path

from app.crawler.discovery import discover_law_links

BASE_URL = "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002"


def test_discover_links():
    html = Path("tests/fixtures/category.html").read_text(encoding="utf-8")
    links = discover_law_links(html, BASE_URL)
    assert len(links) == 2
    assert links[0].title == "消防法"
    assert links[0].url == "https://law.nfa.gov.tw/MOBILE/law.aspx?id=101"


def test_legacy_lsid_links_are_deduplicated_across_ldate():
    html = Path("tests/fixtures/category_legacy.html").read_text(encoding="utf-8")
    links = discover_law_links(html, BASE_URL)
    assert len(links) == 2
    assert links[0].source_key == "nfa:lsid:FL005059"
    assert links[1].source_key == "nfa:lsid:FL005066"


def test_discovery_excludes_navigation_and_category_pages():
    html = """
    <a href="/MOBILE/news.aspx?type=all">最新法規消息</a>
    <a href="/MOBILE/category.aspx?typecode=A001">法規分類</a>
    <a href="/MOBILE/law.aspx?LSID=FL102597">消防安全設備標準</a>
    """
    links = discover_law_links(html, BASE_URL)
    assert [link.url for link in links] == ["https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL102597"]


def test_discovery_excludes_retired_laws():
    html = """
    <a href="/MOBILE/law.aspx?LSID=FL098213">廢防災中心服勤人員訓練專業機構申請登錄收費標準 (114/02/19)</a>
    <a href="/MOBILE/law.aspx?LSID=FL102597">消防設備人員懲戒委員會與懲戒覆審委員會組織及審議規則</a>
    """
    links = discover_law_links(html, BASE_URL)
    assert [link.source_key for link in links] == ["nfa:lsid:FL102597"]
