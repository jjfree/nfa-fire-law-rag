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
from app.search import (
    _defined_terms,
    _matched_law_titles,
    _normalize_query,
    _text_lexical_score,
    exact_article,
    hybrid_search,
)


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
            raw_text="第1條...\n第2條...\n第3條...\n第13條...",
            is_current=True,
        )
        db.add(version)
        db.flush()
        for seq, article, content in [
            (1, "第1條", "為預防火災、搶救災害及緊急救護，以維護公共安全。"),
            (2, "第2條", "本法所稱管理權人，係指依法令或契約對各該場所具有實際支配管理權者。"),
            (3, "第3條", "本法所稱主管機關：在中央為內政部；在直轄市為直轄市政府；在縣（市）為縣（市）政府。"),
            (4, "第13條", "管理權人應依規定設置消防安全設備並負責維護。"),
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

        penalty_articles = [
            "第33條",
            "第34條",
            "第35條",
            "第35-1條",
            "第35-2條",
            "第36條",
            "第37條",
            "第38條",
            "第39條",
            "第40條",
            "第41條",
            "第41-1條",
            "第42條",
            "第42-1條",
            "第42-2條",
            "第42-3條",
            "第42-4條",
            "第43條",
            "第43-1條",
            "第43-2條",
            "第44條",
        ]
        for offset, article in enumerate(penalty_articles, start=5):
            content = f"{article} 違反本法規定者，處新臺幣一萬元以上五萬元以下罰鍰。"
            vector = embedder.embed([f"消防法 第六章 罰則 {article} {content}"])[0]
            db.add(
                LawChunk(
                    version_id=version.id,
                    seq=offset,
                    article_label=article,
                    heading="第六章 罰則",
                    content=content,
                    embedding=embedding_to_storage(vector),
                )
            )
        deleted_content = "第45條 （刪除）"
        db.add(
            LawChunk(
                version_id=version.id,
                seq=26,
                article_label="第45條",
                heading="第六章 罰則",
                content=deleted_content,
                embedding=embedding_to_storage(
                    embedder.embed([f"消防法 第六章 罰則 {deleted_content}"])[0]
                ),
            )
        )

        related_law = Law(
            source_key="test:authority-guidance",
            title="消防主管機關作業規定",
            source_url="https://law.nfa.gov.tw/test-guidance",
        )
        db.add(related_law)
        db.flush()
        related_version = LawVersion(
            law_id=related_law.id,
            version_no=1,
            content_hash="b" * 64,
            raw_text="各級消防主管機關應辦理年度查核。",
            is_current=True,
        )
        db.add(related_version)
        db.flush()
        related_content = "各級消防主管機關應辦理年度查核，並彙整執行成果。"
        related_vector = embedder.embed(
            [f"消防主管機關作業規定 一、 {related_content}"]
        )[0]
        db.add(
            LawChunk(
                version_id=related_version.id,
                seq=1,
                article_label="一、",
                content=related_content,
                embedding=embedding_to_storage(related_vector),
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
    assert count == 27


def test_sqlite_hybrid_search_combines_fts5_and_numpy():
    hits = hybrid_search("管理權人消防安全設備", top_k=1)
    assert len(hits) == 1
    assert hits[0].law_title == "消防法"
    assert hits[0].article_label == "第13條"
    assert hits[0].vector_score > 0
    assert hits[0].lexical_score > 0


def test_sqlite_definition_query_prioritizes_definition_chunk_without_article_hint():
    hits = hybrid_search("請說明消防法規定義的管理權人", top_k=3)

    assert hits[0].law_title == "消防法"
    assert hits[0].article_label == "第2條"
    assert hits[0].lexical_score >= 0.85


def test_plain_identity_query_routes_to_law_and_avoids_web_fallback():
    from app.answer import rag_needs_web_search

    hits = hybrid_search("請說明消防法規的主管機關?", top_k=8)

    assert hits[0].law_title == "消防法"
    assert hits[0].article_label == "第3條"
    assert hits[0].lexical_score == 1.0
    assert not rag_needs_web_search(hits)


def test_definition_cases_are_retrieved_from_generic_clause_patterns():
    cases = (("管理權人", "第2條"), ("主管機關", "第3條"))

    for term, expected_article in cases:
        hits = hybrid_search(f"請說明消防法規的{term}?", top_k=8)
        assert hits[0].article_label == expected_article


def test_definition_parser_and_law_title_routing_are_not_term_specific():
    content = (
        "本法所稱管理權人，係指實際支配管理權者。"
        "本法所稱主管機關：在中央為內政部。"
    )

    assert _defined_terms(content) == ("管理權人", "主管機關")
    assert _normalize_query("請說明：消防法規的主管機關？") == "消防法規的主管機關"
    assert _matched_law_titles(
        "消防法施行細則的主管機關", ["消防法", "消防法施行細則", "建築法"]
    ) == ("消防法施行細則",)


def test_definition_boost_prefers_definition_of_query_term_over_reference():
    query = "請說明消防法規定義的管理權人"
    definition = "本法所稱管理權人，係指依法令或契約對各該場所具有實際支配管理權者。"
    reference = "本須知所稱指導機構，指接受場所管理權人之委託，提供相關服務。"

    definition_score = _text_lexical_score(query, "消防法", "第2條", "", definition)
    reference_score = _text_lexical_score(query, "其他法規", "二、", "", reference)

    assert definition_score == 1.0
    assert reference_score < definition_score


def test_inclusion_target_exact_match_is_not_diluted_by_question_wording():
    query = "請說明消防列管場所包含哪些？是否包含寺廟？"
    matching = "各類場所按用途分類如下：乙類場所包含寺廟、宗祠及教堂。"
    unrelated = "消防機關得依場所危險程度分類列管檢查及複查。"

    matching_score = _text_lexical_score(query, "設置標準", "第12條", "", matching)
    unrelated_score = _text_lexical_score(query, "消防法", "第6條", "", unrelated)

    assert matching_score == 1.0
    assert unrelated_score < matching_score


def test_action_query_still_prefers_obligation_over_definition():
    hits = hybrid_search("管理權人應負哪些消防安全設備維護責任", top_k=3)

    assert hits[0].law_title == "消防法"
    assert hits[0].article_label == "第13條"


def test_sqlite_exact_article_matches_current_data():
    hits = exact_article("消防法", "第13條")
    assert [hit.article_label for hit in hits] == ["第13條"]


def test_exhaustive_penalty_query_returns_complete_structural_section():
    from app.answer import rag_needs_web_search
    from app.rerank import retrieve_answer_evidence

    evidence = retrieve_answer_evidence(
        "請說明消防法所有懲處條款",
        top_k=20,
    )

    assert evidence.mode == "structural_section"
    assert evidence.complete is True
    assert evidence.total_matches == 21
    assert len(evidence.hits) == 21
    assert evidence.scope_law_title == "消防法"
    assert evidence.scope_heading == "第六章 罰則"
    assert evidence.hits[0].article_label == "第33條"
    assert evidence.hits[-1].article_label == "第44條"
    assert any(hit.article_label == "第37條" for hit in evidence.hits)
    assert all(hit.law_title == "消防法" for hit in evidence.hits)
    assert all(hit.article_label != "第45條" for hit in evidence.hits)
    assert not rag_needs_web_search(evidence.hits)


def test_conversations_persist_title_and_exchange():
    from app.conversations import (
        create_conversation,
        delete_conversation,
        get_messages,
        list_conversations,
        rename_conversation,
        save_exchange,
    )

    conversation_id = create_conversation()
    assert rename_conversation(conversation_id, "消防設備問題")
    save_exchange(
        conversation_id,
        "管理權人要設置什麼？",
        response={"summary": "找到條文", "results": [{"article_label": "第13條"}]},
    )

    conversations = list_conversations()
    conversation = next(item for item in conversations if item.id == conversation_id)
    assert conversation.title == "消防設備問題"
    assert conversation.last_message_at is not None
    assert conversation.created_at is not None
    messages = get_messages(conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].response["results"][0]["article_label"] == "第13條"

    assert delete_conversation(conversation_id)
    assert all(item.id != conversation_id for item in list_conversations())
