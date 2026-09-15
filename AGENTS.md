# AGENTS.md — NFA Fire Law RAG

This file is the working contract for agents and contributors in this repository.
It records the current project direction and the safe Windows-first boundaries for
future changes.

## 1. Project Goal

Build a maintainable Taiwan fire-law knowledge base and retrieval system covering
fire prevention, fire investigation, hazardous materials, fire-safety equipment,
and related subordinate regulations. Answers must be grounded in preserved source
text and must expose the law title, article/chunk label, version, and source URL.

The default target is a directly runnable Windows 10/11 installation using Python,
SQLite, SQLite FTS5, NumPy, and a hybrid lexical/semantic retrieval pipeline.

## 2. Scope and non-goals

- Keep the existing crawler, parser, ingestion, versioning, API, MCP, and test
  surfaces unless a focused change is required.
- Prefer small, reversible changes over a broad rewrite.
- Do not add a hosted database, container runtime, Linux subsystem, or system-level
  service to satisfy a normal development task.
- Do not perform a full crawl or bulk download during routine validation.

## 3. Architecture

The intended flow is:

`NFA source → discovery/fetch → HTML/PDF parsing → normalized law/version/chunk
records → SQLite + FTS5 + float32 embeddings → hybrid search → FastAPI/MCP`

Relevant modules are under `app/`: `crawler/` for source access,
`parser.py`/`attachments.py` for normalization and extraction, `ingest.py` for
version-aware ingestion, `db.py`/`models.py` for persistence, `embedding.py` for
vector generation, `search.py` for retrieval, and `api.py`/`mcp_server.py` for
interfaces.

The PostgreSQL/pgvector path remains an optional compatibility path in the current
codebase. It is not part of the default Windows runtime and must not become a
prerequisite for SQLite work.

## 4. Windows-only constraints

- Write paths with `pathlib.Path` or other platform-neutral Python APIs.
- Use Windows-compatible commands and `.venv\\Scripts\\...` examples in Windows
  documentation.
- Do not assume `/`, `/app`, `/data`, POSIX permissions, symlinks, `sudo`, or a
  POSIX shell is available.
- Keep paths configurable and relative to the repository or the configured SQLite
  URL where practical.

## 5. No Docker / No WSL rule

Docker, docker-compose, WSL, Linux containers, and Linux-only tooling are not part
of the supported default architecture. Existing `Dockerfile`, `docker-compose.yml`,
PostgreSQL settings, and `scripts/init.sql` are retained as optional legacy/dev
artifacts for now. Do not delete them without an explicit decision and migration
record; do not document them as required for SQLite use.

Do not install Docker, WSL, PostgreSQL, system packages, or administrator-level
software as part of this project.

## 6. Python environment conventions

- Supported Python is `>=3.11`; validate with the repository-local `.venv` first.
- Prefer `python -m pip` and `python -m pytest` from `.venv`.
- Do not install dependencies automatically during inspection or tests.
- Keep runtime dependencies in `pyproject.toml`; keep development dependencies in
  the `dev` extra. The `postgres` extra is optional.
- Do not commit `.env`, `.venv/`, caches, credentials, or generated local data.

## 7. SQLite conventions

- SQLite is the default and must work without a server.
- Keep the database URL configurable; the normal local file is
  `data/nfa_fire_law.db`.
- Keep foreign-key enforcement enabled and use transactions for schema/data changes.
- Preserve law identity, versions, current-version state, chunks, metadata, source
  URLs, timestamps, and content hashes.
- Store SQLite embeddings as compact float32 bytes and validate dimensions before
  retrieval or persistence.
- Never use the real local database for destructive test setup; use a temporary or
  test database.

## 8. FTS5 conventions

- `law_chunks_fts` is the SQLite lexical index and must represent current law
  versions only when rebuilt by application code.
- Keep FTS values traceable through `chunk_id`, `law_id`, and `version_id`.
- Use parameterized MATCH queries and keep user query construction safe.
- Preserve the CJK character n-gram strategy unless a replacement is tested against
  Chinese legal queries and the existing fixtures.

## 9. NumPy vector retrieval conventions

- Use NumPy cosine similarity for the SQLite semantic path.
- Use `float32` storage/working arrays where possible and guard zero norms.
- The configured embedding dimension must be consistent for stored chunks and query
  vectors.
- The default hash embedder is a deterministic no-key PoC; it is not equivalent to
  a trained multilingual model. Changing providers requires re-embedding all chunks.

## 10. Data directory conventions

- `data/` is local/generated and ignored by Git.
- Preserve raw law text, normalized metadata, content hashes, version numbers,
  retrieval URLs, and attachment reports needed for auditability.
- Do not commit the local SQLite database, downloaded attachments, crawl dumps, or
  secrets. Keep small, intentional fixtures under `tests/fixtures/` when needed.
- Do not delete or overwrite existing data during an inspection task.

Files that must not be committed to Git include `.env`, `.venv/`, `__pycache__/`,
`.pytest_cache/`, `.ruff_cache/`, coverage output, SQLite database files, downloaded
attachments, crawl dumps, API keys, and other generated or secret material. Keep
the existing `.gitignore` aligned with this list.

## 11. Test requirements

- Run the repository test suite after code changes: `.venv\\Scripts\\python.exe -m pytest -q`.
- Keep tests deterministic, offline, and independent of Docker, WSL, PostgreSQL,
  external DNS, and API keys.
- Add or update focused fixtures/tests for parser, crawler URL normalization,
  ingestion/version behavior, SQLite/FTS5, embeddings, and retrieval changes.
- A live probe is explicitly networked and must stay small; it is not a replacement
  for fixture-based tests.

## 12. Logging requirements

- Report crawl, retry, skip, parse, attachment, and ingestion outcomes with enough
  context to diagnose a single law without exposing secrets.
- Include stable source identity and URL context in operational reports.
- Never log API keys, authorization headers, cookies, or full environment contents.
- Prefer structured/JSON-compatible result fields for CLI/API reports.

## 13. Crawl and update rules

- Respect the configured allowed host, TLS verification, timeout, retry, and delay.
- Keep crawling single-threaded and bounded during development.
- Stop on HTTP 403/429 rather than aggressively retrying.
- Prefer stable NFA print views when configured, but preserve the original source URL.
- Use stable `LSID` identity where available; unchanged content must not create a new
  version or redo embeddings. Changed content creates a new current version while
  preserving the old version.
- Same-host attachments are bounded by configured byte/page limits; skipped or
  failed attachments are reported without aborting the whole law unless access is
  explicitly blocked.

## 14. Citation and traceability rules

Every answer-facing result must retain enough provenance to cite:

- law title and stable source identity;
- article/heading/chunk label;
- version number and current/version state;
- original source URL and, when useful, retrieved URL;
- content/version timestamps and hash where an audit needs them.

Do not silently merge text from different law versions or return an uncited legal
claim from a retrieval result.

## 15. Security and configuration

- `.env.example` documents settings; `.env` is local-only and ignored.
- Keep the admin crawl endpoint protected or local-only before any public deploy.
- Treat source HTML, PDFs, and retrieved text as untrusted input.
- Keep TLS certificate verification enabled. Validate same-host URLs before fetching.
- Do not add credentials, permissive production defaults, or arbitrary file/network
  access while doing project inventory work.

## 16. Git and change hygiene

- Preserve existing files whose purpose is uncertain; document the uncertainty
  instead of deleting or renaming them.
- Keep generated files and local caches out of commits.
- Before changing code, inspect the worktree and avoid overwriting unrelated user
  changes.
- Keep changes reviewable and scoped. A project-status/documentation task should not
  trigger a large code refactor.
- For this repository, the user authorizes pushing scoped changes to
  `origin/main` without repeated confirmation. Verify the remote and branch before
  pushing, and run the relevant tests first; this authorization does not apply to
  other repositories or remotes.
- Record residual Docker/WSL/Linux/PostgreSQL artifacts and their disposition in
  `docs/PROJECT_STATUS.md`.

## 17. Documentation alignment requirements

Documentation changes are driven by impact. A change that affects user operation,
data contracts, source rules, execution commands, security boundaries, or
validation must align the affected documents in the same change. A pure internal
refactor that does not change observable behavior does not require a full manual
rewrite, but it must preserve tests and document any changed implementation
contract.

The document responsibilities are:

| Document | Role | Update when |
|---|---|---|
| `docs/SYSTEM_MANUAL.md` | User/operator manual for architecture, crawler design, installation, startup, UI, and operations | Behavior, operation, architecture, configuration, data model, or security boundary changes |
| `docs/FRONTEND_USER_GUIDE.md` plus `output/docx/nfa-fire-law-rag-frontend-user-guide.docx` and `output/pdf/nfa-fire-law-rag-frontend-user-guide.pdf` | Frontend-only user instructions with versioned screenshots and synchronized Word/PDF editions | Streamlit-visible behavior, wording, controls, defaults, answer/evidence states, conversation handling, or launcher workflow changes |
| `README.md` | Short project entry point and quick start | Initial setup, main entrypoint, required commands, or supported scope changes |
| `AGENTS.md` | Developer and agent working contract | Platform, data safety, testing, Git, architecture, or maintenance rules change |
| `docs/PROJECT_STATUS.md` | Evidence-backed status, risks, test baseline, and residual disposition | Feature status, test baseline, documentation inventory, or residual disposition changes |
| `docs/MIGRATION_PLAN_SQLITE_HYBRID_RAG.md` | Staged roadmap and unfinished work | Milestones, priorities, or architecture decisions change |
| `.env.example` | Copyable configuration contract | A setting is added, removed, renamed, or its default changes |
| `pyproject.toml` | Python version, dependencies, extras, and entrypoints source of truth | Dependency, optional extra, entrypoint, or supported-version changes |

Use this alignment matrix before delivery:

| Change type | Required alignment | Suggested validation |
|---|---|---|
| Crawler URL, selector, pacing, or attachment policy | System manual crawler/troubleshooting sections; `.env.example`; README crawl instructions | Crawler/parser/attachment fixtures and a small live probe |
| Schema, versioning, FTS5, or embedding | System manual data/retrieval sections; migration plan; project status | SQLite/FTS5/ingestion/version tests; never use the real database for destructive test setup |
| Search, rerank, answer, or citation behavior | System manual retrieval/UI sections; README embedding/answer notes | Search/answer/rerank/web tests; inspect provenance and citations |
| FastAPI or MCP contract | System manual API/MCP section; README API/MCP notes | API/MCP smoke tests and updated tool/field inventory |
| Streamlit UI or launcher | System manual startup/UI sections; frontend user guide, affected screenshots, Word/PDF editions; README UI notes; project status inventory | UI/launcher tests; verify loopback binding and persistence; inspect every rendered manual page |
| Configuration, dependency, or installation workflow | System manual installation/configuration sections; `.env.example`; `pyproject.toml`; README | Run commands with the repository-local `.venv` |
| Security, public deployment, or data-use policy | System manual boundary/security sections; this contract; README warnings | Check host allowlist, TLS, authentication, and that secrets are not in Git |

Before a pull request or delivery, confirm:

- User commands, URLs, UI behavior, API/MCP fields, configuration keys, and defaults are documented when changed.
- Law identity, current-version behavior, chunk structure, FTS5, embedding dimensions, and provenance remain documented and tested when changed.
- New network, credential, host, attachment, retry, or public-service behavior is reflected in the security and crawler documentation.
- `.venv\\Scripts\\python.exe -m pytest -q` passes.
- Windows-local `.venv` commands remain the primary supported examples.
- Docker, WSL, or PostgreSQL have not accidentally become prerequisites for the SQLite default.
- `docs/PROJECT_STATUS.md` reflects the current completion, risk, test, and residual entries.
- The change description lists documents aligned and documents intentionally unaffected.

The versioned PDF `output/pdf/nfa-fire-law-rag-system-manual.pdf` is a deliberate
user-facing artifact, not disposable local data. `docs/SYSTEM_MANUAL.md` remains
its single source of truth. When the manual changes, run the bundled-runtime
command below, inspect every rendered page, and commit the Markdown, generator,
and PDF together:

```powershell
$pdfPython = "C:\\Users\\james.chang\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe"
& $pdfPython scripts\\build_system_manual_pdf.py
```

Do not hand-edit the PDF or update only the PDF. If the PDF layout changes,
re-render it and verify that Chinese glyphs, tables, code blocks, page numbers,
and section transitions remain readable before delivery.

The frontend guide has five synchronized, versioned source/output surfaces:

- `docs/FRONTEND_USER_GUIDE.md` is the text source of truth.
- `docs/assets/frontend-user-guide/` contains the current UI screenshots.
- `scripts/build_frontend_user_guide.py` builds both deliverable formats.
- `output/docx/nfa-fire-law-rag-frontend-user-guide.docx` is the editable edition.
- `output/pdf/nfa-fire-law-rag-frontend-user-guide.pdf` is the print/share edition.

When Streamlit-visible behavior or the launcher workflow changes, update the
affected Markdown sections and screenshots, rebuild both outputs, inspect every
rendered DOCX and PDF page, and commit all affected files together:

```powershell
$artifactPython = "C:\Users\james.chang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $artifactPython scripts\build_frontend_user_guide.py --format all
```

Do not hand-edit either generated edition. A pure internal refactor with no
visible UI or workflow effect does not require replacing screenshots.
