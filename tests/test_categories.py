import pytest

from app.crawler.categories import category_urls_for_codes


def test_category_urls_for_codes_normalizes_and_deduplicates():
    assert category_urls_for_codes([" a001 ", "A002", "A003", "A002"]) == [
        "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A001",
        "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002",
        "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A003",
    ]


def test_category_urls_for_codes_rejects_unknown_code():
    with pytest.raises(ValueError, match="Unsupported NFA category"):
        category_urls_for_codes(["A999"])
