# ProgressTimelineWidget — Design

## Status

**P4c implemented.** A dumb Textual widget that renders an
`ExecutionProgressProjection` without reading runtime events directly.
Integrated into `DashboardProjection` and `DashboardScreen`.

## Motivation

The Rig Console Dashboard needs to display runtime execution progress
(status, timing, output byte counts, warnings, exit code) for the current
invocation. Direct access to `RuntimeStreamEvent` objects from the widget
would violate the projection pattern and risk accidental content leakage.

`ProgressTimelineWidget` follows the `EvidenceRailWidget` pattern: it
consumes a pre-aggregated `ExecutionProgressProjection` and renders it
as a compact card in the dashboard's vertical layout.

## Widget Architecture

### Location

- Source: `vibe/cli/textual_ui/rig_console/widgets/progress_timeline.py`
- Projection model: `rig_relay.desktop.execution_progress.ExecutionProgressProjection`
- Exported via `__all__ = ["ProgressTimelineWidget"]`

### Pattern

Mirrors `EvidenceRailWidget` / `SessionPaneWidget` exactly:

```python
class ProgressTimelineWidget(Vertical):
    class Updated(Message):
        def __init__(self, projection: ExecutionProgressProjection) -> None: ...

    def __init__(self, projection: ExecutionProgressProjection | None = None, ...) -> None
    def compose(self) -> ComposeResult
    def update_projection(self, projection: ExecutionProgressProjection) -> None
    def _render_all(self) -> None
    def _update_static(self, css_class: str, text: str) -> None
```

### Children

1. A header `Static` with class `.progress-timeline-header`, always showing
   `"Progress"`.
2. A body `Static` with class `.progress-timeline-body`, whose text is
   rebuilt by `_build_body_text()` on each update.

### Rendering

`_build_body_text()` returns a multi-line string. Sections:

1. **Status line**: `"status: <status>"` + optional `"  <elapsed_ms>ms"`
2. **Identity line**: Space-separated short IDs — `"inv: <12chars>"`,
   `"lease: <12chars>"`, `"req: <12chars>"`. Only present if field is set.
3. **Heartbeat line**: `"heartbeats: <count>"`. Only if `heartbeat_count > 0`.
4. **Output line**: `"stdout: <bytes>b"` and/or `"stderr: <bytes>b"` plus
   `"(truncated)"` badge when respective truncation flag is set.
5. **Warning line**: `"warnings: <count>"` + `" [<kind>]"` + `" <message>"`.
   Only if `warning_count > 0`. Messages capped at 200 chars.
6. **Terminal lines**: Separate lines for `exit: <code>`, `error: <kind>`,
   `refused: <reason>`. Only present when respective field is set.

If the projection is empty (no meaningful data), renders:
`"No runtime execution yet."`

### Empty-state detection (`_is_empty`)

A projection is considered empty when all of the following are true:

- `status == "pending"` (default)
- `invocation_id` is None
- `lease_id` is None
- `request_id` is None
- `heartbeat_count == 0`
- `warning_count == 0`
- `last_event_at` is None
- `exit_code` is None
- `error_kind` is None
- `refusal_reason` is None
- `stdout_bytes` is None
- `stderr_bytes` is None
- `elapsed_ms` is None

### CSS

```css
ProgressTimelineWidget {
    width: 100%;
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $surface;
    border: solid $border;
}

ProgressTimelineWidget > .progress-timeline-header {
    width: 100%;
    height: auto;
    text-style: bold;
    color: $text;
}

ProgressTimelineWidget > .progress-timeline-body {
    width: 100%;
    height: auto;
    color: $text;
    padding: 0 0 0 1;
}
```

## Projection Integration

### DashboardProjection changes

An optional field was added to `DashboardProjection`:

```python
execution_progress: ExecutionProgressProjection | None = None
```

When `None`, the widget defaults to `ExecutionProgressProjection()` (empty state).

### DashboardScreen integration

In `compose()`, the widget is yielded between the activity zone and the
footer, always present:

```python
yield Horizontal(
    SessionPaneWidget(proj.session),
    EvidenceRailWidget(proj.evidence),
    classes="dashboard-activity",
)
yield ProgressTimelineWidget(proj.execution_progress or None)
yield FooterStatusWidget(proj)
```

In `_render_all()`, the widget's projection is updated:

```python
ep = proj.execution_progress or ExecutionProgressProjection()
timeline = self.query_one(ProgressTimelineWidget)
timeline.update_projection(ep)
```

Widget is always present in `compose()` to avoid conditional DOM issues
with `query_one()`.

## Content-light Guarantee

The widget renders only metadata from `ExecutionProgressProjection`. It
never accesses:

- `chunk_text` — raw output chunks
- `stdout` / `stderr` (raw) — only byte counts `stdout_bytes`/`stderr_bytes`
- `content` — generic raw content
- `diff` / `snippet` / `patch` — diffs
- `argv` — raw command
- `output` — raw command output

Verified by:
- Model `extra="forbid"` prevents accidental field addition
- Widget only accesses model fields via `proj.<field>` getters
- Widget does not accept raw event objects
- Test `test_widget_does_not_render_raw_output` asserts no raw patterns
  in rendered text
- Test `test_no_forbidden_raw_field_names_in_widget` checks no forbidden
  attribute names on the widget class

## Tests

- Location: `tests/cli/textual_ui/rig_console/test_progress_timeline.py`
- 40 tests covering:
  - Model validation (rejects raw fields, rejects extras, no raw field names)
  - Empty state (both explicit and default constructor)
  - Status line (with/without elapsed, different statuses)
  - Identity line (each ID separately, combined, truncated, none)
  - Heartbeat line (count shown, hidden when zero)
  - Output line (stdout, stderr, combined, truncated badges, missing)
  - Warning line (count, kind, message, long message truncation, hidden)
  - Terminal lines (exit code, error kind, refusal, combined, hidden)
  - Full projection (all sections rendered)
  - Failure projection (error + refusal rendered)
  - Update method (replaces data)
  - Content-light (no raw field names in widget, no raw output in text)
  - Edge cases (zero bytes, only warnings, only heartbeats, long IDs)

## Widget Behavior Rules

1. **Always present in DOM** — even when `execution_progress` is `None`,
   the widget renders the empty state. No conditional mounting.

2. **Content-light only** — never reads runtime events or raw output
   streams. Only renders already-aggregated projection data.

3. **Projection-absent → empty state** — when `execution_progress` field
   is not set (None), the widget defaults to an empty projection.

4. **Projection-present → full render** — when a non-empty projection is
   received, the widget renders all available sections.

5. **Re-render via update_projection** — calling `update_projection()`
   replaces internal state, re-renders, and posts an `Updated` message.

## Cross-References

- [Execution Progress Projection](../governance/execution-progress-projection.md)
- [EvidenceRailWidget](textual-rig-console-evidence-rail.md)
- [Dashboard Screen](textual-rig-console-dashboard.md)
