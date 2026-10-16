# Project Status — nfa-fire-law-rag

Date: 2026-10-15
Repository: `C:\Users\james.chang\source\nfa-fire-law-rag`
Branch: `main` at `origin/main`; the tracked baseline was clean before this documentation change.

## Executive summary

The repository is a working Phase 2 proof of concept, not an empty scaffold. The
SQLite-first path already covers discovery, bounded HTTP fetching, source URL identity,
HTML parsing, article/point chunking, attachment text extraction, version-aware
ingestion, SQLite schema creation, FTS5 indexing, deterministic or OpenAI
embeddings, NumPy-assisted hybrid search, FastAPI, MCP, a local Streamlit browser
UI, and offline tests.

The main gap is operational/product completeness rather than a missing core RAG
engine: the repository has limited update/observability hardening and no
requirements file, while the checked-in Windows launcher remains a small local
developer entrypoint rather than an unattended service. A local Ollama/Gemma
answer-generation layer is now implemented, with further evaluation still needed
for answer quality and legal citation coverage.
PostgreSQL/pgvector and Docker artifacts remain as optional residual paths and are
not required for the Windows SQLite target.

## Inventory

| Area | Current evidence | Assessment |
|---|---|---|
| Repository | 76 tracked files before this change; `main` tracks `origin/main` | Present and maintainable |
| Python package | `app/` with config, models, DB, parser, ingest, search, API, MCP | Substantially implemented |
| Crawler | `app/crawler/{discovery,fetch,nfa_urls}.py` | Implemented, bounded and host-validated |
| Ingestion | `app/ingest.py`, attachment handling, version/hash logic | Implemented with focused follow-up needs |
| Retrieval | `app/search.py`, `app/rerank.py` | Implemented SQLite FTS5 + NumPy hybrid path plus scoped structural retrieval for exhaustive chapter queries |
| Embedding | `app/embedding.py` | Implemented deterministic hash and optional OpenAI providers |
| Database | `app/db.py`, `app/models.py`, `scripts/init.sql` | SQLite default implemented; PostgreSQL optional |
| API/MCP | `app/api.py`, `app/mcp_server.py` | Implemented PoC search and cited-answer interfaces with retrieval-mode and coverage metadata |
| Browser UI | `app/streamlit_app.py`, `app/conversations.py`, `app/ui_preferences.py`, `.streamlit/config.toml`, `pyproject.toml` `ui` extra | Local Streamlit Q&A/evidence interface with SQLite-persisted multi-conversation history and display-result count, title editing, deletion, latest-question viewport positioning, and exhaustive-query coverage display |
| Tests | Offline test modules plus fixtures | 119 tests passing |
| Evaluation | `eval/phase2_queries.json`, `app/evaluation.py`, CLI `eval` | Seed evaluation implemented; corpus-dependent |
| Config | `app/config.py`, `.env.example`; local `.env` ignored | Implemented; secrets kept local |
| Docs | `README.md`, `AGENTS.md`, five `docs/` files, versioned screenshots, system-manual PDF, and frontend Word/PDF guides | README, full system manual, frontend user guide, developer notes, editable/print deliverables, and operational documentation are present |
| Windows launchers | `scripts/start_streamlit.bat` | Implemented; safely recognizes repository-owned venv process trees, restarts the local UI, and opens the browser without crawling or installing |
| Requirements files | No `requirements*.txt`/`.in`; dependencies in `pyproject.toml` | `pyproject.toml` is the source of truth |
| Data | Ignored local `data/nfa_fire_law.db` (~128 MiB) and `data/test.txt` | Local/generated; not commit candidates |

Functional directories named `ingestion`, `retrieval`, `database`, `config`, or
`docs` do not all exist as separate folders; their current functionality is located
in the modules and files listed above. No files were deleted or renamed because the
purpose of the existing optional artifacts is clear enough to retain.

### Requested scan coverage

The repository-wide scan covered the requested source and operational areas:

| Requested area | Evidence | Result |
|---|---|---|
| Python/runtime | `pyproject.toml`, `.env.example`, `app/` | Python package and dependency source of truth are present |
| `bat`/`ps1` and requirements | repository root and `scripts/` | One tracked Streamlit launcher; no `requirements*.txt`; dependencies remain in `pyproject.toml` |
| Database/data | `app/db.py`, `app/models.py`, `scripts/init.sql`, ignored `data/` | SQLite default is implemented; local DB and `test.txt` are generated/untracked data |
| Crawler/ingestion | `app/crawler/`, `app/ingest.py`, `app/attachments.py` | Bounded discovery/fetch and version-aware ingestion are implemented |
| Parsing | `app/parser.py`, `tests/fixtures/` | HTML/print normalization and chunk fixtures are present |
| Retrieval/embedding | `app/search.py`, `app/embedding.py`, `app/evaluation.py`, `eval/` | FTS5 + NumPy hybrid PoC and seed evaluation are present |
| API/MCP | `app/api.py`, `app/mcp_server.py` | PoC interfaces are present; admin authentication remains a gap |
| Tests/docs | `tests/`, `README.md`, `AGENTS.md`, `docs/` | Offline tests and this handoff documentation are present |

Assessment labels used below: **已完成** means evidenced by code/tests,
**部分完成** means usable but not operationally complete, **未完成** means a
future capability, **可沿用** means keep as the current extension point, and
**應淘汰** means confirmed for removal. No current file has a confirmed
「應淘汰」判定.

## Completion assessment

### Already completed

- SQLite is the default storage backend and creates the schema plus an FTS5 virtual
  table without a database server.
- Law identity uses normalized source URL/`LSID` keys; versions preserve old content
  and identify the current version.
- Parser extracts titles/metadata, removes dynamic page noise, splits formal
  articles and administrative points, and creates a stable semantic content hash.
- Same-host PDF attachments are bounded, extracted when searchable, and reported
  when skipped or failed.
- FTS5 indexing adds CJK n-grams and stores identifiers needed to map hits to chunks.
- SQLite retrieval fuses FTS5 candidates, exact law-title routing, structured legal
  definition signals, text overlap, and NumPy cosine similarity. Hash embeddings
  use a lower provider-specific vector weight; exact article lookup is also present.
- A query naming one law and one article now normalizes Chinese/Arabic numerals and
  routes to exact current-version lookup. A missing article does not return a
  similarly scored provision from another law; answer metadata and UI cards identify
  `exact_article` results without presenting lookup scores as hybrid similarity.
- Composite inclusion questions are split into focused retrieval facets. Exact named
  objects receive a conservative lexical signal, and the answer-facing merge reserves
  evidence coverage across distinct facets plus the best matching parent statute in the
  bounded candidate set before optional reranking. The answer evidence order promotes
  direct object coverage first and the related parent statute second without changing
  the stored retrieval scores.
- Broad regulatory-topic questions now reserve the directly governing regulation and
  related parent act from a bounded candidate pool. Evidence selection prioritizes
  distinct laws, caps the first fill at two provisions per law, and retains separate
  citations for repeated labels with different content.
- Exhaustive single-law penalty questions now bypass ordinary relevance truncation:
  the answer path detects explicit all/complete/per-article intent, expands penalty
  terminology, scopes to the named law's current `罰則` chapter, excludes deleted-only
  provisions, and returns every matching chunk in legal sequence. Retrieval metadata
  reports the mode, chapter, total count, returned count, and completeness; the
  Streamlit UI makes this visible (for example, `消防法／第六章 罰則，21／21`).
- Answer generation uses model-specific context/output profiles, records Ollama
  completion metadata, retries a detected length truncation once, and reports an
  explicit incomplete state if the retry still fails to finish. The frontend
  diagnostic line shows actual/output-limit token counts and translates raw
  completion reasons into clear Chinese generation states while preserving the
  original metadata for diagnostics.
- Administrative-direction parsing preserves parent section/subsection headings for
  repeated item labels on newly ingested versions. The Streamlit evidence view keeps
  cards in strict citation-number order while retaining the law title on every card.
- Version metadata records an explicit parser revision. Incremental crawl returns
  `reprocess_required` instead of silently accepting stale derived chunks, and a
  dry-run-first `reprocess-current` CLI can rebuild current chunks, embeddings,
  metadata/hash, and FTS without changing legal version numbers or history.
- Hash matches are considered unchanged only for the current version. Source content
  that reverts to a historical hash creates a new chronological current version instead
  of reactivating an old row or leaving the current pointer stale.
- Formal-article parsing keeps line-leading cross-references such as
  `第六條第一項所定...` inside the current provision. The local corpus was rebuilt at
  parser revision 3; `消防法` Article 9 now contains its complete 655-character text.
- FastAPI health/search/article/law/version/admin endpoints and MCP tools exist.
- A local Streamlit UI supports natural-language queries, law filtering, result
  counts, current-version evidence, scores, source links, and clickable answer
  citations that jump to and expand stable evidence anchors without an API key.
- `scripts/start_streamlit.bat` checks the repository `.venv`, starts Streamlit on
  loopback, safely follows a bounded Windows venv parent chain when replacing its own
  prior listener, and opens the local Q&A page automatically.
- Offline fixtures cover crawler discovery, URL identity, fetch behavior, parsing,
  attachment handling, hashing, embeddings, SQLite/FTS5, and ingestion probing.

### Partially completed

- Incremental sync exists at the law/version/hash/parser-revision level, but scheduling, durable
  crawl manifests, resumability, and richer update reporting are not yet a full
  operational workflow.
- Metadata and provenance are stored, and the local UI displays retrieval evidence;
  the Ollama/Gemma answer layer now generates only from current retrieved chunks
  and rejects missing/unknown evidence citations. Answer-facing retrieval conditionally
  uses the default Gemma cloud model to rerank entity comparison and authority/scope questions,
  while raw search remains deterministic. Broader answer-quality evaluation is still needed.
- OpenAI embeddings are supported, but provider/model/dimension compatibility is a
  configuration responsibility and there is no migration command for re-embedding.
- Retrieval has a PostgreSQL branch, but the supported/default acceptance target is
  SQLite; cross-backend parity is not established here.
- Evaluation has seed cases but needs a larger domain-owned question set and a
  repeatable quality threshold.
- API admin crawl has no authentication, as already noted by the README.

### Not completed / future work

- Full update scheduler or unattended Windows task workflow.
- Explicit database migration/versioning tooling beyond `create_all` and the current
  schema.
- Broader answer-quality evaluation and stronger sentence-level citation coverage.
- Production authentication, rate governance, monitoring, and deployment guidance.
- Broader document extraction (for example ODT/DOCX) and a tested reranker.
- A production service, unattended scheduler, or remote deployment; the checked-in
  launcher is intentionally limited to local interactive use.

### Reuse / retire / refactor guidance

| Decision | Items | Guidance |
|---|---|---|
| Reuse directly | `app/config.py`, `app/db.py`, `app/models.py`, `app/parser.py`, `app/embedding.py`, `app/search.py`, `app/streamlit_app.py`, `scripts/start_streamlit.bat`, tests, fixtures | These form the current SQLite-first core and local UI and should be extended narrowly |
| Reuse with focused hardening | `app/ingest.py`, `app/crawler/*`, `app/api.py`, `app/mcp_server.py` | Add observability, update controls, and citation contracts incrementally |
| Retain but keep optional | `Dockerfile`, `docker-compose.yml`, `scripts/init.sql`, PostgreSQL dependencies/branches | Do not delete during this phase; never make them prerequisites |
| No confirmed retirement | No tracked file has an uncertain enough purpose to delete | Preserve and document instead of guessing |
| Likely refactor later | schema migration/versioning, answer-layer quality, operational CLI, backend boundary | Schedule after the baseline is documented and tested |

## Docker/WSL/Linux residual scan

| Residual | Location/evidence | Disposition |
|---|---|---|
| Docker image/build path | `Dockerfile` uses `WORKDIR /app` and installs the optional postgres extra | Retain, mark optional; not used by SQLite validation |
| docker-compose | `docker-compose.yml` starts `pgvector/pgvector:pg16`, mounts `/var/lib/postgresql/data`, and configures a `db` service | Retain, mark optional legacy/dev path; do not invoke |
| PostgreSQL extensions | `scripts/init.sql` creates `vector` and `pg_trgm`; `app/db.py` has the same optional setup | Retain for compatibility; outside the default target |
| Container path | `Dockerfile` `/app`; compose service paths | Documentation-only residual; no Windows runtime dependency |
| Linux-only script | No tracked Linux shell script was found. README contains a macOS/Linux activation example and `bash` code fences | Keep README context but make Windows instructions primary in future edits |
| WSL | No WSL command or config was found in tracked source; README explicitly says WSL is unnecessary | No action; policy is documented in `AGENTS.md` |
| `sudo` | No tracked `sudo` usage was found | None |
| Linux path assumption | Container-only `/app` and `/var/lib/postgresql/data`; no application POSIX path dependency found | Keep isolated to optional container path |

The separate `C:\Users\james.chang\Documents\ChatGPT\nfa-fire-law-rag` folder
contains bootstrap `.bat` files but is not this Git repository and was not modified.

## Local environment checks

All checks below were read-only or in-memory; no system software was installed and
no live crawl was run.

| Check | Result |
|---|---|
| `py --version` | Python 3.12.10 |
| `python --version` | Python 3.12.10 |
| `.venv\\Scripts\\python.exe --version` | Python 3.12.10 |
| `.venv\\Scripts\\python.exe -m pip --version` | pip 26.2.1 from the repository venv |
| Python `venv` import | Passed |
| standalone `sqlite3.exe` | Not available on PATH |
| Python sqlite module | 2.6.0 (reported deprecated module-version attribute) |
| SQLite runtime | 3.49.1; `SELECT sqlite_version()` returned 3.49.1 |
| temporary FTS5 table/query | Passed; one inserted Chinese legal row was found |
| NumPy | 2.5.3; float32 array and norm calculation passed |
| Streamlit UI dependency | `1.63.0` installed in repository `.venv` |
| Ollama hosted web-search key | Configured only in ignored local `.env`; a bounded 2026-10-15 live query returned Ministry of the Interior sources after adding `moi.gov.tw` to the allowlist |
| repository tests | `95 passed, 30 warnings` after exhaustive-section retrieval, evidence coverage, prompt-source compaction, latest-question viewport positioning, and prior parser/versioning coverage |
| current repository tests | `101 passed, 29 warnings` on 2026-10-13 with `--basetemp data/pytest_ui_pref_20261013`; includes UI preference persistence and validation |
| 2026-10-15 repository tests | `119 passed, 29 warnings` with `--basetemp data/pytest-final`; includes explicit `/web` parsing, forced search over high-scoring structural evidence, failure states, API/MCP/Streamlit dispatch, and mode-specific UI status. Default sandbox temp was not writable, so the rerun used ignored `data/`. |
| 2026-10-15 allowlist regression tests | `120 passed, 29 warnings` with `--basetemp data/pytest-web-allowlist-full`; focused test verifies the exact central-authority query retains a Ministry of the Interior result and rejects a private repost. |
| 2026-10-15 automatic announcement search | A saved non-`/web` query for the central-authority announcement returned `web_search_status=not_needed` despite top local score 0.645; the answer gate now recognizes explicit authority-announcement requests before relying on that score. |
| 2026-10-15 repository tests after automatic announcement search | `124 passed, 29 warnings` with `--basetemp data/pytest-auto-announcement-full`; focused tests cover source-intent classification, auto search with high-scoring local hits, ordinary local-only queries, and accurate UI caption. |
| 2026-10-16 precision search probe | Bounded live searches found a 2025-09-16 Ministry amendment announcement ahead of the 2024-03-07 original announcement; a latest-law query found the current full-text Fire Services Act page on `law.moj.gov.tw` with a 2024-11-29 amendment date. |
| 2026-10-16 repository tests after precision search | `131 passed, 29 warnings` with `--basetemp data/pytest-precision-full`; includes focused re-query, official-domain deduplication, source-date parsing/order, historical-year behavior, fallback on secondary search failure, answer provenance, and UI date display. Ruff passed on changed Python files. |
| 2026-10-16 named-article regression | `134 passed, 29 warnings` with `--basetemp data/pytest_article_20261016c`; confirms `請說明消防法第四十二條` resolves to the stored current `消防法` / `第42條`, including Chinese/Arabic subarticle labels and UI mode display. No crawl or local database rewrite was needed. |
| Ruff (changed Python files) | Passed |
| Ruff (whole repository) | Three pre-existing findings remain: one `B008` in `app/cli.py` and import ordering in two crawler modules |

The warnings were existing dependency/runtime warnings: `datetime.utcnow()` deprecation
from SQLAlchemy-related defaults, the deprecated `sqlite3.version` read used for this
check, and a pytest cache permission warning. They did not fail tests.

## Files changed in this phase

On 2026-10-16, a named-article question using Chinese numerals failed to match
the stored Arabic-number article label. Exact-title and single-article queries now
normalize the article number and fetch only matching current-version chunks.
The query `請說明消防法第四十二條` returns `消防法` / `第42條` from the ignored local
database. Answer and UI metadata mark the result as `exact_article`; the evidence
card does not present fixed lookup scores as hybrid relevance. Offline regression
tests, README, system manual and PDF, frontend guide and its Word/PDF editions,
and the migration plan were aligned. Existing screenshots depict general hybrid
results and remain accurate; none shows a named-article query. `AGENTS.md`,
`.env.example`, and `pyproject.toml` were unaffected because maintenance rules,
settings, dependencies, and entrypoints did not change.

The 2026-10-15 change adds a leading `/web` directive and `web_mode=force` to answer
entrypoints. The answer layer attempts official web search even when local evidence
scores highly or structural retrieval is complete; server enablement, key, HTTPS
allowlist, relevance filtering, and citation validation remain in force. Streamlit
reports forced-search outcomes without describing them as local RAG insufficiency.
The existing guide screenshots show ordinary automatic queries and remain accurate;
no screenshot depicts the new forced-search state. README, system manual, frontend
guide, project status, system-manual PDF, and frontend Word/PDF were aligned.
`AGENTS.md`, `.env.example`, `pyproject.toml`, and the migration plan were unaffected
because platform rules, configuration keys, dependencies, and roadmap milestones did
not change. No live web search or crawl was run.

A later 2026-10-15 check of `/web 一定規模以上之建築物的中央主管機關公告?`
found a saved `web_search_mode=force`, `web_search_status=no_results` response. A bounded
live probe returned a `www.moi.gov.tw` announcement and `ws.moi.gov.tw` download, both
excluded by the previous default domain allowlist. The default allowlist and
`.env.example` now include `moi.gov.tw`; a second bounded probe retained both
official sources. The focused regression test uses mocked HTTP and stays offline.

A subsequent check found that the same announcement request without `/web` skipped web
search because the high local retrieval score passed the automatic fallback gate.
The answer layer now treats explicit authority-announcement requests as source
requests, attempts official web search in auto mode, and keeps ordinary high-scoring
law questions local. Streamlit auto-mode captions now report search outcomes without
assuming that low RAG confidence triggered the search. Frontend guide text and
Word/PDF editions, system manual and PDF, README, and project status were aligned;
existing screenshots show ordinary local queries and remain accurate. Configuration,
dependencies, agent rules, and migration milestones did not change.
A bounded live probe with the exact query and a 0.645 local score returned
`web_search_mode=auto`, `web_search_status=used`, and two official web results;
answer generation was stubbed during this trigger check.

On 2026-10-16, the same announcement query initially favored the 113-year original
notice because the provider's top-five result window omitted the later amendment.
The web client now uses one bounded follow-up search based on the first official
result's formal title, or a current full-text query for latest-law requests. It
deduplicates allowed URLs, fetches at most the configured three pages, extracts
only explicit official publication/amendment dates, and orders dated evidence
newest first. A follow-up failure retains initial results; an explicit historical
year suppresses the latest-version follow-up. The answer prompt distinguishes
source dates from effective dates and retrieval time, and warns when latest-version
completeness cannot be established. API/MCP/Streamlit web evidence now carries
`source_date` and `source_date_label` when available. README, system manual,
frontend guide, generated PDFs/Word, and project status were aligned; existing
screenshots remain accurate because they show ordinary local evidence rather than
Web date metadata. No configuration key, dependency, crawler, or SQLite contract
changed.

- `AGENTS.md` — new repository working contract with 16 policy categories.
- `README.md` — corrected the documented 2-second throttle, made Windows-safe,
  non-destructive setup/re-embedding guidance primary, and linked the full system
  manual.
- `docs/PROJECT_STATUS.md` — this evidence-backed inventory and completion report.
- `docs/SYSTEM_MANUAL.md` — system architecture, crawler design, installation/startup,
  Streamlit usage, and documentation alignment rules.
- `scripts/build_system_manual_pdf.py` — reproducible offline PDF builder using the
  Markdown manual as the source of truth.
- `output/pdf/nfa-fire-law-rag-system-manual.pdf` — versioned, rendered system-manual
  PDF for printing and sharing.
- `docs/FRONTEND_USER_GUIDE.md` and `docs/assets/frontend-user-guide/` — frontend-only
  instructions and current Streamlit screenshots.
- `scripts/build_frontend_user_guide.py` — synchronized Word/PDF frontend-guide builder.
- `output/docx/nfa-fire-law-rag-frontend-user-guide.docx` and
  `output/pdf/nfa-fire-law-rag-frontend-user-guide.pdf` — editable and print/share
  editions of the frontend user guide.
- `docs/MIGRATION_PLAN_SQLITE_HYBRID_RAG.md` — Phase 0–10 staged migration plan.
- `app/answer.py` — local/cloud Ollama Gemma answer generation with evidence validation.
- `app/rerank.py` — conditional answer-evidence reranking for comparison/scope questions,
  with deterministic search and failure fallback preserved; composite questions now
  merge source-diverse, facet-covering evidence.
- `app/query_analysis.py` — conservative composite-facet and explicit inclusion-target
  extraction shared by retrieval and web-result validation.
- `app/web_search.py` — bounded Ollama hosted web-search/fetch fallback with HTTPS
  official-domain allowlisting, timestamped provenance, and explicit-target relevance
  filtering before evidence numbering.
- `app/config.py`, `.env.example` — local LLM endpoint, model, thinking, timeout,
  temperature, output-limit, and optional web-fallback settings.
- `app/api.py`, `app/mcp_server.py`, `app/streamlit_app.py`, `app/conversations.py` —
  cited-answer wiring plus persisted local conversation history while preserving raw
  search and evidence display.
- `app/models.py` — adds `conversations` and `conversation_messages` tables; SQLite
  `create_all` adds them automatically to an existing local database.
- `tests/test_answer.py`, `tests/test_query_analysis.py`, `tests/test_rerank.py`, `tests/test_web_search.py`,
  `tests/test_streamlit_app.py` — offline answer-layer, reranking, web-fallback, and UI
  integration tests.
- `scripts/start_streamlit.bat` — Windows launcher that stops only the repository's
  prior Streamlit process tree on the configured local port (including a base-Python
  listening child beneath the repository venv parent), waits for the health endpoint,
  and then opens the local Q&A URL.
- `.streamlit/config.toml` — disables Streamlit usage statistics for local-only operation.
- `tests/test_streamlit_app.py`, `tests/test_sqlite_backend.py` — UI response/provenance
  tests and offline conversation persistence coverage without requiring Streamlit at
  import time.
- `tests/test_start_streamlit_bat.py` — offline checks for launcher paths, loopback binding, and no crawl/install behavior.
- `pyproject.toml` — adds the optional `ui` dependency extra for Streamlit.

No existing application code, database contents, or optional Docker/PostgreSQL
artifacts were deleted; the new UI module and its test were added separately.

## Recommended next phase

The browser UI is now the recommended local interaction path. The next focused
implementation remains **Phase 1: Windows runtime and repeatable local commands**,
especially a read-only diagnostics command, followed by broader answer-quality and
citation evaluation. Keep the UI local-only until authentication and deployment
controls are reviewed. Likely files include:

- `pyproject.toml` (only if a CLI entrypoint or dependency metadata needs a small
  adjustment);
- `app/cli.py` (diagnostics/reporting command, no crawl by default);
- optionally `scripts/` for a small `.bat` or `.ps1` wrapper;
- focused tests under `tests/`.

Do not begin with a full crawl, PostgreSQL migration, Docker setup, or broad schema
rewrite. Preserve the current passing test baseline first.

## Documentation governance

`docs/SYSTEM_MANUAL.md` is now the user-facing and operator-facing source for the
architecture, crawler design, installation/startup, and Streamlit usage. Its
maintenance section points to the normative documentation-alignment rules in
`AGENTS.md`. `README.md` remains the short entry point; this file remains the
evidence-backed status snapshot; and `docs/MIGRATION_PLAN_SQLITE_HYBRID_RAG.md`
remains the staged roadmap.

`docs/FRONTEND_USER_GUIDE.md` is the frontend-user source of truth. Its versioned
screenshots and generated Word/PDF editions must be updated together whenever a
Streamlit-visible control, default, workflow, answer/evidence state, or launcher
instruction changes. The build and page-inspection contract is recorded in
`AGENTS.md`.

Future changes that affect behavior, commands, configuration, data contracts,
provenance, security boundaries, or validation must follow the alignment matrix
in `AGENTS.md` and update the affected documents in the same change. Pure
refactors that do not alter observable behavior do not require a full manual
rewrite, but must still preserve tests and document any changed implementation
contract.

The minimum delivery check is `.venv\\Scripts\\python.exe -m pytest -q`, together
with a review of the manual's installation commands and the relevant
`PROJECT_STATUS` completion/risk entries. The `AGENTS.md` checklist also requires
explicitly recording which documents were aligned and which were not affected.
