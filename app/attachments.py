import re
from io import BytesIO
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

ATTACHMENT_HINTS = (".pdf", "download", "attachment", "attach", "file")


def discover_attachment_urls(html: str, base_url: str, allowed_host: str) -> list[str]:
    """Find same-host PDF/download links without treating navigation as attachments."""
    soup = BeautifulSoup(html, "html.parser")
    result: list[str] = []
    seen: set[str] = set()
    for node in soup.find_all(["a", "iframe", "embed", "object"]):
        href = (node.get("href") or node.get("src") or node.get("data") or "").strip()
        if not href:
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        path = parsed.path.lower()
        if parsed.scheme not in ("http", "https"):
            continue
        if (parsed.hostname or "").lower() != allowed_host.lower():
            continue
        if not any(hint in path or hint in url.lower() for hint in ATTACHMENT_HINTS):
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def extract_pdf_text(content: bytes) -> str:
    """Extract text from a text-based PDF; scanned PDFs return an empty string."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(pages)).strip()
