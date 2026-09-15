from app.query_analysis import extract_focus_terms, split_query_facets


def test_inclusion_focus_extraction_is_domain_independent():
    assert extract_focus_terms("是否包含寺廟與教堂？") == ("寺廟", "教堂")
    assert extract_focus_terms("包含哪些？") == ()


def test_composite_query_adds_focused_retrieval_facet():
    facets = split_query_facets("請說明消防列管場所包含哪些？是否包含寺廟？")

    assert "請說明消防列管場所包含哪些" in facets
    assert "是否包含寺廟" in facets
    assert "寺廟" in facets
