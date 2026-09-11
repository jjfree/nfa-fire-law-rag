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
