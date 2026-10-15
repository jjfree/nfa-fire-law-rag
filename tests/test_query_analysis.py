from app.query_analysis import (
    extract_focus_terms,
    is_broad_regulatory_query,
    requests_official_announcement,
    split_query_facets,
)


def test_inclusion_focus_extraction_is_domain_independent():
    assert extract_focus_terms("是否包含寺廟與教堂？") == ("寺廟", "教堂")
    assert extract_focus_terms("包含哪些？") == ()


def test_composite_query_adds_focused_retrieval_facet():
    facets = split_query_facets("請說明消防列管場所包含哪些？是否包含寺廟？")

    assert "請說明消防列管場所包含哪些" in facets
    assert "是否包含寺廟" in facets
    assert "寺廟" in facets


def test_broad_regulatory_query_requires_topic_scope_without_article() -> None:
    assert is_broad_regulatory_query("請再次說明消防安全設備檢修申報相關規定")
    assert not is_broad_regulatory_query("請說明消防安全設備檢修及申報辦法第5條")


def test_official_announcement_request_needs_source_beyond_law_text():
    assert requests_official_announcement("一定規模以上之建築物的中央主管機關公告?")
    assert requests_official_announcement("請搜尋一定規模以上之建築物的中央主管機關公告")
    assert requests_official_announcement("內政部的最新公告在哪裡？")
    assert not requests_official_announcement("消防法第13條的規定為何？")
    assert not requests_official_announcement("消防法對公告程序有何規定？")
