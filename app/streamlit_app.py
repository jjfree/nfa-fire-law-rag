"""Local browser UI for the SQLite/FTS5/NumPy fire-law RAG.

The Streamlit import is intentionally lazy so the core package and test suite do
not require the optional UI dependency.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC
from html import escape
from typing import Any

ANSWER_MODEL_OPTIONS = ("gemma4:e2b", "gemma4:e4b", "gemma4:31b-cloud")
_CITATION_RE = re.compile(r"\[(\d+)\]")
_OUTPUT_LIMIT_REASONS = {"length", "max_tokens", "token_limit"}
_QUESTION_ANCHOR_CSS = """
<style>
.nfa-question-anchor {
  display: block;
  height: 0;
  margin: 0;
  padding: 0;
  scroll-margin-top: 5rem;
}
</style>
"""


def build_answer_diagnostic(response: dict[str, Any]) -> str:
    """Build a user-facing generation summary while retaining raw metadata elsewhere."""
    model = response.get("answer_model")
    if not model:
        return ""

    parts = [f"模型：{model}"]
    actual_tokens = response.get("answer_eval_count")
    output_limit = response.get("answer_effective_output_tokens")
    if actual_tokens is not None and output_limit is not None:
        parts.append(f"實際輸出 {actual_tokens}／上限 {output_limit} tokens")
    elif actual_tokens is not None:
        parts.append(f"實際輸出 {actual_tokens} tokens")
    elif output_limit is not None:
        parts.append(f"輸出上限 {output_limit} tokens")

    answer_status = str(response.get("answer_status") or "").strip().lower()
    done_reason = str(response.get("answer_done_reason") or "").strip()
    normalized_reason = done_reason.lower()
    if answer_status == "incomplete":
        generation_status = (
            "達到輸出上限，回答未完整"
            if normalized_reason in _OUTPUT_LIMIT_REASONS
            else "回答未完整"
        )
    elif answer_status == "llm_error":
        generation_status = "產生失敗"
    elif normalized_reason == "stop" or answer_status == "ok":
        generation_status = "已完成"
    elif normalized_reason in _OUTPUT_LIMIT_REASONS:
        generation_status = "達到輸出上限"
    elif done_reason:
        generation_status = f"模型已結束輸出（技術代碼：{done_reason}）"
    else:
        generation_status = "未回報"
    parts.append(f"生成狀態：{generation_status}")

    retry_count = response.get("answer_retry_count")
    if retry_count:
        parts.append(f"重試：{retry_count} 次")
    return " · ".join(parts)


def linkify_citations(
    answer: str,
    citations: Iterable[int],
    evidence_count: int,
    anchor_prefix: str = "evidence",
) -> str:
    """Turn validated evidence numbers into safe links to client-side cards."""
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
        return f'<a href="#{escape(anchor_id, quote=True)}">[{citation}]</a>'

    return _CITATION_RE.sub(replace, safe_answer)


def evidence_anchor(index: int, anchor_prefix: str = "evidence") -> str:
    """Return a stable anchor used by citation links."""
    if index < 1:
        raise ValueError("evidence anchor index must be positive")
    return f'<span id="{escape(anchor_prefix, quote=True)}-{index}"></span>'


def question_anchor(
    conversation_id: int, message_index: int, latest: bool = False
) -> str:
    """Return a stable, zero-height anchor placed immediately before a question."""
    anchor_id = f"conversation-{conversation_id}-message-{message_index}-question"
    latest_attribute = ' data-nfa-latest-question="true"' if latest else ""
    return (
        f'<span id="{escape(anchor_id, quote=True)}" '
        f'class="nfa-question-anchor"{latest_attribute}></span>'
    )


def latest_user_message_index(messages: Iterable[Any]) -> int | None:
    """Return the rendered index of the most recent user question, if any."""
    latest_index: int | None = None
    for index, message in enumerate(messages):
        if message.role == "user":
            latest_index = index
    return latest_index


def _render_latest_question_scroll(st: Any, anchor_id: str | None) -> None:
    """Keep the viewport at the latest question after Streamlit finishes rendering."""
    if anchor_id is None:
        return

    scroll_script = """
<script>
(() => {
  const targetId = __TARGET_ID__;
  const startedAt = Date.now();
  const alignQuestion = () => {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.scrollIntoView({block: "start", inline: "nearest", behavior: "auto"});
  };

  alignQuestion();
  const alignmentTimer = window.setInterval(() => {
    alignQuestion();
    if (Date.now() - startedAt >= 3000) {
      window.clearInterval(alignmentTimer);
    }
  }, 100);
})();
</script>
""".replace("__TARGET_ID__", json.dumps(anchor_id))
    # `unsafe_allow_javascript` is available in the supported Streamlit runtime
    # used by the launcher. Keep a small fallback for older optional UI installs.
    try:
        st.html(scroll_script, unsafe_allow_javascript=True)
    except (AttributeError, TypeError):
        st.markdown(scroll_script, unsafe_allow_html=True)


_EVIDENCE_CSS = """
<style>
.rag-evidence-card {
  border: 1px solid rgba(128, 128, 128, 0.35);
  border-radius: 0.5rem;
  margin: 0.5rem 0;
  overflow: hidden;
}
.rag-evidence-toggle {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
}
.rag-evidence-header {
  display: block;
  cursor: pointer;
  padding: 0.65rem 0.8rem;
  font-weight: 600;
}
.rag-evidence-header:hover {
  background: rgba(128, 128, 128, 0.12);
}
.rag-evidence-content {
  display: none;
  border-top: 1px solid rgba(128, 128, 128, 0.25);
  padding: 0.75rem 0.8rem;
}
.rag-evidence-toggle:checked ~ .rag-evidence-content,
.rag-evidence-card:target .rag-evidence-content {
  display: block;
}
.rag-evidence-meta {
  color: rgba(128, 128, 128, 0.95);
  font-size: 0.85rem;
  margin-bottom: 0.5rem;
}
.rag-evidence-text {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0 0 0.75rem 0;
  font-family: inherit;
}
</style>
"""


def _evidence_card(
    index: int,
    title: str,
    metadata: str,
    content: str,
    source_url: str,
    anchor_prefix: str,
    default_expanded: bool = False,
) -> str:
    anchor_id = f"{anchor_prefix}-{index}"
    safe_anchor_id = escape(anchor_id, quote=True)
    toggle_id = f"{anchor_id}-toggle"
    checked = " checked" if default_expanded else ""
    return (
        f'<div id="{safe_anchor_id}" class="rag-evidence-card">'
        f'<input class="rag-evidence-toggle" type="checkbox" '
        f'id="{escape(toggle_id, quote=True)}"{checked}>'
        f'<label class="rag-evidence-header" '
        f'for="{escape(toggle_id, quote=True)}">{escape(title)}</label>'
        '<div class="rag-evidence-content">'
        f'<div class="rag-evidence-meta">{escape(metadata)}</div>'
        f'<pre class="rag-evidence-text">{escape(content)}</pre>'
        f'<a href="{escape(source_url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">開啟原始來源</a>'
        "</div></div>"
    )


def build_evidence_cards(
    local_results: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    anchor_prefix: str = "evidence",
) -> str:
    """Build client-side evidence cards that open through fragment targeting."""
    cards = [_EVIDENCE_CSS]
    local_count = len(local_results)
    for index, row in enumerate(local_results, start=1):
        law_title = row["law_title"]
        article = row["article_label"]
        heading = f"｜{row['heading']}" if row["heading"] else ""
        title = f"[{index}] {law_title}｜{article}{heading}｜版本 {row['version_no']}"
        if row.get("retrieval_mode") == "structural_section":
            metadata = "結構式章節檢索 · 依條文順序"
        else:
            metadata = "hybrid={:.4f} · vector={:.4f} · lexical={:.4f}".format(
                row["hybrid_score"], row["vector_score"], row["lexical_score"]
            )
        cards.append(
            _evidence_card(
                index=index,
                title=title,
                metadata=metadata,
                content=row["content"],
                source_url=row["source_url"],
                anchor_prefix=anchor_prefix,
                default_expanded=index == 1,
            )
        )
    for index, source in enumerate(web_results, start=local_count + 1):
        cards.append(
            _evidence_card(
                index=index,
                title=f"[{index}] {source['title']}",
                metadata=f"官方網頁補充資料 · 擷取時間：{source['retrieved_at']}",
                content=source.get("content_preview", ""),
                source_url=source["url"],
                anchor_prefix=anchor_prefix,
            )
        )
    return "".join(cards)


def build_response(
    query: str,
    hits: Iterable[Any],
    retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
                "retrieval_mode": getattr(hit, "retrieval_mode", "hybrid"),
            }
        )

    if not rows:
        summary = "本機 RAG 沒有找到符合的現行法規條文。請改用更具體的關鍵詞、法規名稱或條號。"
    elif retrieval and retrieval.get("mode") == "structural_section":
        total = int(retrieval.get("total_matches") or len(rows))
        summary = (
            f"本機 RAG 依 {retrieval.get('scope_law_title')}「"
            f"{retrieval.get('scope_heading')}」章節結構完整取回 "
            f"{len(rows)}／{total} 筆現行實質條文，並依條文順序顯示。"
        )
    else:
        summary = (
            f"本機 RAG 找到 {len(rows)} 筆現行版本相關條文。以下內容是檢索依據，"
            "請以原始法規與主管機關正式解釋為準。"
        )
    response = {"query": query, "summary": summary, "results": rows}
    if retrieval:
        response["retrieval"] = retrieval
    return response


def search_question(
    query: str,
    top_k: int,
    law_title: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """Run retrieval and local evidence-grounded answer generation."""
    from app.answer import answer_question
    from app.rerank import retrieve_answer_evidence

    evidence = retrieve_answer_evidence(query, top_k=top_k, law_title=law_title)
    response = build_response(query, evidence.hits, evidence.metadata())
    response.update(answer_question(query, evidence.hits, model=llm_model))
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
        elif response.get("answer_status") == "incomplete":
            st.warning("模型回答未完整收尾；以下保留可驗證內容，請查看診斷資訊。")
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
    if response.get("answer_model"):
        st.caption(build_answer_diagnostic(response))
    retrieval = response.get("retrieval", {})
    if retrieval.get("mode") == "structural_section":
        returned = int(retrieval.get("returned_matches") or len(local_results))
        total = int(retrieval.get("total_matches") or returned)
        scope = "／".join(
            value
            for value in (
                retrieval.get("scope_law_title"),
                retrieval.get("scope_heading"),
            )
            if value
        )
        message = f"完整列舉模式：{scope}，證據覆蓋 {returned}／{total} 筆。"
        if retrieval.get("complete") is True and returned == total:
            st.success(message)
        else:
            st.warning(f"{message}目前結果未完整，請勿視為全部條文。")
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
        st.subheader(f"Web 補充來源（{len(web_results)} 筆）")
    st.markdown(response["summary"])
    if local_results or web_results:
        st.caption(
            f"證據編號：本機 [1]–[{len(local_results)}]"
            + (
                f"；Web [{len(local_results) + 1}]–[{evidence_count}]"
                if web_results
                else ""
            )
        )
    if local_results or web_results:
        st.markdown(
            build_evidence_cards(local_results, web_results, anchor_prefix),
            unsafe_allow_html=True,
        )


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


def _conversation_time_label(conversation: Any) -> str:
    timestamp = conversation.last_message_at or conversation.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    local_time = timestamp.astimezone().strftime("%Y/%m/%d %H:%M:%S")
    prefix = "最後對談" if conversation.last_message_at else "尚未對談，建立時間"
    return f"{prefix}：{local_time}"


def _render_conversation_sidebar(st: Any, conversations: list[Any], active_id: int) -> None:
    from app.conversations import create_conversation, delete_conversation, rename_conversation

    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] > div {
            width: 100%;
            justify-content: flex-start;
        }
        section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]
        [data-testid="stMarkdownContainer"] {
            width: 100%;
            text-align: left;
        }
        section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p {
            text-align: left;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    heading_col, action_col = st.columns([3, 2])
    with heading_col:
        st.header("對話列表")
    with action_col:
        if st.button("＋新增對話", type="primary", use_container_width=True):
            st.session_state.active_conversation_id = create_conversation()
            st.rerun()
    st.caption("對話會保存在本機 SQLite，重啟後仍可繼續。")
    conversation_height = 260 if len(conversations) > 5 else "content"
    with st.container(height=conversation_height, border=False):
        for conversation in conversations:
            select_col, menu_col = st.columns([5, 1])
            with select_col:
                label = f"▶ {conversation.title}" if conversation.id == active_id else conversation.title
                if st.button(
                    label,
                    key=f"select_conversation_{conversation.id}",
                    help=_conversation_time_label(conversation),
                    use_container_width=True,
                ):
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
        st.caption("一般查詢依此數量顯示；『所有／全部／逐條』等完整列舉問題可能自動展開超過此數量。")
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
    st.markdown(_QUESTION_ANCHOR_CSS, unsafe_allow_html=True)

    messages = get_messages(active_id)
    latest_question_index = latest_user_message_index(messages)
    latest_question_anchor_id = (
        f"conversation-{active_id}-message-{latest_question_index}-question"
        if latest_question_index is not None
        else None
    )
    for message_index, message in enumerate(messages):
        message_anchor_prefix = f"conversation-{active_id}-message-{message_index}"
        if message.role == "user":
            st.markdown(
                question_anchor(
                    active_id,
                    message_index,
                    latest=message_index == latest_question_index,
                ),
                unsafe_allow_html=True,
            )
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
        _render_latest_question_scroll(st, latest_question_anchor_id)
        return

    # Render the submitted question before starting retrieval/LLM work so the
    # user gets immediate feedback even when the local model takes a while.
    with st.chat_message("user"):
        st.markdown(
            question_anchor(active_id, len(messages), latest=True),
            unsafe_allow_html=True,
        )
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
    _render_latest_question_scroll(
        st,
        f"conversation-{active_id}-message-{len(messages)}-question",
    )
    st.rerun()


if __name__ == "__main__":
    main()
