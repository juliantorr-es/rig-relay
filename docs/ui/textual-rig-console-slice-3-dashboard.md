# Textual Rig Console — Slice 3: DashboardScreen

## Status

**Draft.** Composes existing widgets into a projection-driven dashboard
screen with header, activity (session pane + evidence rail side-by-side),
and footer zones.

## Why DashboardScreen

The `SessionPaneWidget` and `EvidenceRailWidget` are individual cards.
The `DashboardScreen` composes them into a single operator surface:

- **OperatorHeaderWidget** — title, subtitle, safety-state badge
- **Activity zone** — `SessionPaneWidget` (left) + `EvidenceRailWidget` (right)
- **FooterStatusWidget** — footer hint + backlog items (capped at 5)

This is the first multi-widget screen in the Rig Console. It demonstrates
how projections flow through a screen hierarchy: `DashboardProjection`
→ `DashboardScreen` → child widgets via `update_projection()`.

## DashboardProjection Fields

| Field | Type | Description |
|---|---|---|
| `title` | str | Dashboard title |
| `subtitle` | str \| None | Optional subtitle |
| `session` | `SessionPaneProjection` | Session state for the pane |
| `evidence` | `EvidenceRailProjection` | Evidence state for the rail |
| `safety_state` | str \| None | Safety badge label (e.g. "active") |
| `footer_hint` | str \| None | Footer hint text (e.g. "q: quit r: refresh") |
| `backlog_items` | list[str] | Pending items (capped at 5 in display) |

### Properties

| Property | Type | Description |
|---|---|---|
| `backlog_capped` | list[str] | Backlog items capped at `_DASHBOARD_BACKLOG_CAP` (5) |

### What the model explicitly does NOT contain

- No `stdout`, `stderr`, or output fields
- No file contents or snippets
- No diffs or old/new text
- No command transcripts
- No secrets or tokens
- No raw tool results

## OperatorHeaderWidget

Renders the dashboard header from a `DashboardProjection`:

1. **Title** — bold text
2. **Subtitle** — muted, shown if present
3. **Safety badge** — "⚡ {safety_state}", shown if present

Subclasses `Horizontal`. Has `update_projection(DashboardProjection)`.

## FooterStatusWidget

Renders the dashboard footer from a `DashboardProjection`:

1. **Hint** — muted footer hint text, shown if present
2. **Backlog** — "backlog:" header + capped items, or "no backlog" empty state

Subclasses `Vertical`. Has `update_projection(DashboardProjection)`.

## DashboardScreen

A `Screen` subclass composing:

```
┌─ OperatorHeaderWidget ───────────────────────┐
├─ Horizontal ─────────────────────────────────┤
│  SessionPaneWidget  |  EvidenceRailWidget    │
├─ FooterStatusWidget ─────────────────────────┘
```

- `DEFAULT_CSS` sets background `#06110B`, side-by-side widgets at 50% width
- `BINDINGS`: `q` → quit, `r` → refresh placeholder
- `update_projection(DashboardProjection)` propagates to all child widgets
- `action_refresh()` calls `_render_all()` (placeholder for future live updates)

### Projection flow

```
DashboardProjection
├── title / subtitle / safety_state → OperatorHeaderWidget
├── session → SessionPaneWidget
├── evidence → EvidenceRailWidget
└── footer_hint / backlog_items → FooterStatusWidget
```

## EvidenceRailWidget Updates in Slice 3

- Added `Updated` Message class (matching `SessionPaneWidget` pattern)
- Added `update_projection(EvidenceRailProjection)` method
- Added `_render_all()` pattern using `_update_static()` for header, counts, items
- Refactored `compose()` to yield a single `.evidence-rail-items` Static for content

## Project Structure

```
vibe/cli/textual_ui/rig_console/
├── __init__.py              # Public API re-exports (new: DashboardProjection, DashboardScreen, etc.)
├── projections.py           # +DashboardProjection, +_DASHBOARD_BACKLOG_CAP
├── console_app.py           # +DashboardScreen preview mode
├── screens/
│   ├── __init__.py
│   └── dashboard.py         # DashboardScreen (NEW)
└── widgets/
    ├── __init__.py
    ├── session_pane.py
    ├── evidence_rail.py     # +update_projection(), +Updated Message
    ├── operator_header.py   # OperatorHeaderWidget (NEW)
    └── footer_status.py     # FooterStatusWidget (NEW)
```

## Tests

```
tests/cli/textual_ui/rig_console/
├── __init__.py
├── test_session_pane_projection.py
├── test_session_pane_widget.py
├── test_evidence_rail.py
├── test_dashboard_projection.py   # DashboardProjection model tests (NEW)
├── test_dashboard_screen.py        # DashboardScreen structural tests (NEW)
├── test_operator_header.py         # OperatorHeaderWidget tests (NEW)
└── test_footer_status.py           # FooterStatusWidget tests (NEW)
```

## Next Slices

| Slice | Component | Description |
|---|---|---|
| 4 | Action boundary | Provider protocol, typed read-only actions, keybinding seam ✅ Completed |
| 5 | Runtime adapter | Replace fixture provider with real backend adapter |
| 6 | Multi-session grid | Grid of SessionPaneWidget instances for fleet/delegate views |

## What DashboardScreen intentionally does NOT do

- Does not modify VibeApp or any TCSS files
- Does not read raw tool output, logs, files, or diffs
- Does not handle real-time updates (projection feed is a future slice)
- Does not wire into the default CLI (standalone preview only)
- Does not implement session lifecycle controls
- Does not implement full screen navigation (no screen stack yet)

## Standalone Preview

```bash
uv run python -m vibe.cli.textual_ui.rig_console.console_app
```

Default mode is `"dashboard"` which shows the `DashboardScreen` with
sample data. Pass `mode="single"` to see individual widgets:

```python
app = RigConsolePreview(mode="single")
```

## Cross-References

- [Slice 1: SessionPaneWidget](textual-rig-console-slice-1.md)
- [Slice 2: EvidenceRailWidget](textual-rig-console-slice-2-evidence-rail.md)
- [Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Textual Retirement Policy](../governance/textual-retirement-policy.md)
