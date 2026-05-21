# Desktop Projection Shell Pattern Port

**Phase**: Desktop Projection Shell Pattern Port (Phase 3 of remaining slices)
**Date**: 2026-05-13
**Duration**: ~2 hours (partitioned from longer session)

## Summary

Ported Rig's desktop projection pattern to Rig Relay. Created a content-light projection builder (`scripts/rig_relay_desktop_projection.py`) that reads 6 data sources from actual artifact field names, never inventing fields. Missing sources return `"available": false`. Schema at `docs/schemas/rig.relay.desktop_projection.v1.schema.json`.

## Changes Made

### New Files
- `scripts/rig_relay_desktop_projection.py` — Content-light projection builder (380 lines)
- `docs/schemas/rig.relay.desktop_projection.v1.schema.json` — JSON Schema for projection (41st schema)

### Modified Files
- `scripts/rig_relay_desktop_cockpit.py` — Rebuilt to use projection builder; exposes 3 read-only API methods (`get_projection`, `refresh_projection`, `get_available_actions`)
- `frontend/desktop/index.html` — 6 dynamic cards for all projection categories + warning banner + source status
- `frontend/desktop/styles.css` — Warning banner, kv table, source status pill styles
- `frontend/desktop/app.js` — Per-category renderers for all 6 projection sources
- `docs/governance/desktop-cockpit-ui.md` — Updated Read-Only Cockpit section; added Rig Pattern Port section
- `docs/dogfood/rig-relay-self-dogfood.md` — Added entry 23

### New Tests
- `tests/scripts/test_desktop_projection.py` — 24 tests covering:
  - Projection builder returns expected keys, no invented fields
  - Missing sources return `available: false`
  - Warnings for unavailable sources
  - Content-light safeguards (no prompts, keys, raw content)
  - Load functions handle edge cases (missing files, invalid JSON, markdown parsing)
  - Desktop cockpit dry-run and API exposure

## Design Decisions

1. **Projection field names drawn from actual artifacts** — inspected `current_state.json`, `export_manifest.json`, `semantic_change_snippets_manifest.json`, `dataset-summary.md` for real field names
2. **Missing sources** → `"available": false` never crashes; warnings guide user to run generators
3. **Markdown parsing** — `_load_markdown_summary` only parses Executive Summary table; stops at subsequent tables; `exec_` prefix distinguishes markdown-sourced keys from JSON artifact keys
4. **Rig patterns ported** — UIProjection model, build_projection pattern, WidgetProjection/IntentProjection adapted as typed categories + read_only_actions array
5. **Rig patterns NOT ported** — WorkspaceHeader, ProposalLifecycle, AuditTrail, IntegrityStatusCard, ChatProjection, job store, worktree executor, Intake auth

## Validation
- `uv run python scripts/rig_relay_desktop_projection.py` — 3/6 sources available (expected)
- `uv run python scripts/rig_relay_desktop_cockpit.py --dry-run` — prints projection summary
- `uv run python scripts/rig_relay_validate_schemas.py` — 44/44 schemas passed
- `uv run ruff check` — clean
- `uv run pyright` — 0 errors
- `uv run pytest tests/scripts/test_desktop_projection.py` — 24/24 passed

## Known Issues
- 3 pre-existing test failures in `tests/scripts/test_rig_relay_dataset_inspector_lib.py` (duckdb missing)
- 156+ stale coordination leases (dormant — no active conflicts)
- Coordination reservation system creates active leases per write attempt, requiring manual `mark_lease_stale`
