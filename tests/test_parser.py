from pathlib import Path

from app.parser import PARSER_REVISION, parse_law_html, parse_stored_law_text, split_legal_text


def test_parse_article_structure():
    html = Path("tests/fixtures/law.html").read_text(encoding="utf-8")
    law = parse_law_html(html, "消防法")
    assert law.title == "消防法"
    assert len(law.chunks) == 2
    assert law.chunks[0].article_label == "第1條"
    assert "預防火災" in law.chunks[0].content
    assert law.metadata["authority"] == "內政部"
    assert law.metadata["parser_revision"] == PARSER_REVISION


def test_split_points():
    chunks = split_legal_text("一、第一點內容\n補充說明\n二、第二點內容")
    assert len(chunks) == 2
    assert chunks[0].article_label == "一、"


def test_article_cross_reference_at_line_start_stays_in_current_article():
    chunks = split_legal_text(
        "第 9 條\n"
        "第六條第一項所定各類場所之管理權人，應定期檢修消防安全設備。\n"
        "第二項補充文字。\n"
        "第 10 條\n"
        "本條為下一條內容。"
    )

    assert [chunk.article_label for chunk in chunks] == ["第9條", "第10條"]
    assert "第六條第一項所定" in chunks[0].content
    assert chunks[0].content != "第9條"


def test_split_formal_points():
    chunks = split_legal_text("壹、第一點內容\n貳、第二點內容")
    assert [c.article_label for c in chunks] == ["壹、", "貳、"]


def test_split_points_ignores_preamble():
    chunks = split_legal_text("發布日期：民國 115 年 1 月 1 日\n一、第一點\n二、第二點")
    assert [c.article_label for c in chunks] == ["一、", "二、"]


def test_split_hierarchical_directions_preserves_parent_section_path():
    chunks = split_legal_text(
        "一、受理申報\n"
        "1.審核申報文件。\n"
        "二、複查工作\n"
        "（四）注意事項\n"
        "5.複查文件應保存歸檔。\n"
        "（五）其他事項\n"
        "5.特殊設施應由技術人員配合。"
    )

    assert [chunk.article_label for chunk in chunks] == ["1.", "5.", "5."]
    assert chunks[0].heading == "一、受理申報"
    assert chunks[1].heading == "二、複查工作 / （四）注意事項"
    assert chunks[2].heading == "二、複查工作 / （五）其他事項"
    assert "（五）其他事項" not in chunks[1].content


def test_reparse_stored_text_preserves_attachment_boundaries_and_updates_revision():
    raw_text = (
        "一、受理申報\n1.審核申報文件。\n\n"
        "附件：report.pdf\n第1條 附件條文。"
    )

    law = parse_stored_law_text(raw_text, "檢修申報規定", {"parser_revision": 1})

    assert law.metadata["parser_revision"] == PARSER_REVISION
    assert law.chunks[0].heading == "一、受理申報"
    assert law.chunks[1].heading == "附件：report.pdf"
    assert law.text == raw_text


def test_parse_realistic_legacy_print_view():
    html = Path("tests/fixtures/law_legacy_print.html").read_text(encoding="utf-8")
    law = parse_law_html(html, "fallback should not win")
    assert law.title == "液化石油氣零售業安全技術人員訓練專業機構登錄及管理辦法"
    assert law.metadata["published_date"] == "113/03/14"
    assert [c.article_label for c in law.chunks] == ["第1條", "第2條", "第3條"]
    assert law.chunks[0].heading == "第一章 總則"
    assert law.chunks[1].heading == "第一章 總則"
    assert law.chunks[2].heading == "第二章 申請程序"
    assert "列印時間" not in law.text
    assert "版權所有" not in law.chunks[-1].content


def test_print_timestamp_does_not_change_semantic_hash():
    html = Path("tests/fixtures/law_legacy_print.html").read_text(encoding="utf-8")
    changed = html.replace("115/09/11 09:12", "115/09/12 17:55")
    assert parse_law_html(html).content_hash == parse_law_html(changed).content_hash


def test_legacy_title_keeps_parentheses_inside_law_name():
    html = """
    <html><body><form id='form1'>
    法規名稱：各級消防機關（構）人員遴用標準（113/01/24 修正）
    第 1 條 本標準依相關規定訂定之。
    </form></body></html>
    """
    law = parse_law_html(html)
    assert law.title == "各級消防機關（構）人員遴用標準"
    assert law.metadata["amended_date"] == "113/01/24"
