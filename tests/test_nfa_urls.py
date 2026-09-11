from app.crawler.nfa_urls import build_print_url, canonical_source_key, extract_lsid


def test_lsid_is_case_insensitive_and_stable_across_dates():
    a = "https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL005059&ldate=20210101"
    b = "https://law.nfa.gov.tw/mobile/law.aspx?lsid=fl005059&LDATE=20240101"
    assert extract_lsid(a) == "FL005059"
    assert canonical_source_key(a) == "nfa:lsid:FL005059"
    assert canonical_source_key(a) == canonical_source_key(b)


def test_print_url_preserves_lsid_and_optional_date():
    url = "https://law.nfa.gov.tw/MOBILE/law.aspx?LSID=FL005066&ldate=19970402"
    assert build_print_url(url) == (
        "https://law.nfa.gov.tw/GNFA/FLAW/PrintFLAWDAT02.aspx?lsid=FL005066&ldate=19970402"
    )
