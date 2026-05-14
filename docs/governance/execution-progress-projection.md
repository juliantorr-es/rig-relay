# ExecutionProgressProjection — Design

## Status

**Design draft.** Not implemented. Defines the content-light read model for
RuntimeSupervisor execution summaries consumed by desktop/Textual/pywebview
projection surfaces.

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

## Implementation Phases

| Phase | Scope | Dependencies |
|-------|-------|-------------|
| **P4a** | `execution_progress_from_runtime_events()` pure function + model | RuntimeStreamEvent models (done) |
| **P4b** | Wire into projection.py `build_projection()`: collect runtime events, aggregate, emit `progress_events` | P4a |
| **P4c** | Textual ProgressTimeline widget renders the projection | P4a |
| **P4d** | pywebview desktop projection consumes `progress_events` | P4b |

## Cross-References

- [Stream Event Schema](../schemas/rig.relay.runtime_stream_event.v1.schema.json)
- [Desktop Projection Schema](../schemas/rig.relay.desktop_projection.v1.schema.json)
- [Projection Integrity Schema](../schemas/rig.relay.projection_integrity.v1.schema.json)
- [RuntimeSupervisor Architecture](runtime-supervisor.md)
- [Relay Desktop Projection Contract](relay-desktop-projection-contract.md)

## Recommended Implementation Slice

**P4a — Pure aggregation function + model.** Delivers the model,
aggregation function, and unit tests. No UI changes. No schema changes
(existing schemas are sufficient: data flows through DesktopProjection's
top-level `progress_events` array which is already schema-defined).
