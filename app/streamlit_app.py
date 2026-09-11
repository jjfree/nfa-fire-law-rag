"""Local browser UI for the SQLite/FTS5/NumPy fire-law RAG.

The Streamlit import is intentionally lazy so the core package and test suite do
not require the optional UI dependency.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


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


def search_question(query: str, top_k: int, law_title: str | None = None) -> dict[str, Any]:
    """Run retrieval and local evidence-grounded answer generation."""
    from app.answer import answer_question
    from app.search import hybrid_search

    hits = hybrid_search(query, top_k=top_k, law_title=law_title)
    response = build_response(query, hits)
    response.update(answer_question(query, hits))
    return response


def _law_titles() -> list[str]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Law

    with session_scope() as db:
        return list(db.scalars(select(Law.title).order_by(Law.title)).all())


def _render_response(st: Any, response: dict[str, Any]) -> None:
    if response.get("answer"):
        if response.get("answer_status") == "ok":
            st.markdown(response["answer"])
        elif response.get("answer_status") == "llm_error":
            st.warning(response["answer"])
            if response.get("answer_error"):
                st.caption(f"LLM 狀態：{response['answer_error']}")
        else:
            st.info(response["answer"])
    st.markdown(response["summary"])
    for index, row in enumerate(response["results"], start=1):
        article = row["article_label"]
        heading = f"｜{row['heading']}" if row["heading"] else ""
        title = f"{index}. {row['law_title']}｜{article}{heading}｜版本 {row['version_no']}"
        with st.expander(title, expanded=index == 1):
            st.text(row["content"])
            st.caption(
                "hybrid={:.4f} · vector={:.4f} · lexical={:.4f}".format(
                    row["hybrid_score"], row["vector_score"], row["lexical_score"]
                )
            )
            st.link_button("開啟原始法規來源", row["source_url"])


def main() -> None:
    import streamlit as st

    from app.config import get_settings

    settings = get_settings()
    st.set_page_config(page_title="消防法規 RAG", page_icon="🔥", layout="wide")
    st.title("🔥 台灣消防法規 RAG")
    st.caption("本機 SQLite + FTS5 + NumPy 混合檢索；回答以現行法規條文與來源為依據。")

    with st.sidebar:
        st.header("檢索設定")
        top_k = st.slider("顯示結果數", min_value=1, max_value=20, value=8)
        try:
            titles = ["全部法規", *_law_titles()]
        except Exception as exc:  # noqa: BLE001 - show local DB setup errors in the UI
            titles = ["全部法規"]
            st.warning(f"無法載入法規清單：{type(exc).__name__}: {exc}")
        selected_title = st.selectbox("法規篩選", titles)
        st.divider()
        st.caption(f"Backend：{settings.storage_backend}")
        st.caption(f"Embedding：{settings.embedding_provider} / {settings.embedding_dim} 維")
        st.caption("僅建議在本機使用；未提供登入驗證。")

    if "qa_history" not in st.session_state:
        st.session_state.qa_history = []

    for item in st.session_state.qa_history:
        with st.chat_message("user"):
            st.write(item["query"])
        with st.chat_message("assistant"):
            if "error" in item:
                st.error(item["error"])
            else:
                _render_response(st, item["response"])

    query = st.chat_input("例如：消防法第13條對管理權人有什麼要求？")
    if not query:
        return

    with st.chat_message("user"):
        st.write(query)
    with st.chat_message("assistant"):
        try:
            response = search_question(
                query,
                top_k=top_k,
                law_title=None if selected_title == "全部法規" else selected_title,
            )
        except Exception as exc:  # noqa: BLE001 - surface local DB/config errors in the UI
            error = f"查詢失敗：{type(exc).__name__}: {exc}"
            st.error(error)
            st.session_state.qa_history.append({"query": query, "error": error})
        else:
            _render_response(st, response)
            st.session_state.qa_history.append({"query": query, "response": response})


if __name__ == "__main__":
    main()
