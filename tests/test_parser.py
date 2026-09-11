from pathlib import Path

from app.parser import parse_law_html, split_legal_text


def test_parse_article_structure():
    html = Path("tests/fixtures/law.html").read_text(encoding="utf-8")
    law = parse_law_html(html, "消防法")
    assert law.title == "消防法"
    assert len(law.chunks) == 2
    assert law.chunks[0].article_label == "第1條"
    assert "預防火災" in law.chunks[0].content
    assert law.metadata["authority"] == "內政部"


def test_split_points():
    chunks = split_legal_text("一、第一點內容\n補充說明\n二、第二點內容")
    assert len(chunks) == 2
    assert chunks[0].article_label == "一、"


def test_split_points_ignores_preamble():
    chunks = split_legal_text("發布日期：民國 115 年 1 月 1 日\n一、第一點\n二、第二點")
    assert [c.article_label for c in chunks] == ["一、", "二、"]
