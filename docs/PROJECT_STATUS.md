# Project Status — nfa-fire-law-rag

Date: 2026-09-14
Repository: `C:\Users\james.chang\source\nfa-fire-law-rag`
Branch: `main` at `origin/main`; the tracked baseline is clean before this launcher change.

## Executive summary

The repository is a working Phase 2 proof of concept, not an empty scaffold. The
SQLite-first path already covers discovery, bounded HTTP fetching, NFA URL identity,
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
| Repository | 41 tracked files after this change; `main` is synchronized with `origin/main` after push | Present and maintainable |
| Python package | `app/` with config, models, DB, parser, ingest, search, API, MCP | Substantially implemented |
| Crawler | `app/crawler/{discovery,fetch,nfa_urls}.py` | Implemented, bounded and host-validated |
| Ingestion | `app/ingest.py`, attachment handling, version/hash logic | Implemented with focused follow-up needs |
| Retrieval | `app/search.py` | Implemented SQLite FTS5 + NumPy hybrid path |
| Embedding | `app/embedding.py` | Implemented deterministic hash and optional OpenAI providers |
| Database | `app/db.py`, `app/models.py`, `scripts/init.sql` | SQLite default implemented; PostgreSQL optional |
| API/MCP | `app/api.py`, `app/mcp_server.py` | Implemented PoC search and cited-answer interfaces |
| Browser UI | `app/streamlit_app.py`, `app/conversations.py`, `.streamlit/config.toml`, `pyproject.toml` `ui` extra | Local Streamlit Q&A/evidence interface with SQLite-persisted multi-conversation history, title editing, and deletion |
| Tests | 10 test modules plus fixtures | 40 tests passing |
| Evaluation | `eval/phase2_queries.json`, `app/evaluation.py`, CLI `eval` | Seed evaluation implemented; corpus-dependent |
| Config | `app/config.py`, `.env.example`; local `.env` ignored | Implemented; secrets kept local |
| Docs | `README.md`, `AGENTS.md`, and three `docs/` files | README, full system manual, and operational documentation are present |
| Windows launchers | `scripts/start_streamlit.bat` | Implemented; starts the local UI and opens the browser without crawling or installing |
| Requirements files | No `requirements*.txt`/`.in`; dependencies in `pyproject.toml` | `pyproject.toml` is the source of truth |
| Data | Ignored local `data/nfa_fire_law.db` (~98 MB) and `data/test.txt` | Local/generated; not commit candidates |

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
- Law identity uses normalized NFA URL/`LSID` keys; versions preserve old content
  and identify the current version.
- Parser extracts titles/metadata, removes dynamic page noise, splits formal
  articles and administrative points, and creates a stable semantic content hash.
- Same-host PDF attachments are bounded, extracted when searchable, and reported
  when skipped or failed.
- FTS5 indexing adds CJK n-grams and stores identifiers needed to map hits to chunks.
- SQLite retrieval fuses FTS5 candidates, exact law-title routing, structured legal
  definition signals, text overlap, and NumPy cosine similarity. Hash embeddings
  use a lower provider-specific vector weight; exact article lookup is also present.
- FastAPI health/search/article/law/version/admin endpoints and MCP tools exist.
- A local Streamlit UI supports natural-language queries, law filtering, result
  counts, current-version evidence, scores, source links, and clickable answer
  citations that jump to and expand stable evidence anchors without an API key.
- `scripts/start_streamlit.bat` checks the repository `.venv`, starts Streamlit on
  loopback, and opens the local Q&A page automatically.
- Offline fixtures cover crawler discovery, URL identity, fetch behavior, parsing,
  attachment handling, hashing, embeddings, SQLite/FTS5, and ingestion probing.

### Partially completed

- Incremental sync exists at the law/version/hash level, but scheduling, durable
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
| Ollama hosted web-search key | Configured only in ignored local `.env`; live cloud/web request was not run |
| repository tests | `51 passed, 12 warnings` after the cited-answer, web-fallback, cloud-model, and provider-aware definition-ranking additions |

The warnings were existing dependency/runtime warnings: `datetime.utcnow()` deprecation
from SQLAlchemy-related defaults, the deprecated `sqlite3.version` read used for this
check, and a pytest cache permission warning. They did not fail tests.

## Files changed in this phase

- `AGENTS.md` — new repository working contract with 16 policy categories.
- `README.md` — corrected the documented 2-second throttle, made Windows-safe,
  non-destructive setup/re-embedding guidance primary, and linked the full system
  manual.
- `docs/PROJECT_STATUS.md` — this evidence-backed inventory and completion report.
- `docs/SYSTEM_MANUAL.md` — system architecture, crawler design, installation/startup,
  Streamlit usage, and documentation alignment rules.
- `docs/MIGRATION_PLAN_SQLITE_HYBRID_RAG.md` — Phase 0–10 staged migration plan.
- `app/answer.py` — local/cloud Ollama Gemma answer generation with evidence validation.
- `app/rerank.py` — conditional answer-evidence reranking for comparison/scope questions,
  with deterministic search and failure fallback preserved.
- `app/web_search.py` — bounded Ollama hosted web-search/fetch fallback with HTTPS
  official-domain allowlisting and timestamped provenance.
- `app/config.py`, `.env.example` — local LLM endpoint, model, thinking, timeout,
  temperature, output-limit, and optional web-fallback settings.
- `app/api.py`, `app/mcp_server.py`, `app/streamlit_app.py`, `app/conversations.py` —
  cited-answer wiring plus persisted local conversation history while preserving raw
  search and evidence display.
- `app/models.py` — adds `conversations` and `conversation_messages` tables; SQLite
  `create_all` adds them automatically to an existing local database.
- `tests/test_answer.py`, `tests/test_rerank.py`, `tests/test_web_search.py`,
  `tests/test_streamlit_app.py` — offline answer-layer, reranking, web-fallback, and UI
  integration tests.
- `scripts/start_streamlit.bat` — Windows launcher that stops only the repository's
  prior Streamlit process on the configured local port, waits for the health endpoint,
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
