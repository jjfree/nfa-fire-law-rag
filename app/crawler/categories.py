from __future__ import annotations

from collections.abc import Iterable


NFA_CATEGORY_URLS = {
    "A001": "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A001",
    "A002": "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002",
    "A003": "https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A003",
}


def category_urls_for_codes(codes: Iterable[str]) -> list[str]:
    """Resolve supported NFA category codes while preserving input order."""
    urls: list[str] = []
    seen: set[str] = set()
    for raw_code in codes:
        code = raw_code.strip().upper()
        if not code:
            continue
        if code not in NFA_CATEGORY_URLS:
            supported = ", ".join(sorted(NFA_CATEGORY_URLS))
            raise ValueError(f"Unsupported NFA category {raw_code!r}; supported: {supported}")
        if code not in seen:
            seen.add(code)
            urls.append(NFA_CATEGORY_URLS[code])
    if not urls:
        raise ValueError("At least one NFA category code is required")
    return urls
