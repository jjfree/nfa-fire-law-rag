"""Parse explicit web-search requests before retrieval and answer generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

WebSearchMode = Literal["auto", "force"]
_WEB_PREFIX = re.compile(r"^/web(?=\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerRequest:
    query: str
    web_mode: WebSearchMode


def parse_answer_request(query: str, web_mode: WebSearchMode = "auto") -> AnswerRequest:
    """Remove a leading /web directive; never send it to retrieval or search."""
    if web_mode not in ("auto", "force"):
        raise ValueError("web_mode 必須是 auto 或 force")
    question = query.strip()
    if _WEB_PREFIX.match(question):
        question = _WEB_PREFIX.sub("", question, count=1).strip()
        web_mode = "force"
    if not question:
        raise ValueError("請在 /web 後輸入問題" if query.strip() else "請輸入問題")
    return AnswerRequest(question, web_mode)
