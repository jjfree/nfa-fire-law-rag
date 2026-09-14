"""Small persistence layer for the local Streamlit conversation history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.models import Conversation, ConversationMessage

DEFAULT_CONVERSATION_TITLE = "新對話"


@dataclass(frozen=True)
class ConversationSummary:
    id: int
    title: str
    last_message_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str
    response: dict[str, Any] | None
    created_at: datetime


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split()).strip()
    return cleaned[:200] or DEFAULT_CONVERSATION_TITLE


def _title_from_query(query: str) -> str:
    cleaned = " ".join(query.split()).strip()
    return (cleaned[:37] + "…") if len(cleaned) > 38 else (cleaned or DEFAULT_CONVERSATION_TITLE)


def list_conversations() -> list[ConversationSummary]:
    with session_scope() as db:
        latest_message_at = (
            select(func.max(ConversationMessage.created_at))
            .where(ConversationMessage.conversation_id == Conversation.id)
            .scalar_subquery()
        )
        last_activity_at = func.coalesce(latest_message_at, Conversation.created_at)
        rows = db.execute(
            select(Conversation, latest_message_at.label("last_message_at"))
            .order_by(last_activity_at.desc(), Conversation.id.desc())
        ).all()
        return [
            ConversationSummary(
                conversation.id,
                conversation.title,
                last_message_at,
                conversation.created_at,
            )
            for conversation, last_message_at in rows
        ]


def create_conversation(title: str = DEFAULT_CONVERSATION_TITLE) -> int:
    with session_scope() as db:
        conversation = Conversation(title=_clean_title(title))
        db.add(conversation)
        db.flush()
        return conversation.id


def rename_conversation(conversation_id: int, title: str) -> bool:
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return False
        conversation.title = _clean_title(title)
        return True


def delete_conversation(conversation_id: int) -> bool:
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return False
        db.delete(conversation)
        return True


def get_messages(conversation_id: int) -> list[StoredMessage]:
    with session_scope() as db:
        rows = db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at, ConversationMessage.id)
        ).all()
        messages = []
        for row in rows:
            response = json.loads(row.response_json) if row.response_json else None
            messages.append(StoredMessage(row.role, row.content, response, row.created_at))
        return messages


def save_exchange(
    conversation_id: int,
    query: str,
    response: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Store a question and its complete UI response as one transaction."""
    if response is None and error is None:
        raise ValueError("response or error is required")

    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise ValueError(f"找不到對話：{conversation_id}")

        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content=query,
            )
        )
        db.add(
            ConversationMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=error or (response or {}).get("answer") or (response or {}).get("summary", ""),
                response_json=json.dumps(
                    {"error": error} if error else response,
                    ensure_ascii=False,
                ),
            )
        )
        if conversation.title == DEFAULT_CONVERSATION_TITLE:
            conversation.title = _title_from_query(query)
        conversation.updated_at = datetime.now(UTC).replace(tzinfo=None)
