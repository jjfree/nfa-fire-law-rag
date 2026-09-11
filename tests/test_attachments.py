from app.attachments import discover_attachment_urls
from app.parser import ParsedLaw, append_attachment_text


def test_discover_attachment_urls_excludes_navigation_and_external_hosts():
    html = """
    <a href="/MOBILE/category.aspx?typecode=A001">法規分類</a>
    <a href="/downloadFile.ashx?FileId=13720">附件 PDF</a>
    <a href="https://example.com/evidence.pdf">外部附件</a>
    """
    assert discover_attachment_urls(
        html,
        "https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL102597",
        "law.nfa.gov.tw",
    ) == ["https://law.nfa.gov.tw/downloadFile.ashx?FileId=13720"]


def test_append_attachment_text_creates_searchable_chunks_and_updates_hash():
    parsed = ParsedLaw(
        title="消防法",
        text="第1條 原本文字",
        metadata={},
        content_hash="old",
        chunks=[],
    )
    append_attachment_text(parsed, "附件內容：管理權人應維護設備。", "evidence.pdf")
    assert parsed.chunks[0].article_label == "附件1"
    assert parsed.chunks[0].heading == "附件：evidence.pdf"
    assert "附件內容" in parsed.text
    assert parsed.content_hash != "old"
