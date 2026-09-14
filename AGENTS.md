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
