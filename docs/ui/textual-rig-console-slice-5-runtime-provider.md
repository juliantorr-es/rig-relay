# Textual Rig Console — Slice 5: Read-Only Runtime Dashboard Provider

## Status

**Draft.** Replaces the fixture-only provider seam with a real read-only
provider that builds `DashboardProjection` from existing Rig Relay
evidence/session state via the receipt index.

## RuntimeDashboardProjectionProvider

### Constructor

```python
class RuntimeDashboardProjectionProvider:
    def __init__(
        self,
        session_id: str = "unknown",
        session_path: Path | None = None,
        workspace_root: Path | None = None,
        max_evidence_items: int = 20,
        coordination_root: Path | None = None,
        session_root: Path | None = None,
        lane_id: str | None = None,
        task_title: str | None = None,
    ) -> None: ...
```

- `session_id`: Logical session identifier (defaults to "unknown")
- `session_path`: Optional explicit path to a session directory or
  `observability.jsonl` file. If None, resolves from `session_id` via
  `get_observability_log_path()` (`~/.rig/relay/sessions/<id>/observability.jsonl`)
- `workspace_root`: Optional workspace root path for `worktree_path` in the
  session pane (display only)
- `max_evidence_items`: Maximum evidence rail items (default 20)
- `coordination_root`: Optional root path of the coordination store
  (`{root}/sessions/{session_id}.json` contains the coordination session).
  If None, coordination fields remain empty.
- `session_root`: Reserved for future session lifecycle scanning (unused).
- `lane_id`: Explicit lane identifier. Overrides coordination-derived value.
- `task_title`: Explicit task title. Not available from coordination store
  directly; set via constructor.

### Data Sources

The provider reads from two backend stores:

1. **`build_receipt_index()`** from `rig_relay/evidence/receipt_index.py` —
   reads session observability JSONL, filters for `rig.relay.tool_receipt.captured`
   events, returns content-light `ToolReceiptIndexRecord` objects

2. **`evidence_rail_from_receipt_index()`** from `projections.py` — adapter
   that converts `ToolReceiptIndexRecord` list to `EvidenceRailProjection`

3. **Coordination store** (Slice 6) — reads `{coordination_root}/sessions/{session_id}.json`
   for lane_id, last_heartbeat_at, and current_step via `_read_coordination_summary()`.
   Tolerates missing/malformed JSON gracefully.

### SessionPaneProjection Field Mapping

| Field | Source | Behavior |
|---|---|---|
| `session_id` | Constructor parameter | Direct pass-through |
| `status` | Receipt presence | `"active"` if any records, `"idle"` otherwise |
| `worktree_path` | Constructor `workspace_root` | Set if provided |
| `current_step` | Coordination `status` or default | `"No active session data"` if coordination not available |
| `validate_status` | Latest validate receipt status | Extracted from most recent validate record's `status` field |
| `blocker_summary` | N/A | Empty dict `{}` (not available from receipt index) |
| `receipt_count` | Evidence projection | Pass through from `evidence.receipt_count` |
| `latest_receipt_kind` | Most recent receipt tool_name | First non-None tool_name found in descending chronological order |
| `changed_paths` | Evidence items with `path` | Deduplicated, capped at `_PROVIDER_PATH_CAP` (10) |
| `branch_name` | N/A | Left `None` (not available from receipts) |
| `last_heartbeat_at` | Coordination `updated_at` | Coordination session file's `updated_at` |
| `pending_user_action` | N/A | Left `None` |
| `lane_id` | Coordination `task_id` or constructor `lane_id` | Constructor param overrides coordination |
| `task_title` | Constructor `task_title` | Only via explicit constructor input |

### DashboardProjection Field Mapping

| Field | Value |
|---|---|
| `title` | `"Rig Console"` |
| `subtitle` | `"Session <id>"` (first 12 chars) |
| `safety_state` | `"read-only"` |
| `footer_hint` | `"Read-only evidence provider"` + `"(N read errors)"` if errors |
| `backlog_items` | Empty list |

### Missing Session Behavior

If the session path does not exist or the observability file is missing:
- `build_receipt_index` returns `([], ["Observability file not found: ..."])`
- The provider returns a clean `DashboardProjection` with:
  - `session.status = "idle"`
  - `session.receipt_count = 0`
  - `evidence.receipt_count = 0`
  - `evidence.items = []`
  - `footer_hint` includes `"(1 read errors)"`
- No crash, no exception

### Content-Light Guarantees

All data flows through projection models with `extra="forbid"`:
- `DashboardProjection`
- `SessionPaneProjection`
- `EvidenceRailProjection`
- `EvidenceRailItemProjection`

The provider itself never:
- Exposes raw stdout/stderr
- Exposes file contents, diffs, or snippets
- Exposes command transcripts
- Parses raw observability payloads in widget/screen code
- Mutates files or state
- Executes tools

### No Mutation / No Tool Execution Policy

The `RuntimeDashboardProjectionProvider` is **read-only**:
- It calls `build_receipt_index()` which reads JSONL files
- It calls `evidence_rail_from_receipt_index()` which is a pure function
- It does not call any tool, write files, or mutate state
- It is safe to call from the TUI event loop

## Integration with DashboardScreen

```python
from vibe.cli.textual_ui.rig_console.providers import (
    RuntimeDashboardProjectionProvider,
)

provider = RuntimeDashboardProjectionProvider(
    session_id="abc123-def456",
    workspace_root=Path("/Users/user/project"),
)
initial = await provider.dashboard_projection()
screen = DashboardScreen(initial, provider=provider)
```

Pressing `r` (refresh) calls `provider.dashboard_projection()` which
re-reads the observability JSONL and returns an updated projection.
Widgets are updated in place via `update_projection()` — no remounting.

## Project Structure

```
vibe/cli/textual_ui/rig_console/
├── __init__.py              # +RuntimeDashboardProjectionProvider
├── projections.py           # (unchanged)
├── providers.py             # +RuntimeDashboardProjectionProvider
├── intents.py               # (unchanged)
├── console_app.py           # (unchanged — still uses fixture)
├── screens/
│   └── dashboard.py         # (unchanged)
└── widgets/
    ├── __init__.py
    ├── session_pane.py
    ├── evidence_rail.py
    ├── operator_header.py
    └── footer_status.py
```

## Tests

```
tests/cli/textual_ui/rig_console/
├── test_providers.py        # +RuntimeDashboardProjectionProvider tests
```

New test coverage:
- Missing session path returns clean empty projection (no crash)
- Builds from synthetic JSONL with bash/search_replace/validate/write_file events
- EvidenceRailProjection has correct item counts (mutations, refusals, timeouts)
- Items ordered by captured_at descending
- Maps validate receipt status into validate_status
- Maps latest receipt tool_name into latest_receipt_kind
- Deduplicates and caps changed_paths at `_PROVIDER_PATH_CAP` (10)
- No validate receipt → validate_status is None
- Malformed JSON lines are tolerated without crash
- Footer shows read error count
- No forbidden raw fields on DashboardProjection or SessionPaneProjection
- DashboardScreen can be instantiated with RuntimeDashboardProjectionProvider
- workspace_root propagates to worktree_path
- blocker_summary is empty dict (not available from receipts)

## What This Slice Intentionally Does Not Do

- Does not modify legacy VibeApp or its TCSS files
- Does not wire mutation actions
- Does not execute validate or any tool from the TUI
- Does not read coordination state or session lifecycle files
- Does not parse raw observability payloads in widgets/screens
- Does not add real-time/frequent polling
- Does not resolve branch_name (not available from receipt index alone)

## Future Provider Path

| Slice | Improvement |
|---|---|
| 5.1 | **COMPLETED** — Worker-safe refresh (Textual worker via `run_worker(exclusive=True)`) |
| 6 | Add coordination state reading for branch/lane/heartbeat fields |
| 7 | Add session lifecycle directory scanning for multi-session views |

## Cross-References

- [Slice 1: SessionPaneWidget](textual-rig-console-slice-1.md)
- [Slice 2: EvidenceRailWidget](textual-rig-console-slice-2-evidence-rail.md)
- [Slice 3: DashboardScreen](textual-rig-console-slice-3-dashboard.md)
- [Slice 4: Action Boundary](textual-rig-console-slice-4-action-boundary.md)
- [Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Receipt Index](../../rig_relay/evidence/receipt_index.py)
