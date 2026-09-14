from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base

settings = get_settings()

if settings.storage_backend.lower() == "postgres":
    try:
        from pgvector.sqlalchemy import Vector
    except ImportError as exc:  # pragma: no cover - depends on optional deployment extra
        raise RuntimeError(
            "PostgreSQL backend requires optional dependencies; install the postgres extra"
        ) from exc
    EMBEDDING_TYPE = Vector(settings.embedding_dim)
else:
    EMBEDDING_TYPE = LargeBinary


class Law(Base):
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    category: Mapped[str] = mapped_column(String(200), default="消防預防調查法令")
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[list["LawVersion"]] = relationship(
        back_populates="law", cascade="all, delete-orphan"
    )


class LawVersion(Base):
    __tablename__ = "law_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    law: Mapped[Law] = relationship(back_populates="versions")
    chunks: Mapped[list["LawChunk"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("law_id", "version_no", name="uq_law_version"),)


class LawChunk(Base):
    __tablename__ = "law_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("law_versions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    article_label: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[object] = mapped_column(EMBEDDING_TYPE)

    version: Mapped[LawVersion] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("version_id", "seq", name="uq_version_chunk_seq"),
        *(
            [
                Index(
                    "ix_law_chunks_content_trgm",
                    "content",
                    postgresql_using="gin",
                    postgresql_ops={"content": "gin_trgm_ops"},
                )
            ]
            if settings.storage_backend.lower() == "postgres"
            else []
        ),
    )


class Conversation(Base):
    """A persisted UI conversation, independent from the law corpus."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="新對話")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True
    )

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationMessage(Base):
    """One user question or assistant response in a persisted conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
