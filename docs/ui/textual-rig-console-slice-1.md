# Textual Rig Console — Slice 1: Projection-Only SessionPaneWidget

## Status

**Draft.** First slice of the Rig-native Textual operator console,
separate from the legacy VibeApp chat UI.

## Why This Is Separate From VibeApp

VibeApp is the legacy chat-centric Textual TUI (product surface). The Rig
Console is a **development/compatibility surface** for testing projection
models, content-light rendering, and widget grouping before they migrate
to the pywebview desktop cockpit.

Rationale for a separate package (`vibe/cli/textual_ui/rig_console/`):

1. **Projection-first** — Rig Console widgets render backend-authored
   state only. They never touch chat messages, tool output streams, or
   scrollback history.
2. **Content-light by construction** — Projection models forbid raw
   content fields. Widgets cannot accidentally render stdout, file
   contents, or diffs because the projection simply does not contain
   them.
3. **Isolated from VibeApp complexity** — VibeApp owns agent loop,
   chat input, approval callbacks, command dispatch, and 30+ widget types.
   Rig Console starts as a tiny orthogonal package.
4. **Migration path** — These projection models and widgets are designed
   to port to the pywebview desktop cockpit backend. The Textual renderer
   is a development preview; the real surface is the HTML/CSS/JS cockpit.

## Projection-First Rule

**Backend authors the state. Frontend renders the state. Frontend emits
intentions only.**

- Widgets never fetch data directly from tools, receipts, or git.
- Widgets receive a `SessionPaneProjection` (or future projection type)
  and render it.
- Missing data degrades to explicit placeholder (None/0), never
  fabricated state.

## SessionPaneProjection Fields

| Field | Type | Description |
|---|---|---|
| `session_id` | str | Unique session identifier |
| `lane_id` | str \| None | Logical lane within the console |
| `task_title` | str \| None | Human-readable task title |
| `status` | str | Session status (`active`, `blocked`, `idle`, etc.) |
| `branch_name` | str \| None | Git branch name |
| `worktree_path` | str \| None | Display-only worktree path |
| `last_heartbeat_at` | str \| None | ISO 8601 timestamp of last heartbeat |
| `current_step` | str \| None | Short description of current activity |
| `validate_status` | str \| None | Last validation run status |
| `blocker_summary` | dict[str, int] | Structured blocker counts (e.g. `{"dirty_files": 3}`) |
| `receipt_count` | int | Number of captured tool receipts |
| `latest_receipt_kind` | str \| None | Kind of most recent receipt |
| `changed_paths` | list[str] | Paths modified by the session (capped at 5 in display) |
| `pending_user_action` | str \| None | Action the user needs to take |

### What the model explicitly does NOT contain

- No `stdout`, `stderr`, or output fields
- No file contents or snippets
- No diffs or old/new text
- No command transcripts
- No secrets or tokens
- No raw tool results

## What the Widget Shows

The `SessionPaneWidget` renders one session as a vertical card:

1. **Header row** — truncated session ID, lane tag, status, task title
2. **Metadata row** — branch name, worktree path, last heartbeat time
3. **Current step** — what the session is doing right now
4. **Validate status** — validation result + structured blocker summary if blocked
5. **Receipt summary** — receipt count + latest receipt kind
6. **Changed paths** — sorted, capped at 5, with total count
7. **Pending action badge** — shown if the user needs to act

### What the widget intentionally does NOT show

- No scrollback firehose
- No raw logs
- No tool output
- No diffs or file previews
- No direct tool execution buttons
- No session lifecycle controls

## Project Structure

```
vibe/cli/textual_ui/rig_console/
├── __init__.py              # Public API re-exports
├── projections.py           # SessionPaneProjection + EvidenceRail projections
├── console_app.py           # Standalone fixture preview (optional)
├── widgets/
│   ├── __init__.py
│   ├── session_pane.py      # SessionPaneWidget
│   └── evidence_rail.py     # EvidenceRailWidget (Slice 1.1–2)
```

## Tests

```
tests/cli/textual_ui/rig_console/
├── __init__.py
├── test_session_pane_projection.py   # Model field/method tests
├── test_session_pane_widget.py       # Widget structural/content tests
└── test_evidence_rail.py             # Evidence rail model/adapter/widget tests
```

Tests cover:
- Projection defaults and immutability methods
- Unknown field rejection (via `ConfigDict(extra="forbid")`)
- Nullable field handling in `to_display_dict()`
- Forbidden raw field names are absent from projection fields
- Widget instantiation with various projection states
- `compose()` output structure (full, minimal, empty states)
- `update_projection()` replaces data
- Helper functions `_cap()`, `_format_path()`, `_format_blocker_summary()`
- Empty blocker/receipt/paths render cleanly

### Slice 1.1–2 additions (structured blockers and EvidenceRailWidget)

- `blocker_summary` changed from `str | None` to `dict[str, int] = {}`
- `_format_blocker_summary()` renders stable sorted text from dict
- `EvidenceRailItemProjection` — content-light receipt item
- `EvidenceRailProjection` — summary with counts and items
- `evidence_rail_from_receipt_index()` — pure adapter from `ToolReceiptIndexRecord`
- `EvidenceRailWidget` — renders header, counts, item list, empty state
- All projections forbid extra fields
- Adapter caps items (default 20), orders by `captured_at` descending

## Standalone Preview

Run `uv run python -m vibe.cli.textual_ui.rig_console.console_app` for a
fixture preview with four sample sessions and one evidence rail.

This is for local visual testing. Not wired into the default CLI.

## Next Slices

| Slice | Component | Description |
|---|---|---|
| 2 | EvidenceRailWidget | ✅ Completed (included as Slice 1.1–2) |
| 3 | DashboardScreen | ✅ Completed — projection-driven screen with header, activity, footer zones |
| 4 | Typed intents | Structured intention types (refresh, navigate, validate) |
| 5 | Multi-session grid | Grid of SessionPaneWidget instances for fleet/delegate views |
| 6 | Backend feed | Live projection updates from coordination store |
| 7 | pywebview port | Migrate projection models to desktop cockpit backend |

## Cross-References

- [Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Textual Retirement Policy](../governance/textual-retirement-policy.md)
- [Receipt Index](../../rig_relay/evidence/receipt_index.py)
- [Coordination Models](../../rig_relay/coordination/models.py)
- [Slice 2: EvidenceRailWidget](textual-rig-console-slice-2-evidence-rail.md)
