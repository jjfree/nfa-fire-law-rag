"""Local browser UI for the SQLite/FTS5/NumPy fire-law RAG.

The Streamlit import is intentionally lazy so the core package and test suite do
not require the optional UI dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from html import escape
from typing import Any
from urllib.parse import quote

ANSWER_MODEL_OPTIONS = ("gemma4:e2b", "gemma4:e4b", "gemma4:31b-cloud")
_CITATION_RE = re.compile(r"\[(\d+)\]")


def linkify_citations(
    answer: str,
    citations: Iterable[int],
    evidence_count: int,
    anchor_prefix: str = "evidence",
) -> str:
    """Turn validated evidence numbers into safe links that open their expander."""
    valid_citations = {
        int(citation)
        for citation in citations
        if 1 <= int(citation) <= evidence_count
    }
    safe_answer = escape(answer, quote=False)

    def replace(match: re.Match[str]) -> str:
        citation = int(match.group(1))
        if citation not in valid_citations:
            return match.group(0)
        anchor_id = f"{anchor_prefix}-{citation}"
        target = quote(f"{anchor_prefix}:{citation}", safe="")
        return (
            f'<a href="?evidence={target}#{anchor_id}" target="_self">'
            f"[{citation}]</a>"
        )

    return _CITATION_RE.sub(replace, safe_answer)


def evidence_anchor(index: int, anchor_prefix: str = "evidence") -> str:
    """Return a stable anchor used by citation links."""
    if index < 1:
        raise ValueError("evidence anchor index must be positive")
    return f'<span id="{escape(anchor_prefix, quote=True)}-{index}"></span>'


def _requested_evidence(st: Any) -> tuple[str, int] | None:
    """Read the citation target that caused the current Streamlit rerun."""
    query_params = getattr(st, "query_params", None)
    raw_target = query_params.get("evidence") if query_params is not None else None
    if not raw_target or ":" not in raw_target:
        return None
    anchor_prefix, raw_index = raw_target.rsplit(":", 1)
    try:
        index = int(raw_index)
    except ValueError:
        return None
    return (anchor_prefix, index) if index > 0 else None


def build_response(query: str, hits: Iterable[Any]) -> dict[str, Any]:
    """Convert retrieval hits into a UI-safe, provenance-preserving response."""
    rows = []
    for hit in hits:
        rows.append(
            {
                "law_title": hit.law_title,
                "article_label": hit.article_label or "未標示條號",
                "heading": hit.heading or "",
                "content": hit.content,
                "source_url": hit.source_url,
                "version_no": hit.version_no,
                "vector_score": float(hit.vector_score),
                "lexical_score": float(hit.lexical_score),
                "hybrid_score": float(hit.hybrid_score),
            }
        )

    if not rows:
        summary = "本機 RAG 沒有找到符合的現行法規條文。請改用更具體的關鍵詞、法規名稱或條號。"
    else:
        summary = (
            f"本機 RAG 找到 {len(rows)} 筆現行版本相關條文。以下內容是檢索依據，"
            "請以原始法規與主管機關正式解釋為準。"
        )
    return {"query": query, "summary": summary, "results": rows}


def search_question(
    query: str,
    top_k: int,
    law_title: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """Run retrieval and local evidence-grounded answer generation."""
    from app.answer import answer_question
    from app.search import hybrid_search

    hits = hybrid_search(query, top_k=top_k, law_title=law_title)
    response = build_response(query, hits)
    response.update(answer_question(query, hits, model=llm_model))
    return response


def _law_titles() -> list[str]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Law

    with session_scope() as db:
        return list(db.scalars(select(Law.title).order_by(Law.title)).all())


def _render_response(
    st: Any, response: dict[str, Any], anchor_prefix: str = "evidence"
) -> None:
    local_results = response.get("results", [])
    web_results = response.get("web_results", [])
    evidence_count = len(local_results) + len(web_results)
    requested_evidence = _requested_evidence(st)
    if response.get("answer"):
        if response.get("answer_status") == "ok":
            st.markdown(
                linkify_citations(
                    response["answer"],
                    response.get("answer_citations", []),
                    evidence_count,
                    anchor_prefix,
                ),
                unsafe_allow_html=True,
            )
        elif response.get("answer_status") == "llm_error":
            st.warning(response["answer"])
            if response.get("answer_error"):
                st.caption(f"LLM 狀態：{response['answer_error']}")
        else:
            st.info(response["answer"])
    web_status = response.get("web_search_status")
    if web_status == "used":
        st.caption("本次 RAG 證據不足，已補充允許清單內的官方網頁資料。")
    elif web_status == "unavailable":
        st.caption("RAG 證據不足；web fallback 尚未設定 OLLAMA_API_KEY。")
    elif web_status == "error":
        st.caption("RAG 證據不足；web fallback 暫時無法連線，以下仍顯示本機結果。")
    elif web_status == "no_results":
        st.caption("RAG 證據不足；web search 沒有找到允許清單內的官方來源。")
    if web_results:
        st.subheader("Web 補充來源")
        for index, source in enumerate(web_results, start=len(local_results) + 1):
            st.markdown(
                evidence_anchor(index, anchor_prefix), unsafe_allow_html=True
            )
            with st.expander(
                source["title"],
                expanded=requested_evidence == (anchor_prefix, index),
            ):
                st.caption(f"擷取時間：{source['retrieved_at']}")
                if source.get("content_preview"):
                    st.text(source["content_preview"])
                st.link_button("開啟官方來源", source["url"])
    st.markdown(response["summary"])
    for index, row in enumerate(local_results, start=1):
        st.markdown(evidence_anchor(index, anchor_prefix), unsafe_allow_html=True)
        article = row["article_label"]
        heading = f"｜{row['heading']}" if row["heading"] else ""
        title = f"{index}. {row['law_title']}｜{article}{heading}｜版本 {row['version_no']}"
        with st.expander(
            title,
            expanded=index == 1 or requested_evidence == (anchor_prefix, index),
        ):
            st.text(row["content"])
            st.caption(
                "hybrid={:.4f} · vector={:.4f} · lexical={:.4f}".format(
                    row["hybrid_score"], row["vector_score"], row["lexical_score"]
                )
            )
            st.link_button("開啟原始法規來源", row["source_url"])


def _ensure_active_conversation(st: Any) -> tuple[int, list[Any]]:
    """Create the first conversation and recover from deleted/stale selections."""
    from app.conversations import create_conversation, list_conversations

    conversations = list_conversations()
    if not conversations:
        conversation_id = create_conversation()
        conversations = list_conversations()
    else:
        conversation_id = st.session_state.get("active_conversation_id")
        valid_ids = {conversation.id for conversation in conversations}
        if conversation_id not in valid_ids:
            conversation_id = conversations[0].id
    st.session_state.active_conversation_id = conversation_id
    return conversation_id, conversations


def _render_conversation_sidebar(st: Any, conversations: list[Any], active_id: int) -> None:
    from app.conversations import create_conversation, delete_conversation, rename_conversation

    heading_col, action_col = st.columns([3, 2])
    with heading_col:
        st.header("對話列表")
    with action_col:
        if st.button("＋新增對話", type="primary", use_container_width=True):
            st.session_state.active_conversation_id = create_conversation()
            st.rerun()
    st.caption("對話會保存在本機 SQLite，重啟後仍可繼續。")
    for conversation in conversations:
        select_col, menu_col = st.columns([5, 1])
        with select_col:
            label = f"▶ {conversation.title}" if conversation.id == active_id else conversation.title
            if st.button(label, key=f"select_conversation_{conversation.id}", use_container_width=True):
                st.session_state.active_conversation_id = conversation.id
                st.rerun()
        with menu_col, st.popover("⋯", use_container_width=True):
            new_title = st.text_input(
                "對話標題",
                value=conversation.title,
                key=f"conversation_title_{conversation.id}",
            )
            if st.button("儲存標題", key=f"rename_conversation_{conversation.id}"):
                rename_conversation(conversation.id, new_title)
                st.rerun()
            if st.button("刪除對話", key=f"delete_conversation_{conversation.id}"):
                delete_conversation(conversation.id)
                st.session_state.pop("active_conversation_id", None)
                st.rerun()


def main() -> None:
    import streamlit as st

    from app.config import get_settings
    from app.conversations import get_messages, save_exchange
    from app.db import init_db

    settings = get_settings()
    st.set_page_config(page_title="消防法規 RAG", page_icon="🔥", layout="wide")
    init_db()
    active_id, conversations = _ensure_active_conversation(st)

    with st.sidebar:
        _render_conversation_sidebar(st, conversations, active_id)
        st.divider()
        st.header("檢索設定")
        top_k = st.slider("顯示結果數", min_value=1, max_value=20, value=8)
        try:
            titles = ["全部法規", *_law_titles()]
        except Exception as exc:  # noqa: BLE001 - show local DB setup errors in the UI
            titles = ["全部法規"]
            st.warning(f"無法載入法規清單：{type(exc).__name__}: {exc}")
        selected_title = st.selectbox("法規篩選", titles)
        selected_model = st.selectbox(
            "回答模型",
            ANSWER_MODEL_OPTIONS,
            index=(
                ANSWER_MODEL_OPTIONS.index(settings.llm_model)
                if settings.llm_model in ANSWER_MODEL_OPTIONS
                else len(ANSWER_MODEL_OPTIONS) - 1
            ),
            format_func=lambda model: (
                f"{model}（速度優先）" if model == "gemma4:e2b" else f"{model}（品質優先）"
                if model == "gemma4:e4b"
                else f"{model}（雲端品質優先）"
            ),
        )
        st.caption(
            "e2b 較快；e4b 通常較完整；31b-cloud 會使用 Ollama Cloud。"
            "選擇 31b-cloud 時，即使 RAG 無命中也會嘗試 web fallback。"
        )
        st.divider()
        st.caption(f"Backend：{settings.storage_backend}")
        st.caption(f"Embedding：{settings.embedding_provider} / {settings.embedding_dim} 維")
        st.caption("僅建議在本機使用；未提供登入驗證。")

    active_title = next(item.title for item in conversations if item.id == active_id)
    st.title("🔥 台灣消防法規 RAG")
    st.caption(f"目前對話：{active_title}")

    st.caption("本機 SQLite + FTS5 + NumPy 混合檢索；回答以現行法規條文與來源為依據。")

    messages = get_messages(active_id)
    for message_index, message in enumerate(messages):
        message_anchor_prefix = f"conversation-{active_id}-message-{message_index}"
        with st.chat_message(message.role):
            if message.role == "user":
                st.write(message.content)
            elif message.response and message.response.get("error"):
                st.error(message.response["error"])
            elif message.response:
                _render_response(st, message.response, message_anchor_prefix)
            else:
                st.write(message.content)

    query = st.chat_input("例如：消防法第13條對管理權人有什麼要求？")
    if not query:
        return

    # Render the submitted question before starting retrieval/LLM work so the
    # user gets immediate feedback even when the local model takes a while.
    with st.chat_message("user"):
        st.write(query)
    with st.chat_message("assistant"), st.spinner("正在檢索法規並整理回答…"):
        try:
            response = search_question(
                query,
                top_k=top_k,
                law_title=None if selected_title == "全部法規" else selected_title,
                llm_model=selected_model,
            )
        except Exception as exc:  # noqa: BLE001 - surface local DB/config errors in the UI
            error = f"查詢失敗：{type(exc).__name__}: {exc}"
            save_exchange(active_id, query, error=error)
            st.error(error)
        else:
            message_anchor_prefix = f"conversation-{active_id}-message-{len(messages) + 1}"
            _render_response(st, response, message_anchor_prefix)
            save_exchange(active_id, query, response=response)
    st.rerun()


if __name__ == "__main__":
    main()
