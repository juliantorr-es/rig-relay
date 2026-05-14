# Textual Rig Console — Slice 6: Coordination/Session Enrichment

## Status

**Complete.** Adds coordination store reading for lane_id, last_heartbeat_at,
and current_step fields in `RuntimeDashboardProjectionProvider`, along with
constructor overrides for lane_id and task_title. Tolerates missing/malformed
coordination data gracefully.

## Motivation

Slice 5 populated `SessionPaneProjection` from receipt index data alone,
leaving several fields (`lane_id`, `task_title`, `last_heartbeat_at`,
`current_step`) as `None` or a static fallback. These fields are available
from the coordination store (`CoordinationSession` JSON files), which
tracks cross-session task claims, heartbeats, and session lifecycle.

Adding coordination reading to the provider fills these gaps without
changing widget code or the projection model surface.

## What Changed

### `providers.py` (`CoordinationDashboardSummary` + `_read_coordination_summary`)

1. **`CoordinationDashboardSummary` model** — content-light Pydantic model
   with `extra="forbid"`. Fields:

   | Field | Type | Source |
   |-------|------|--------|
   | `lane_id` | `str \| None` | Coordination session `task_id` |
   | `task_title` | `str \| None` | Not directly available from store |
   | `last_heartbeat_at` | `str \| None` | Coordination `updated_at` |
   | `current_step` | `str \| None` | Coordination `status` |
   | `pending_user_action` | `str \| None` | Reserved (not yet available) |
   | `session_status` | `str \| None` | Coordination `status` |
   | `warnings` | `list[str]` | Malformed-JSON flag |

2. **`_read_coordination_summary()`** — file-level helper that reads
   `{coordination_root}/sessions/{session_id}.json` and parses with
   `CoordinationSession.model_validate()`. Returns a
   `CoordinationDashboardSummary` in all paths:

   - `coordination_root is None` → empty summary
   - Session file missing → empty summary
   - Malformed JSON → empty summary with `warnings=["Malformed coordination session file"]`
   - Valid JSON → populated summary from coordination fields

3. **Constructor params added** to `RuntimeDashboardProjectionProvider`:

   ```python
   coordination_root: Path | None = None
   session_root: Path | None = None  # Reserved
   lane_id: str | None = None        # Overrides coordination
   task_title: str | None = None     # Explicit only
   ```

4. **`_build_session()` updated** — calls `_read_coordination_summary()`
   and applies the precedence: explicit constructor params override
   coordination-derived values. Receipt-derived fields are unchanged.

### Precedence Rules

| Field | Precedence |
|-------|-----------|
| `lane_id` | Constructor `lane_id` > coordination `task_id` > `None` |
| `task_title` | Constructor `task_title` > `None` |
| `last_heartbeat_at` | Coordination `updated_at` > `None` |
| `current_step` | Coordination `status` > `"No active session data"` |
| `validate_status`, `receipt_count`, `changed_paths` | Receipt index only (unchanged) |

### Error Tolerance

All three failure modes return a clean projection with coordination fields
set to `None`/`"No active session data"` — no exception propagates to the
caller. Receipt-derived data is unaffected.

## Updates to Existing Files

| File | Change |
|------|--------|
| `vibe/cli/textual_ui/rig_console/providers.py` | Added `CoordinationDashboardSummary`, `_read_coordination_summary()`, 4 new constructor params, `_build_session()` calls `_read_coordination_summary()` |
| `tests/cli/textual_ui/rig_console/test_providers.py` | 12 new tests in `TestCoordinationEnrichment` class |
| `docs/ui/textual-rig-console-slice-5-runtime-provider.md` | Updated constructor, data sources, field mapping table, Future Provider Path |
| `docs/ui/textual-rig-console-slice-5-1-worker-refresh.md` | Added callable-vs-coroutine explanation for RuntimeWarning fix |

## What This Slice Intentionally Does Not Do

- Does not modify legacy VibeApp or its TCSS files
- Does not wire mutation actions
- Does not execute validate or any tool from the TUI
- Does not parse raw observability payloads in widgets/screens
- Does not add real-time/frequent polling
- Does not add session lifecycle directory scanning (multi-session views)
- Does not resolve branch_name (not available from coordination store)
- Does not resolve pending_user_action (not yet tracked)
- Does not mutate coordination files or repair leases
- Does not crawl the coordination directory tree

## New Test Coverage

`TestCoordinationEnrichment` (12 tests):

| Test | What It Verifies |
|------|------------------|
| `test_missing_coordination_root_returns_clean_projection` | `coordination_root=None` → fields stay None/default |
| `test_missing_coordination_dir_returns_clean_projection` | Non-existent coordination dir → no crash |
| `test_missing_session_file_is_tolerated` | Missing session JSON → clean projection, receipts still work |
| `test_malformed_coordination_json_is_tolerated` | Garbage JSON → empty summary, receipt data unaffected |
| `test_lane_id_from_coordination_propagates` | Coordination `task_id` → `lane_id` |
| `test_explicit_lane_id_overrides_coordination` | Constructor `lane_id` overrides coordination `task_id` |
| `test_explicit_task_title_propagates` | Constructor `task_title` appears in projection |
| `test_last_heartbeat_at_from_coordination` | Coordination `updated_at` → `last_heartbeat_at` |
| `test_current_step_from_coordination` | Coordination `status` → `current_step` |
| `test_workspace_root_still_propagates_with_coordination` | `workspace_root` → `worktree_path` alongside coordination |
| `test_no_forbidden_raw_fields_with_coordination` | No stdout/stderr/output/content/diff leakage |
| `test_receipt_data_survives_with_coordination` | `validate_status`, `receipt_count`, `status` unchanged by coordination |

## Risk and Verification

- **Risk**: None. Coordination store is read-only, missing data is tolerated,
  explicit overrides take priority. No change to receipt index or evidence
  rail logic.
- **Verification**: 25 provider tests pass (13 existing + 12 new), all 29
  dashboard screen tests pass, ruff/pyright clean.

## Next Slice (7)

Add session lifecycle directory scanning for multi-session views — reading
the coordination store's top-level session index to populate a session
list/selector widget.

## Cross-References

- [Slice 5: Runtime Dashboard Provider](textual-rig-console-slice-5-runtime-provider.md)
- [Slice 5.1: Worker-Safe Dashboard Refresh](textual-rig-console-slice-5-1-worker-refresh.md)
- [Coordination Models](../../rig_relay/coordination/models.py)
- [Coordination Store](../../rig_relay/coordination/store.py)
- [Providers module](../../vibe/cli/textual_ui/rig_console/providers.py)
