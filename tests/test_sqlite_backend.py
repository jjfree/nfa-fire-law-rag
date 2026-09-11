import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

# Keep this integration test independent from a developer's .env and from Docker.
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["STORAGE_BACKEND"] = "sqlite"
os.environ["DATABASE_URL"] = "sqlite:///" + _db_path.replace("\\", "/")

from app.config import get_settings

get_settings.cache_clear()

from app.db import embedding_to_storage, engine, init_db, rebuild_fts, session_scope
from app.embedding import HashEmbedder
from app.models import Law, LawChunk, LawVersion
from app.search import exact_article, hybrid_search


@pytest.fixture(scope="module", autouse=True)
def sqlite_database():
    init_db()
    embedder = HashEmbedder(get_settings().embedding_dim)
    with session_scope() as db:
        law = Law(
            source_key="test:fire-law",
            title="消防法",
            source_url="https://law.nfa.gov.tw/test",
        )
        db.add(law)
        db.flush()
        version = LawVersion(
            law_id=law.id,
            version_no=1,
            content_hash="a" * 64,
            raw_text="第1條...\n第13條...",
            is_current=True,
        )
        db.add(version)
        db.flush()
        for seq, article, content in [
            (1, "第1條", "為預防火災、搶救災害及緊急救護，以維護公共安全。"),
            (2, "第13條", "管理權人應依規定設置消防安全設備並負責維護。"),
        ]:
            vector = embedder.embed([f"消防法 {article} {content}"])[0]
            db.add(
                LawChunk(
                    version_id=version.id,
                    seq=seq,
                    article_label=article,
                    content=content,
                    embedding=embedding_to_storage(vector),
                )
            )
        db.flush()
        rebuild_fts(db)
    yield
    engine.dispose()
    Path(_db_path).unlink(missing_ok=True)


def test_sqlite_creates_fts5_index_for_current_chunks():
    with session_scope() as db:
        count = db.execute(text("SELECT count(*) FROM law_chunks_fts")).scalar_one()
    assert count == 2


def test_sqlite_hybrid_search_combines_fts5_and_numpy():
    hits = hybrid_search("管理權人消防安全設備", top_k=1)
    assert len(hits) == 1
    assert hits[0].law_title == "消防法"
    assert hits[0].article_label == "第13條"
    assert hits[0].vector_score > 0
    assert hits[0].lexical_score > 0


def test_sqlite_exact_article_matches_current_data():
    hits = exact_article("消防法", "第13條")
    assert [hit.article_label for hit in hits] == ["第13條"]
