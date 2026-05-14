# ExecutionProgressProjection — Design

## Status

**Phase P4a implemented.** Defines the content-light read model for
RuntimeSupervisor execution summaries consumed by desktop/Textual/pywebview
projection surfaces. See `## Implementation Status` below.

## Motivation

`RuntimeSupervisor` now emits rich structured stream events. If UI layers
consume these ad hoc, the system risks:

- Reintroducing Vibe-style state sprawl (multiple ad hoc projections)
- Raw stream leakage into evidence rails and receipt timelines
- Non-deterministic aggregation logic scattered across UI widgets

A single **ExecutionProgressProjection** read model solves this: a pure
aggregation function transforms a list of `RuntimeStreamEvent` into a
compact, content-light summary.

## Fields

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `schema_version` | string | constant | `"rig.relay.execution_progress.v1"` |
| `invocation_id` | string | `event_id` from any event | Stable identifier for this execution |
| `lease_id` | string | `lease_id` from any event | Executing lease |
| `request_id` | string | `request_id` from any event | Original request |
| `workspace_id` | string\|null | derived from lease request | Workspace context |
| `worktree_path` | string\|null | derived from lease request | Worktree path |
| `status` | string | aggregated from events | One of: `pending`, `starting`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`, `blocked`, `degraded` |
| `started_at` | string\|null | first `STATUS(starting)` | ISO 8601 |
| `last_event_at` | string\|null | latest `captured_at` | ISO 8601 |
| `elapsed_ms` | float\|null | terminal event or latest heartbeat | Duration so far |
| `heartbeat_count` | int | count of HEARTBEAT events | ≥0 |
| `warning_count` | int | count of WARNING events | ≥0 |
| `latest_warning_kind` | string\|null | last WARNING event | Sanitized, no raw content |
| `latest_warning_message` | string\|null | last WARNING event | Sanitized, no raw content |
| `stdout_bytes` | int\|null | terminal event | Total bytes drained |
| `stderr_bytes` | int\|null | terminal event | Total bytes drained |
| `stdout_truncated` | bool | terminal event | Whether cap was exceeded |
| `stderr_truncated` | bool | terminal event | Whether cap was exceeded |
| `exit_code` | int\|null | terminal event | Process exit code |
| `error_kind` | string\|null | FAILURE event | `"timeout"`, `"cancelled"`, `"governance_blocked"`, etc. |
| `refusal_reason` | string\|null | FAILURE event | Human-readable (no raw output) |
| `terminal_event_id` | string\|null | last COMPLETION/FAILURE | Links to full event if needed |
| `evidence_sha256` | string\|null | SHA256 of the terminal event JSON | For integrity chain |

### Forbidden fields

The following are NEVER present in ExecutionProgressProjection:

- `chunk_text` — raw output
- `stdout` / `stderr` — raw output (only hashes and byte counts)
- `content` — generic raw content
- `diff` / `snippet` — diff content
- `shell` / `argv` — full command (request_id fingerprint is sufficient)
- `file_path` — file contents

## Aggregation Behavior

### Signature (future implementation)

```python
def execution_progress_from_runtime_events(
    events: list[RuntimeStreamEvent],
    now: datetime | None = None,
) -> ExecutionProgressProjection:
    ...
```

### Rules

1. **Status precedence (terminal over non-terminal):**
   - If any COMPLETION or FAILURE event exists, use its `status` field.
   - If only STATUS events exist, use the latest non-terminal status.
   - If no STATUS events, use `"pending"` before first event, `"running"` after HEARTBEAT/WARNING.

2. **Heartbeat count:** Incremented on each HEARTBEAT `event_kind`.

3. **Warning count:** Incremented on each WARNING `event_kind`.
   - `latest_warning_kind` and `latest_warning_message` set from the last WARNING event.
   - Messages are sanitized: truncated to 200 chars, no raw output patterns.

4. **Byte/hash/truncation fields:** Taken from the **last** COMPLETION or FAILURE event.
   - If multiple terminal events (shouldn't happen), last one wins.

5. **Duration:** `elapsed_ms` from terminal event if available; otherwise from latest HEARTBEAT.

6. **Missing terminal event:** If no COMPLETION/FAILURE after `stall_warning_after_ms` threshold:
   - Status set to `"degraded"`.
   - Can also use `"running"` if heartbeats are still arriving.

7. **Malformed events:** Events that fail Pydantic validation are skipped.
   - Degraded status if >50% of events are malformed.

8. **Out-of-order events:** Events are processed in list order (assumed chronological).
   - `started_at` from first STATUS(starting) event.
   - `last_event_at` from last event's `captured_at`.

### Edge cases

| Scenario | Status | Behavior |
|----------|--------|----------|
| Empty event list | `pending` | All counts 0, no timestamps |
| Only heartbeats | `running` | `elapsed_ms` from latest heartbeat |
| First event is COMPLETION | `succeeded`/`failed` | `started_at` from completion's `captured_at` |
| WARNING after COMPLETION | `succeeded`/`failed` | WARNING ignored (terminal wins) |
| Multiple FAILURE events | last FAILURE's status | Last terminal wins |
| Terminal without stdout fields | degraded | Missing byte counts flagged |

## Projection-Integrity Relationship

`ProjectionIntegrity` does not need modification. The ExecutionProgressProjection
would be assessed via the existing integrity framework:

| Condition | Integrity Status | Rationale |
|-----------|-----------------|-----------|
| Terminal event exists + has receipt/envelope/audit backing | `VERIFIED` | Evidence chain complete |
| Running with recent heartbeat (< 2 × heartbeat_interval_ms) | `DEGRADED` | In-flight but no terminal evidence yet |
| Running with stale heartbeat (≥ 2 × heartbeat_interval_ms) | `STALE` | Process may have died silently |
| Status = succeeded/failed but no receipt/envelope/audit | `DEGRADED` | Authority missing |
| Status = succeeded/failed but no terminal event in stream | `VIOLATED` | Projection claims completion without evidence (AUTHORITY_UNBACKED) |
| Warnings present in projection | `DEGRADED` | Non-fatal, but attention needed |

The integrity assessment feeds into the existing `integrity` field on
`DesktopProjection`. No new violation codes are needed — existing codes
(`MISSING_RECEIPT`, `STALE_RECEIPT`, `AUTHORITY_UNBACKED`) cover all cases.

## UI Behavior Rules

### Textual (Legacy TUI)

- **ProgressTimeline widget** renders ExecutionProgressProjection as a compact
  progress row/card in the activity zone.
- Show: status badge, elapsed time, byte counts, warning badge, exit code.
- Never show raw output by default. Raw chunks may remain in the stream/chat
  pane only, not in the evidence rail or projection card.
- Stalled process shows a warning badge (visual indicator, non-blocking).
- Completed process links to receipt/audit event ID, not full output dump.
- Clicking the card could expand to show `stdout_bytes`/`stderr_bytes` metadata.

### Desktop (pywebview)

- Consistent read model: same `ExecutionProgressProjection` fields.
- Projection builder (`projection.py`) populates `progress_events` array in
  the desktop projection JSON.
- Widget name: `ProgressTimeline` (already registered in `projection_widgets.py`).
- Contract: follows Relay Desktop Projection Contract rules — frontend renders,
  does not author state or infer decisions.

### Content-light enforcement

The projection layer is the **last sanitization boundary** before UI rendering.
All fields in ExecutionProgressProjection are safe to render. The aggregation
function must:

- Strip `chunk_text` from chunk events.
- Strip raw output from WARNING messages (truncate to safe length, remove
  patterns matching stdout/stderr content).
- Never include argv (request_id is the stable reference).
- Never include file contents, diffs, or snippets.

## Relationship to Existing Widget Taxonomy

| Widget | Current Status | Relationship |
|--------|---------------|--------------|
| `ProgressTimeline` | Defined in widget taxonomy, **no data source** | This design fills the gap |
| `LatestIntentResult` | Has data source (intent results) | Separate concern — intent-level results are coarser than execution-level events |
| `ReceiptTimeline` | Has data source (receipt index) | Terminal execution events may link to receipt IDs |
| `SessionPaneProjection` | Has data source (coordination leases) | Execution status may be part of session pane in the future |

## Implementation Status

**Phases P4a + P4b.1 + P4c implemented.** See source:
- Model + aggregation: `rig_relay/desktop/execution_progress.py`
- Projection integration: `rig_relay/desktop/projection.py` (`build_projection()`)
- Schema: `docs/schemas/rig.relay.execution_progress_projection.v1.schema.json`
- Desktop schema: `docs/schemas/rig.relay.desktop_projection.v1.schema.json` (optional `execution_progress` field)
- Tests: `tests/desktop/test_execution_progress_projection.py`
- Integration tests: `tests/desktop/test_desktop_projection.py`

### Implemented

- `ExecutionProgressProjection` Pydantic model — 23 fields, `extra="forbid"`,
  content-light (no `chunk_text`, `stdout`, `stderr`, `content`, `diff`,
  `snippet`, `argv`).
- `execution_progress_from_runtime_events()` pure aggregation function —
  accepts `Sequence[Any]` (model instances or dicts), processes events
  in order, skips malformed events without crashing.
- Message sanitization: warning/refusal messages truncated to 200 chars.
- All terminal events: last one wins (COMPLETION or FAILURE).
- `build_projection()` integration: optional `runtime_events` parameter;
  when provided, aggregates and attaches `execution_progress` to the
  desktop projection output. When omitted, field is absent.
- Desktop projection schema includes optional nullable `execution_progress`
  object with `additionalProperties: false`.
- 14 integration tests covering: no events, empty events, completion,
  failure, content-light, malformed events, multi-event aggregation.
- `ProgressTimelineWidget` Textual widget — renders projection as a compact
  card in DashboardScreen, no raw event access, empty state handling,
  40 unit tests.
- `DashboardProjection.execution_progress` optional field — wires the
  projection into the dashboard model without conditional DOM.
- Widget integrated into `DashboardScreen.compose()` and `_render_all()`.
- 8 forbidden fields verified absent in widget tests.
- 93/93 schemas valid (execution_progress schema + desktop schema with
  new field).

### Deferred (next phases)

| Phase | Scope | Status |
|-------|-------|--------|
| **P4b.1** | Wire into `projection.py` `build_projection()` | Implemented |
| **P4b.2** | Cockpit caller passes runtime events to `build_projection()` | Deferred |
| **P4c** | Textual ProgressTimeline widget | Implemented |
| **P4d** | pywebview ProgressTimeline widget | Deferred |

### Content-light proof (P4a + P4b.1)

All forbidden fields verified absent in model tests, integration tests,
schema validation, and model review:

| Forbidden field | Present in projection? | Evidence |
|----------------|----------------------|----------|
| `chunk_text` | No | Integration test `test_chunk_text_not_copied` |
| `stdout` / `stderr` | No | Only `stdout_bytes`/`stderr_bytes` |
| `content` | No | Model `extra="forbid"` + schema `additionalProperties: false` |
| `diff` / `snippet` | No | Model `extra="forbid"` + schema `additionalProperties: false` |
| `argv` | No | Model `extra="forbid"` |
| `output` / `patch` | No | Model `extra="forbid"` |

## Implementation Phases

| Phase | Scope | Dependencies | Status |
|-------|-------|-------------|--------|
| **P4a** | `execution_progress_from_runtime_events()` pure function + model | RuntimeStreamEvent models (done) | Implemented |
| **P4b.1** | Wire into projection.py `build_projection()`: optional `runtime_events` param, aggregate, attach `execution_progress` field | P4a | Implemented |
| **P4b.2** | Cockpit caller passes runtime events to `build_projection()` | P4b.1 | Deferred |
| **P4c** | Textual ProgressTimeline widget renders the projection | P4a | Implemented |
| **P4d** | pywebview desktop projection consumes `progress_events` | P4b.1 | Deferred |

## Cross-References

- [Stream Event Schema](../schemas/rig.relay.runtime_stream_event.v1.schema.json)
- [Desktop Projection Schema](../schemas/rig.relay.desktop_projection.v1.schema.json)
- [Projection Integrity Schema](../schemas/rig.relay.projection_integrity.v1.schema.json)
- [RuntimeSupervisor Architecture](runtime-supervisor.md)
- [Relay Desktop Projection Contract](relay-desktop-projection-contract.md)

## Recommended Implementation Slice

**P4b.1 — Wire aggregation into `build_projection()`.** Delivers the
integration seam (`runtime_events` parameter) and schema update
(optional `execution_progress` field). No UI changes. Next slice should
be P4b.2 (cockpit caller passes runtime events) or P4d (pywebview
widget).
