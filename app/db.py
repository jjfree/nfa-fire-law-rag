from contextlib import contextmanager
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.storage_backend.lower() == "sqlite":
    database_path = settings.database_url.removeprefix("sqlite:///")
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401

    with engine.begin() as conn:
        if settings.storage_backend.lower() == "postgres":
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(bind=engine)
    if settings.storage_backend.lower() == "sqlite":
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS law_chunks_fts USING fts5(
                        content,
                        article_label,
                        heading,
                        law_title,
                        chunk_id UNINDEXED,
                        law_id UNINDEXED,
                        version_id UNINDEXED
                    )
                    """
                )
            )


def embedding_to_storage(vector: list[float]):
    """Store vectors as pgvector on PostgreSQL and compact bytes on SQLite."""
    if settings.storage_backend.lower() == "sqlite":
        return np.asarray(vector, dtype=np.float32).tobytes()
    return vector


def embedding_from_storage(value) -> np.ndarray:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return np.frombuffer(value, dtype=np.float32)
    return np.asarray(value, dtype=np.float32)


def _fts_index_text(value: str | None) -> str:
    """Add CJK character n-grams because unicode61 does not segment Chinese."""
    import re

    value = value or ""
    normalized = re.sub(r"\s+", "", value.lower())
    grams = {
        normalized[i : i + n]
        for n in (1, 2, 3)
        for i in range(max(0, len(normalized) - n + 1))
    }
    return f"{value} {' '.join(sorted(grams))}".strip()


def rebuild_fts(session) -> None:
    """Rebuild the SQLite FTS index from current law versions only."""
    if settings.storage_backend.lower() != "sqlite":
        return
    rows = list(session.execute(
        text(
            """
            SELECT c.id AS chunk_id, l.id AS law_id, c.version_id,
                   c.article_label, c.heading, c.content, l.title AS law_title
            FROM law_chunks c
            JOIN law_versions v ON v.id = c.version_id AND v.is_current = 1
            JOIN laws l ON l.id = v.law_id
            """
        )
    ).mappings())
    session.execute(text("DELETE FROM law_chunks_fts"))
    for row in rows:
        session.execute(
            text(
                """
                INSERT INTO law_chunks_fts
                    (content, article_label, heading, law_title, chunk_id, law_id, version_id)
                VALUES (:content, :article_label, :heading, :law_title, :chunk_id, :law_id, :version_id)
                """
            ),
            {
                "content": _fts_index_text(row["content"]),
                "article_label": _fts_index_text(row["article_label"]),
                "heading": _fts_index_text(row["heading"]),
                "law_title": _fts_index_text(row["law_title"]),
                "chunk_id": row["chunk_id"],
                "law_id": row["law_id"],
                "version_id": row["version_id"],
            },
        )
