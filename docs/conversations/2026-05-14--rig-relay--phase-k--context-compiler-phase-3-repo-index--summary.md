# Phase 3: RepoContextIndex — DuckDB-backed constrained retrieval

**Date:** 2026-05-14
**Phase:** k (prompt-first shell bridge → context compiler → repo index)
**Topic:** DuckDB-backed RepoContextIndex replacing ad-hoc file discovery with deterministic constrained retrieval
**Kind:** summary

## Context

Phase 1 built pack-based context compiler with fingerprint caching (7 packs).
Phase 2 wired the receipt store for compaction receipts + context envelope persistence.
Phase 3 (this) adds a DuckDB-backed `RepoContextIndex` that maps source files to their tests, docs, schemas, and same-package peers — then integrates it into the compiler.

## Outcome

### New file: `rig_relay/context/repo_index.py`
- `RepoContextIndex` class, DuckDB in-memory backend
- `populate()` scans git-tracked files, discovers relationships via naming conventions
- `find_tests(paths)` → test files by stem matching (`test_{stem}.py`, `{stem}_test.py`)
- `find_docs(paths)` → doc files in `docs/`
- `find_schemas(paths)` → schema files in `docs/schemas/`
- `find_related(paths)` → all relations grouped by type
- `summary()` → content-light file/relation counts
- Fingerprint based on file mtimes for rebuild caching
- Graceful absence: returns empty results if DuckDB unavailable or no git repo

### Modified: `rig_relay/context/compiler.py`
- `ContextCompiler.__init__` accepts `repo_index: RepoContextIndex | None`
- `RelevantTestsPack` uses index when available (falls back to glob patterns)
- New `RelatedFilesPack` — shows related files (tests, docs, schemas) for user-mentioned paths
- Both packs added to `_default_packs`

### Modified: `vibe/cli/textual_ui/rig_console/screens/dashboard.py`
- `_do_turn` lazily creates `RepoContextIndex` on first prompt and caches it
- Passes to `ContextCompiler(repo_index=...)`

### Tests: `tests/context/test_repo_index.py`
- 11 tests: populate, find_tests, find_related, summary, fallback, integration with RelatedFilesPack and RelevantTestsPack, end-to-end via ContextCompiler

### Validation
- **431 tests pass** (420 old + 11 new)
- Ruff, pyright, ruff format all clean
- No new dependencies (DuckDB was already in `pyproject.toml`)

## Key Decisions
- **In-memory DuckDB**: index rebuilt per session (or lazily on first prompt). Fingerprint caching avoids redundant rebuilds within a session.
- **Deterministic relations**: stem-based mapping, no glob, no heuristic scoring. If a test file has the same stem as a source file (modulo `test_` prefix/suffix), it's related. Embeds cleanly into the content-light convention.
- **Index as optional dependency**: all packs fall back gracefully. If DuckDB is not installed, no git repo, or the index errors, the compiler uses its original glob-based logic. Zero disruption.
- **No embeddings**: Phase 3 explicitly skips semantic retrieval. The index is structural only — filenames, paths, and naming conventions.

## Delta from Phase 2
| Metric | Phase 2 | Phase 3 |
|---|---|---|
| Files touched | 7 | 5 |
| New files | 0 | 2 (repo_index.py, test_repo_index.py) |
| New tests | 11 | 11 |
| Test count | 420 | 431 |
| Dependencies added | 0 | 0 |

## Cross-Session Coordination
No coordination artifacts produced. RepoContextIndex is session-local (in-memory DuckDB, lazily initialized, no inter-session state).

## Out-of-Scope Findings Recorded
None.

## Next Steps
- Phase 4: cross-lane context exchange (lane summaries → compiler input)
- Phase 5: MCP-compatible resource exposure if warranted
- Embeddings remain deferred (acceleration layer, not authority)
