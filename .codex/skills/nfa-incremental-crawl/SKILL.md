---
name: nfa-incremental-crawl
description: Incrementally crawl Taiwan NFA fire-law categories A001, A002, and A003 and update the local SQLite/FTS5/embedding RAG. Use when the user asks to 增量爬取 A001/A002/A003, sync NFA fire laws, or refresh the fire-law corpus; do not use for unrelated web crawling or a full crawl of other categories.
metadata:
  short-description: 增量同步 NFA A001/A002/A003 法規到 RAG
---

# NFA A001/A002/A003 增量同步

Use the repository's existing Windows-first crawler and ingestion pipeline. The
supported target is the local SQLite RAG in this repository; do not introduce
Docker, WSL, PostgreSQL, a hosted database, or a new crawler for this workflow.

## Trigger and scope

Treat prompts such as `請增量爬取A001/A002/A003` as an instruction to sync
exactly these NFA category pages:

- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A001`
- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A002`
- `https://law.nfa.gov.tw/MOBILE/category.aspx?typecode=A003`

The sync is idempotent at law/version/content-hash level: unchanged laws should
be reported as `unchanged`, while changed laws create a new current version and
preserve the prior version. A003 attachment indicators can lead through an
attachment-list HTML page before the actual same-host PDF; the application
handles that bounded hop and records skipped/failed attachments in metadata.

## Run

From the repository root, use the repository virtual environment:

```powershell
.venv\Scripts\python.exe -m app.cli crawl --categories A001,A002,A003
```

Use `--max-laws N` only when the user explicitly requests a small smoke run.
Do not substitute `probe` for the requested update: `probe` is read-only and
does not write the RAG. Do not run categories outside A001/A002/A003 unless the user
explicitly names them.

The crawler is deliberately sequential and bounded by the configured delay,
timeout, same-host validation, attachment byte/page limits, and 403/429 stop
behavior. If the source returns 403/429, stop and report it; do not aggressively
retry or bypass the block. Do not expose cookies, authorization headers, or
environment contents.

## Verify and report

After a successful run, report the JSON result by category, including discovered
and selected counts, inserted/unchanged/error counts, and notable attachment
parsed/skipped/error outcomes. If an individual law fails, keep the other laws'
results and surface the failed law title/source URL.

Run the focused offline tests when code has changed:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_categories.py tests\test_attachments.py
```

Do not claim that the RAG was updated if the command only produced a probe or if
the database write failed. The answer-facing corpus must retain law title,
article/chunk label, version, current state, source URL, and attachment outcome.
