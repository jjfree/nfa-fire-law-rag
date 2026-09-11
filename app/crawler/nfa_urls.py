from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


LSID_KEYS = {"lsid"}
DATE_KEYS = {"ldate", "date"}


def query_dict_ci(url: str) -> dict[str, str]:
    """Return first query value per key using lowercase keys."""
    parsed = urlparse(url)
    result: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        result.setdefault(key.lower(), value)
    return result


def extract_lsid(url: str) -> str | None:
    value = query_dict_ci(url).get("lsid")
    return value.upper() if value else None


def canonical_source_key(url: str) -> str:
    """Stable identity for NFA laws.

    The legacy NFA system commonly emits the same law with different `ldate`
    values and with `LSID` in inconsistent casing.  `LSID` is the durable law
    identity, so historical dates must not create duplicate `Law` rows.
    """
    parsed = urlparse(url)
    lsid = extract_lsid(url)
    if lsid:
        return f"nfa:lsid:{lsid}"

    query = query_dict_ci(url)
    for key in ("id", "no", "lawid", "uid", "sn", "lawno"):
        value = query.get(key)
        if value:
            return f"{parsed.path.lower()}?{key}={value}"

    # Keep a normalized fallback for non-LSID detail URLs.
    pairs = sorted((k.lower(), v) for k, v in parse_qsl(parsed.query, keep_blank_values=True))
    return urlunparse(
        (
            parsed.scheme.lower(),
            (parsed.netloc or "").lower(),
            parsed.path,
            "",
            urlencode(pairs),
            "",
        )
    )


def build_print_url(url: str) -> str | None:
    """Build the legacy print-view URL for a law when an LSID is present.

    The print view is substantially easier and more stable to parse than the
    mobile/interactive view and contains the complete legal text.
    """
    parsed = urlparse(url)
    lsid = extract_lsid(url)
    if not lsid:
        return None
    query = query_dict_ci(url)
    params = {"lsid": lsid}
    if query.get("ldate"):
        params["ldate"] = query["ldate"]
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            "/GNFA/FLAW/PrintFLAWDAT02.aspx",
            "",
            urlencode(params),
            "",
        )
    )


def is_probable_law_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if extract_lsid(url):
        return any(
            token in path
            for token in (
                "/mobile/law.aspx",
                "/gnfa/flaw/flawdat02.aspx",
                "/gnfa/flaw/printflawdat02.aspx",
                "/lnfa/flaw/flawdoc01.aspx",
            )
        ) or "law" in path
    return any(token in path for token in ("law", "detail", "content", "show", "view"))
