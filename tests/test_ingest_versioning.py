import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.crawler.discovery import DiscoveredLawLink
from app.crawler.fetch import FetchedPage
from app.ingest import ingest_link, reprocess_current_laws
from app.parser import PARSER_REVISION, metadata_json, parse_law_html


class FakeFetcher:
    def __init__(self, html: str):
        self.html = html

    def fetch(self, url: str) -> FetchedPage:
        return FetchedPage(url=url, text=self.html, content_type="text/html", status_code=200)

    def fetch_bytes(self, url: str):  # pragma: no cover - fixtures contain no attachments
        raise AssertionError(f"Unexpected attachment fetch: {url}")


def _html(body: str) -> str:
    return f"<html><body><form id='form1'>法規名稱：測試法規\n{body}</form></body></html>"


@pytest.fixture()
def isolated_ingest_db(monkeypatch):
    import app.db as db_module
    from app import models as _models  # noqa: F401 - register ORM metadata
    from app.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIRTUAL TABLE law_chunks_fts USING fts5(
                    content, article_label, heading, law_title,
                    chunk_id UNINDEXED, law_id UNINDEXED, version_id UNINDEXED
                )
                """
            )
        )
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
    yield session_scope
    engine.dispose()


def _seed_version(
    session_scope,
    html: str,
    *,
    version_no: int = 1,
    is_current: bool = True,
    parser_revision: int | None = PARSER_REVISION,
):
    from app.models import Law, LawChunk, LawVersion

    parsed = parse_law_html(html, "測試法規")
    metadata = dict(parsed.metadata)
    metadata["attachments"] = {"discovered": 0, "parsed": 0, "skipped": [], "errors": []}
    if parser_revision is None:
        metadata.pop("parser_revision", None)
    else:
        metadata["parser_revision"] = parser_revision
    with session_scope() as db:
        law = db.scalar(select(Law).where(Law.source_key == "test:law"))
        if law is None:
            law = Law(
                source_key="test:law",
                title=parsed.title,
                source_url="https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=TEST",
            )
            db.add(law)
            db.flush()
        version = LawVersion(
            law_id=law.id,
            version_no=version_no,
            content_hash=parsed.content_hash,
            raw_text=parsed.text,
            metadata_json=metadata_json(metadata),
            is_current=is_current,
        )
        db.add(version)
        db.flush()
        for chunk in parsed.chunks:
            db.add(
                LawChunk(
                    version_id=version.id,
                    seq=chunk.seq,
                    article_label=chunk.article_label,
                    heading=chunk.heading,
                    content=chunk.content,
                    embedding=b"\x00" * 16,
                )
            )
        return law.id, version.id, parsed


def _link() -> DiscoveredLawLink:
    return DiscoveredLawLink(
        title="測試法規",
        url="https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=TEST",
        source_key="test:law",
    )


def test_unchanged_requires_current_parser_revision(isolated_ingest_db):
    html = _html("第1條 本法用於測試目前解析版本且文字長度足夠。")
    _seed_version(isolated_ingest_db, html)

    result = ingest_link(_link(), FakeFetcher(html))

    assert result["status"] == "unchanged"


def test_old_parser_revision_reports_reprocess_required(isolated_ingest_db):
    html = _html("第1條 本法用於測試舊解析版本且文字長度足夠。")
    law_id, _, _ = _seed_version(isolated_ingest_db, html, parser_revision=1)

    result = ingest_link(_link(), FakeFetcher(html))

    assert result == {
        "status": "reprocess_required",
        "law_id": law_id,
        "title": "測試法規",
        "version": 1,
        "stored_parser_revision": 1,
        "required_parser_revision": PARSER_REVISION,
        "retrieved_url": "https://law.nfa.gov.tw/GNFA/FLAW/PrintFLAWDAT02.aspx?lsid=TEST",
        "fallback_failures": [],
    }


def test_source_change_creates_new_version_and_preserves_old(isolated_ingest_db):
    from app.models import LawVersion

    old_html = _html("第1條 這是修正前法規內容而且文字長度足夠。")
    new_html = _html("第1條 這是修正後法規內容而且文字長度足夠。")
    law_id, _, _ = _seed_version(isolated_ingest_db, old_html)

    result = ingest_link(_link(), FakeFetcher(new_html))

    assert result["status"] == "inserted"
    assert result["version"] == 2
    with isolated_ingest_db() as db:
        versions = db.scalars(
            select(LawVersion).where(LawVersion.law_id == law_id).order_by(LawVersion.version_no)
        ).all()
        assert [version.version_no for version in versions] == [1, 2]
        assert [version.is_current for version in versions] == [False, True]


def test_historical_hash_reversion_creates_new_current_version(isolated_ingest_db):
    from app.models import LawVersion

    old_html = _html("第1條 這是第一版法規內容而且文字長度足夠。")
    current_html = _html("第1條 這是第二版法規內容而且文字長度足夠。")
    law_id, _, old_parsed = _seed_version(
        isolated_ingest_db, old_html, version_no=1, is_current=False
    )
    _seed_version(isolated_ingest_db, current_html, version_no=2, is_current=True)

    result = ingest_link(_link(), FakeFetcher(old_html))

    assert result["status"] == "inserted"
    assert result["version"] == 3
    with isolated_ingest_db() as db:
        versions = db.scalars(
            select(LawVersion).where(LawVersion.law_id == law_id).order_by(LawVersion.version_no)
        ).all()
        assert [version.is_current for version in versions] == [False, False, True]
        assert versions[0].content_hash == old_parsed.content_hash
        assert versions[2].content_hash == old_parsed.content_hash


def test_reprocess_current_is_dry_run_then_rebuilds_in_place(isolated_ingest_db):
    from app.models import LawVersion

    html = _html("一、受理申報\n1.審核申報文件並確認內容完整。")
    law_id, version_id, _ = _seed_version(
        isolated_ingest_db, html, parser_revision=None
    )
    with isolated_ingest_db() as db:
        version = db.get(LawVersion, version_id)
        version.chunks[0].heading = None
        version.content_hash = "a" * 64
        original_hash = version.content_hash

    dry_run = reprocess_current_laws()
    assert dry_run["mode"] == "dry-run"
    assert dry_run["affected"] == 1
    with isolated_ingest_db() as db:
        version = db.get(LawVersion, version_id)
        assert json.loads(version.metadata_json).get("parser_revision") is None
        assert version.chunks[0].heading is None

    applied = reprocess_current_laws(apply=True, law_ids=[law_id])
    assert applied["mode"] == "apply"
    assert applied["affected"] == 1
    with isolated_ingest_db() as db:
        version = db.get(LawVersion, version_id)
        assert version.version_no == 1
        assert version.is_current
        assert json.loads(version.metadata_json)["parser_revision"] == PARSER_REVISION
        assert version.chunks[0].heading == "一、受理申報"
        assert version.content_hash != original_hash
        assert db.execute(text("SELECT count(*) FROM law_chunks_fts")).scalar_one() == 1
