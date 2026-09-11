from dataclasses import dataclass

from app.streamlit_app import build_response


@dataclass
class FakeHit:
    law_title: str
    article_label: str | None
    heading: str | None
    content: str
    source_url: str
    version_no: int
    vector_score: float
    lexical_score: float
    hybrid_score: float


def test_build_response_preserves_provenance_and_scores():
    response = build_response(
        "管理權人消防安全設備",
        [
            FakeHit(
                law_title="消防法",
                article_label="第13條",
                heading=None,
                content="管理權人應依規定設置消防安全設備。",
                source_url="https://law.nfa.gov.tw/test",
                version_no=2,
                vector_score=0.91,
                lexical_score=1.0,
                hybrid_score=0.94,
            )
        ],
    )

    assert response["results"][0]["law_title"] == "消防法"
    assert response["results"][0]["article_label"] == "第13條"
    assert response["results"][0]["version_no"] == 2
    assert response["results"][0]["source_url"].startswith("https://")
    assert response["results"][0]["hybrid_score"] == 0.94


def test_build_response_handles_empty_retrieval():
    response = build_response("不存在的查詢", [])

    assert response["results"] == []
    assert "沒有找到" in response["summary"]
