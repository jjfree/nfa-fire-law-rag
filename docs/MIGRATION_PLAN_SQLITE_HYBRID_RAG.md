# Migration Plan — SQLite Hybrid RAG on Windows

This is a staged, reversible plan for finishing the Windows-first Taiwan fire-law
RAG system without a large rewrite. It assumes the current repository baseline:
SQLite is the default, FTS5 and NumPy hybrid search already exist, the crawler is
bounded, and the PostgreSQL/Docker path remains optional and is not executed.

## Guardrails

- Windows 10/11, Python 3.11+, repository-local `.venv`.
- No Docker, WSL, PostgreSQL service, system-level installation, administrator
  permission, or package installation as part of the migration.
- No full crawl or bulk download during migration validation.
- No file deletion. Keep uncertain/optional artifacts and document their status.
- Use temporary/in-memory or disposable test databases for validation; do not reset
  the existing local `data/nfa_fire_law.db`.
- Every phase must leave the previous phase runnable. A rollback means reverting
  only that phase's focused changes and restoring the prior configuration/schema
  snapshot, not deleting user data.

## Phase 0 — Baseline, ownership, and safety

**Input**

- Existing Git worktree, `README.md`, `pyproject.toml`, current tests, ignored local
  `.env`, `.venv`, and local SQLite data if present.

**Output**

- A recorded inventory, a Git status baseline relative to `HEAD`, explicit
  Windows/no-Docker boundaries, and a reproducible test/environment result. The
  documentation produced by this phase may remain untracked until reviewed.

**Affected files**

- `AGENTS.md`
- `docs/PROJECT_STATUS.md`
- `docs/MIGRATION_PLAN_SQLITE_HYBRID_RAG.md`

**Validation**

- Confirm repository root and Git status.
- Confirm `.venv` Python/pip, Python SQLite version, `SELECT sqlite_version()`,
  temporary FTS5 create/query, and NumPy import/calculation.
- Run the offline suite with `.venv\\Scripts\\python.exe -m pytest -q`.

**Rollback**

- Documentation-only rollback is a review decision; do not delete user-created
  files. Keep the status evidence if it is useful for audit history.

## Phase 1 — Windows runtime and diagnostics

**Input**

- Working `.venv`, current `pyproject.toml`, `app/config.py`, and CLI.

**Output**

- A short, Windows-safe setup/diagnostics path that reports prerequisites without
  installing software, crawling, or touching the production-like local database.

**Affected files**

- Likely `app/cli.py`
- Likely `tests/`
- Optional small `scripts/*.bat` or `scripts/*.ps1`
- `README.md` only for corrected Windows-first instructions

**Validation**

- Diagnostics completes with no network call and reports Python, SQLite, FTS5,
  NumPy, selected database URL/backend, and embedding dimension.
- Run the existing suite and a fresh temporary CLI/database smoke test.

**Rollback**

- Remove/revert only the new diagnostics entrypoint and wrapper; retain existing
  source and local data.

## Phase 2 — SQLite schema and FTS5 baseline

**Input**

- `app/models.py`, `app/db.py`, `scripts/init.sql`, SQLite default settings, and
  `tests/test_sqlite_backend.py`.

**Output**

- A documented, tested SQLite schema for sources/laws/versions/chunks/metadata and
  a current-version-only FTS5 index with stable chunk identifiers.

**Affected files**

- `app/models.py`
- `app/db.py`
- `tests/test_sqlite_backend.py`
- Optional new focused migration/schema tests

**Validation**

- Create schema in a temporary SQLite database.
- Assert foreign keys, current-version filtering, FTS5 creation, rebuild behavior,
  and mapping from an FTS hit to `law_chunks` and `law_versions`.

**Rollback**

- Revert schema/index code to the prior tested shape. Do not alter or delete the
  user's existing database; if a schema change is needed later, add an explicit
  migration step rather than recreating it blindly.

## Phase 3 — Source discovery and bounded acquisition

**Input**

- NFA category/detail URL handling in `app/crawler/`, allowed-host config, and
  existing HTML fixtures.

**Output**

- Stable discovery of relevant law links, normalized `LSID` identity, print-view
  preference, TLS validation, bounded retries, and respectful stop behavior for
  403/429 responses.

**Affected files**

- `app/crawler/discovery.py`
- `app/crawler/fetch.py`
- `app/crawler/nfa_urls.py`
- `app/config.py`
- `tests/test_discovery.py`, `tests/test_fetch.py`, `tests/test_nfa_urls.py`

**Validation**

- Use fixtures and mocked fetchers only for routine tests.
- Verify same-host enforcement, URL canonicalization, retry bounds, delay config,
  and immediate stop on access-block responses.
- If a live check is explicitly needed, use a single small probe only and stop on
  failure; never run the full crawl as validation.

**Rollback**

- Restore the prior crawler/parser behavior and configuration defaults. Keep any
  downloaded local data untouched.

## Phase 4 — Legal text normalization and metadata

**Input**

- NFA HTML/print fixtures and parser/attachment modules.

**Output**

- Normalized title, law metadata, legal text, article/point boundaries, dynamic
  chrome removal, attachment report, and stable semantic content hash.

**Affected files**

- `app/parser.py`
- `app/attachments.py`
- `tests/test_parser.py`
- `tests/test_attachments.py`
- `tests/fixtures/*`

**Validation**

- Assert titles, published/amended/effective dates, article labels, administrative
  points, attachment labels, and unchanged hashes when only print timestamps differ.
- Include malformed/empty/scanned attachment cases without failing the whole law.

**Rollback**

- Revert only parser/fixture changes that fail regression tests. Preserve source raw
  text and existing version records.

## Phase 5 — Traceable chunking and versioned ingestion

**Input**

- Parsed laws from Phase 4, existing `app/ingest.py`, models, and content hashes.

**Output**

- Idempotent ingestion: unchanged content remains unchanged, changed content creates
  a new current version, old versions remain queryable for audit, and each chunk
  points to its version and law source.

**Affected files**

- `app/ingest.py`
- `app/models.py`
- `tests/test_ingest_probe.py`
- New focused version/idempotency tests if needed

**Validation**

- In a temporary database, ingest the same fixture twice and assert one version;
  change one legal body and assert a new version with the old version retained.
- Verify FTS rebuild excludes old versions and attachment skip reports are persisted.

**Rollback**

- Stop ingestion changes and use the previous ingestion path. Do not delete old or
  new version rows; reconcile with a focused migration only after review.

## Phase 6 — Embeddings and NumPy storage

**Input**

- `app/embedding.py`, SQLite embedding BLOB conversion in `app/db.py`, embedding
  settings, and existing embedding tests.

**Output**

- Deterministic no-key embedding baseline plus optional provider configuration,
  dimension checks, float32 storage, zero-norm protection, and an explicit path to
  re-embed when provider/model/dimension changes.

**Affected files**

- `app/embedding.py`
- `app/db.py`
- `app/config.py`
- `app/ingest.py`
- `tests/test_embedding.py`

**Validation**

- Assert deterministic output, configured dimension, float32 round-trip, cosine
  score bounds, empty/short text behavior, and no provider mixing in one corpus.
- Do not call a remote embedding provider during routine validation.

**Rollback**

- Keep the current hash provider/configuration as the safe fallback. Restore prior
  provider settings and do not overwrite existing vectors without an approved
  re-embedding operation.

## Phase 7 — Lexical, semantic, and hybrid retrieval

**Input**

- Current FTS5 index, stored vectors, `app/search.py`, and Phase 2 evaluation cases.

**Output**

- Predictable top-k hybrid retrieval with article hints, optional law-title filter,
  current-version filtering, score components, and provenance in every hit.

**Affected files**

- `app/search.py`
- `app/db.py`
- `tests/test_sqlite_backend.py`
- New retrieval ranking tests

**Validation**

- Test exact article queries, Chinese lexical terms, semantic-only candidate gaps,
  title filters, current-version isolation, and empty corpus behavior.
- Run the seed evaluation against a controlled fixture corpus; record hit-rate
  changes rather than requiring live data.

**Rollback**

- Restore the previous scoring weights/query construction. Keep indexed data and
  embeddings intact; rankings are code-level behavior and can be re-evaluated.

## Phase 8 — API/MCP contracts and citations

**Input**

- `app/api.py`, `app/mcp_server.py`, `app/search.py`, and provenance fields from
  Phase 5/7.

**Output**

- Stable health/search/article/law/version interfaces whose results expose law
  title, article/chunk, source URL, version, and enough metadata for answer-layer
  citations. Admin crawl remains local/protected by default.

**Affected files**

- `app/api.py`
- `app/mcp_server.py`
- `app/search.py`
- `tests/` API/MCP contract tests

**Validation**

- Exercise endpoints/tools against a temporary fixture database with no network.
- Assert provenance fields are present and admin operations do not silently expose
  credentials or invoke a full crawl.

**Rollback**

- Preserve old endpoint shapes or version the contract; revert only the new response
  fields/handlers after test review, without removing source records.

## Phase 9 — Incremental update, evaluation, and observability

**Input**

- Version/hash behavior, bounded crawler, evaluation seed, and CLI.

**Output**

- A repeatable small-batch update command/report, durable error/skip summaries,
  evaluation thresholds owned by the domain team, and operational logs that do not
  leak secrets.

**Affected files**

- `app/ingest.py`
- `app/evaluation.py`
- `app/cli.py`
- `app/config.py`
- `eval/phase2_queries.json`
- `tests/`

**Validation**

- Run only fixture/mocked batches in CI/local smoke tests.
- Verify reruns are idempotent, failures are attributable to one source, and a
  403/429 stops acquisition without an uncontrolled retry loop.
- Compare evaluation metrics against a reviewed baseline.

**Rollback**

- Disable the new scheduled/update command and return to manual small-batch runs.
  Keep reports for diagnosis; do not purge failed or historical version metadata.

## Phase 10 — Windows release hardening

**Input**

- Passing phases 0–9, README, `AGENTS.md`, local data conventions, and the actual
  target Windows machine policy.

**Output**

- A documented Windows-local runbook, optional non-admin launcher, backup/restore
  guidance for SQLite, secret handling, test gate, and explicit statement that
  Docker/WSL/PostgreSQL are not prerequisites.

**Affected files**

- `README.md`
- `AGENTS.md`
- Optional `scripts/*.bat`/`*.ps1`
- Optional focused `docs/` runbook and tests

**Validation**

- Fresh user-level `.venv` rehearsal without system installation.
- Initialize a disposable SQLite DB, run health/search against fixtures, run tests,
  and verify no credentials/data/caches are staged for Git.
- Confirm an offline run remains possible and a networked probe is explicitly
  bounded and opt-in.

**Rollback**

- Keep the prior README/runbook and disable only the new wrapper or release check.
  Restore from a user-managed SQLite backup if a future operational change affects
  data; never use a destructive reset as rollback.

## Recommended sequencing after this handoff

Proceed with Phase 1 as the next implementation step in the active repository. The
first change should be a no-network diagnostics path plus focused tests. Do not
start Phase 3 with a complete crawl, and do not activate the optional
Docker/PostgreSQL route to validate the SQLite target.
