import json
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.nfa_interpretation import (
    InterpretationImportError,
    fetch_one_page,
    import_interpretation,
    parse_interpretation,
    validate_url,
)

URL = (
    "https://law.nfa.gov.tw/GNFA/FINT/FINTQRY04.aspx?pg=7&"
    "EID=D01201%2c%E5%85%A7%E6%8E%88%E6%B6%88%2c1000824302%2c20110718"
)
HTML = """<html><body><table>
<tr><th>發文字號</th><td>內授消字第1000824302號</td></tr>
<tr><th>發文日期</th><td>100年7月18日</td></tr>
<tr><th>主旨</th><td>測試用：防火管理人與不同場所的索引文字，此段不是實際函釋內容。</td></tr>
<tr><th>說明</th><td>測試用：這裡放入足夠長的範例字串，僅用來確認單頁擷取、內容雜湊、版本更新與索引重建。
這些字串不代表主管機關的任何法律見解，也不得作為回答使用者問題的法源。</td></tr>
</table></body></html>"""


@pytest.fixture()
def isolated_db(monkeypatch):
    import app.db as db_module
    from app import models as _models  # noqa: F401
    from app.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("""CREATE VIRTUAL TABLE law_chunks_fts USING fts5(
            content, article_label, heading, law_title,
            chunk_id UNINDEXED, law_id UNINDEXED, version_id UNINDEXED
        )"""))
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session = local_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_module, "session_scope", session_scope)
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    import app.search as search_module

    monkeypatch.setattr(search_module, "session_scope", session_scope)
    yield session_scope
    engine.dispose()


def test_url_requires_exact_official_detail_and_eid():
    eid, number = validate_url(URL)
    assert number == "1000824302"
    assert eid == "D01201,內授消,1000824302,20110718"
    with pytest.raises(InterpretationImportError):
        validate_url("https://example.com/GNFA/FINT/FINTQRY04.aspx?EID=" + eid)
    with pytest.raises(InterpretationImportError):
        validate_url("https://law.nfa.gov.tw/GNFA/FINT/FINTQRY03.aspx?EID=" + eid)
    with pytest.raises(InterpretationImportError):
        validate_url(URL.replace("law.nfa.gov.tw", "law.nfa.gov.tw:bad"))


def test_parser_rejects_nonmatching_or_empty_page():
    eid, number = validate_url(URL)
    parsed = parse_interpretation(HTML, eid, number)
    assert parsed.metadata["發文日期"] == "100年7月18日"
    assert "不同場所" in parsed.text
    with pytest.raises(InterpretationImportError):
        parse_interpretation(HTML.replace(number, "9999999999"), eid, number)
    with pytest.raises(InterpretationImportError):
        parse_interpretation(f"<html>{number}</html>", eid, number)


def test_fetch_uses_one_request_and_stops_on_redirect_or_block(monkeypatch):
    original_client = httpx.Client
    requests = []
    status = 200

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(
                status,
                headers={"content-type": "text/html; charset=utf-8", "location": "https://example.com/"},
                text=HTML,
            )

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    html, retrieved = fetch_one_page(URL)
    assert "1000824302" in html and retrieved == URL
    assert requests == [URL]
    for status in (302, 403, 429):
        requests.clear()
        with pytest.raises(InterpretationImportError):
            fetch_one_page(URL)
        assert requests == [URL]


def test_single_import_versions_current_and_indexes_only_requested_page(isolated_db):
    from app.models import Law, LawChunk, LawVersion

    preview = import_interpretation(URL, html=HTML, apply=False)
    assert preview["status"] == "preview"
    with isolated_db() as db:
        assert db.scalar(select(Law)) is None

    inserted = import_interpretation(URL, html=HTML)
    assert inserted["status"] == "inserted"
    assert inserted["chunks"] == 2
    assert import_interpretation(URL, html=HTML)["status"] == "unchanged"
    changed = HTML.replace("索引重建", "檢索驗證")
    updated = import_interpretation(URL, html=changed)
    assert updated["version"] == 2
    with isolated_db() as db:
        laws = db.scalars(select(Law)).all()
        assert len(laws) == 1
        assert laws[0].category == "消防署函釋"
        assert laws[0].source_url == URL
        versions = db.scalars(select(LawVersion).order_by(LawVersion.version_no)).all()
        assert [v.is_current for v in versions] == [False, True]
        chunks = db.scalars(select(LawChunk).where(LawChunk.version_id == versions[1].id)).all()
        assert all(len(chunk.embedding) == 384 * 4 for chunk in chunks)
        fts_versions = db.execute(text("SELECT DISTINCT version_id FROM law_chunks_fts")).scalars().all()
        assert fts_versions == [versions[1].id]

    from app.answer import build_evidence_context
    from app.search import hybrid_search

    hits = hybrid_search("防火管理人不同場所", top_k=2)
    assert hits and hits[0].source_type == "nfa_interpretation"
    assert "來源類型：消防署函釋" in build_evidence_context(hits)


def test_offline_pdf_import_links_indexed_page_and_preserves_official_url(
    isolated_db, monkeypatch, tmp_path
):
    import app.nfa_interpretation_pdf as pdf_module
    from app.config import get_settings
    from app.models import Law, LawVersion
    from app.search import hybrid_search
    from app.streamlit_app import build_evidence_cards, build_response

    source = tmp_path / "official.pdf"
    source.write_bytes(b"%PDF-test-content")
    monkeypatch.setattr(pdf_module, "get_settings", lambda: get_settings().model_copy(update={"max_attachment_bytes": 25_000_000}))
    page_text = "測試用：防火管理人與不同場所的函釋索引文字，這不是正式函釋內容。" * 4
    monkeypatch.setattr(
        pdf_module,
        "_extract_pages",
        lambda _content, _number, _eid: ([page_text], {"發文日期": "100/07/18", "發文機關": "內政部消防署"}),
    )
    storage = tmp_path / "stored"
    public = tmp_path / "public"
    preview = pdf_module.import_interpretation_pdf(
        source, URL, apply=False, storage_dir=storage, public_dir=public
    )
    assert preview["status"] == "preview"
    assert not storage.exists() and not public.exists()

    inserted = pdf_module.import_interpretation_pdf(
        source, URL, storage_dir=storage, public_dir=public
    )
    assert inserted["status"] == "inserted"
    assert inserted["local_pdf_url"].endswith("#page=1")
    next(public.glob("*.pdf")).unlink()
    assert pdf_module.import_interpretation_pdf(
        source, URL, storage_dir=storage, public_dir=public
    )["status"] == "unchanged"
    assert len(list(storage.glob("*.pdf"))) == 1
    assert len(list(public.glob("*.pdf"))) == 1

    with isolated_db() as db:
        law = db.scalar(select(Law))
        version = db.scalar(select(LawVersion))
        assert law.source_url == URL
        assert version.is_current
        assert json.loads(version.metadata_json)["source_format"] == "user_supplied_pdf"
    hits = hybrid_search("防火管理人不同場所", top_k=2)
    assert hits and hits[0].local_pdf_url == inserted["local_pdf_url"]
    response = build_response("防火管理人不同場所", hits)
    card = build_evidence_cards(response["results"], [])
    assert "開啟本機 PDF（第1頁）" in card
    assert "消防署原始網址" in card
    assert inserted["local_pdf_url"] in card


def test_pdf_public_url_rejects_untrusted_metadata():
    from app.nfa_interpretation_pdf import pdf_public_url

    assert pdf_public_url('[]', "第1頁") is None
    assert pdf_public_url('{"local_pdf_name":"' + "a" * 64 + '.pdf","pdf_page_count":"bad"}', "第1頁") is None
    assert pdf_public_url('{"local_pdf_name":"../secret.pdf","pdf_page_count":1}', "第1頁") is None
    assert pdf_public_url('{"local_pdf_name":"' + "a" * 64 + '.pdf","pdf_page_count":1}', "第2頁") is None


def test_multiple_premises_query_adds_interpretation_vocabulary():
    from app.query_analysis import expand_regulatory_query

    expanded = expand_regulatory_query("防火管理人是否可以被多個場所遴選?")
    assert "不同場所 兼任" in expanded
    assert expand_regulatory_query("多個場所的消防設備檢修") == "多個場所的消防設備檢修"
