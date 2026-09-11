from pathlib import Path

from app.crawler.discovery import discover_law_links


def test_discover_links():
    html = Path("tests/fixtures/category.html").read_text(encoding="utf-8")
    links = discover_law_links(html, "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002")
    assert len(links) == 2
    assert links[0].title == "消防法"
    assert links[0].url == "https://law.nfa.gov.tw/MOBILE/law.aspx?id=101"
