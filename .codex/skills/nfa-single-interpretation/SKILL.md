---
name: nfa-single-interpretation
description: Import one user-supplied Taiwan NFA FINTQRY04 official interpretation URL or matching saved PDF into this project's SQLite, FTS5, and embedding index. Use for 「將此消防署函釋 URL／PDF 加入索引」; do not use for category crawls or arbitrary sites.
metadata:
  short-description: 單篇消防署函釋加入本機 RAG
---

# 單篇消防署函釋索引

Use this repository's `scripts/add_nfa_interpretation.py` for exactly one user-provided `https://law.nfa.gov.tw/GNFA/FINT/FINTQRY04.aspx?...EID=...` URL. The script validates the host, page path and stable `EID`, performs at most one GET without redirects or retries, requires the requested document number and body in the page, and then versions it in the configured SQLite database. It never follows links, fetches attachments, paginates, or crawls a category.

From the repository root:

```powershell
.venv\Scripts\python.exe scripts\add_nfa_interpretation.py '<URL>'
```

On PowerShell, wrap the full URL in single quotes so `&` remains part of the URL. Success is `status=inserted` or `status=unchanged`; `inserted` includes the new version and chunk count. The source page is indexed in the existing FTS5 and vector retrieval path with source category `消防署函釋`. Its original URL, `EID`, document number, content hash, and retrieved URL are preserved.

For a network-free import of an official page already saved by the user, use `--html-file <path>`. The script still requires the matching document number and body. `--preview` parses without a database write. Do not use an unrelated copy, a search snippet, or generated text as page content.

For a user-supplied official print PDF, use the same URL with `--pdf-file <path>`. This is fully offline: inspect its visible issuer, document number, date, and searchable text before writing. Preserve the user file untouched; the script keeps content-addressed copies under ignored `data/source_pdfs/` and `app/static/local-pdfs/`. The PDF page number becomes the chunk label, and answer evidence links to that local PDF page while retaining the official URL. If text extraction is insufficient, report that OCR is needed; never invent body text. Use `--preview` to check before import. Do not commit the PDF or local SQLite database.

```powershell
.venv\Scripts\python.exe scripts\add_nfa_interpretation.py '<URL>' --pdf-file 'C:\path\to\official.pdf' --preview
.venv\Scripts\python.exe scripts\add_nfa_interpretation.py '<URL>' --pdf-file 'C:\path\to\official.pdf'
```

If the site returns HTTP 403/429, redirects to a challenge, times out, or the parser cannot confirm the page, stop and report the error. Do not retry, rotate identity, automate a browser, or claim that the index was updated. Ask for an official saved HTML page or source-supported access path if needed. Never run the category crawler to compensate for a failed single-page import.

After code changes, run `.venv\Scripts\python.exe -m pytest -q`. For a normal one-page import, report the script JSON and the source URL; no full crawl is needed.
