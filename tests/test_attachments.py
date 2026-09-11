import sys
from types import SimpleNamespace

import pytest

from app.attachments import PdfTooManyPagesError, discover_attachment_urls, extract_pdf_text
from app.crawler.discovery import DiscoveredLawLink
from app.crawler.fetch import FetchedPage
from app.ingest import _ingest_attachments
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


def test_extract_pdf_text_rejects_too_many_pages(monkeypatch):
    class FakeReader:
        def __init__(self, stream):
            self.pages = [object(), object(), object()]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))
    with pytest.raises(PdfTooManyPagesError, match="more than 2 pages"):
        extract_pdf_text(b"not-a-real-pdf", max_pages=2)


def test_attachment_report_lists_skipped_files(monkeypatch):
    class FakeFetcher:
        def fetch_bytes(self, url):
            return "application/pdf", b"pdf"

    def reject_pdf(content, max_pages):
        raise PdfTooManyPagesError(f"PDF has more than {max_pages} pages")

    monkeypatch.setattr("app.ingest.extract_pdf_text", reject_pdf)
    parsed = ParsedLaw(title="消防法", text="第1條 原本文字", metadata={}, content_hash="old", chunks=[])
    page = FetchedPage(
        url="https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL102597",
        text='<a href="/downloadFile.ashx?FileId=13720">附件 PDF</a>',
        content_type="text/html",
        status_code=200,
    )
    link = DiscoveredLawLink(
        title="消防法",
        url=page.url,
        source_key="nfa:lsid:FL102597",
    )
    report = _ingest_attachments(parsed, page, link, FakeFetcher())
    assert report["parsed"] == 0
    assert report["skipped"] == [
        {
            "url": "https://law.nfa.gov.tw/downloadFile.ashx?FileId=13720",
            "reason": "PDF has more than 200 pages",
        }
    ]
