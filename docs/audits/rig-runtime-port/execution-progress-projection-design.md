# ExecutionProgress Projection Design — Audit Record

## Design Authority

| Field | Value |
|-------|-------|
| **Date** | 2026-06 |
| **Author** | Rig Relay agent (governance-audit) |
| **Status** | Design draft — not implemented |
| **Scope** | Runtime event → projection aggregation contract |

## Context

RuntimeSupervisor (P2b) now emits structured `RuntimeStreamEvent` objects
during subprocess execution. These include:

- STATUS events (starting, running)
- STDOUT_CHUNK / STDERR_CHUNK events (bounded, capped)
- HEARTBEAT events (periodic liveness)
- WARNING events (stall detected, truncation applied, etc.)
- COMPLETION events (succeeded, failed — content-light)
- FAILURE events (timed_out, cancelled, blocked — content-light)

The existing `projection.py` builder and `projection_widgets.py` taxonomy
already define a `ProgressTimeline` widget and a `progress_events` field
in the `PROJECTION_FIELD_TO_WIDGET` map — but **no data source populates it**.

## Design Decisions

### Decision 1: Pure aggregation function

**Decision:** Build `execution_progress_from_runtime_events()` as a pure
function (no I/O, no side effects) that transforms a `list[RuntimeStreamEvent]`
into a single `ExecutionProgressProjection`.

**Rationale:** Pure functions are testable, deterministic, and composable.
The projection builder (`projection.py`) can call this function when runtime
event data is available.

**Risk:** Low. The function depends only on Pydantic models that are already
stable.

### Decision 2: No new schema

**Decision:** Do not create a new JSON Schema for ExecutionProgressProjection.
The data flows through the existing `DesktopProjection.progress_events` array,
which is already schema-defined as `"type": "array"` with no item schema
enforcement at v1.

**Rationale:** Adding a schema creates maintenance burden. The projection's
top-level `progress_events` field is already reserved in the schema and
widget taxonomy. The Pydantic model `ExecutionProgressProjection` at the
code level provides type safety.

**Risk:** Low. Schema enforcement can be added in a future v2 if needed.

### Decision 3: No chunk_text in projection

**Decision:** `chunk_text` from `RuntimeOutputChunkEvent` is NEVER included
in the projection. Only aggregated byte counts and SHA256 hashes from
terminal events appear.

**Rationale:** Content-light terminal events are the contract. Raw chunks
are ephemeral — they exist only in the stream/chat pane during live execution.

**Risk:** None. This is an explicit content-light policy.

### Decision 4: Terminal event wins status

**Decision:** Once a COMPLETION or FAILURE event is processed, its status
overrides any non-terminal status (STATUS, HEARTBEAT). WARNING events after
terminal are ignored.

**Rationale:** Terminal events are authoritative. Non-terminal events after
completion are logically impossible (heartbeats stop after terminal event
by construction), but the aggregation handles out-of-order or malformed
streams defensively.

**Risk:** Low. RuntimeSupervisor guarantees heartbeat stop after terminal
event, but the projection layer should be defensive.

### Decision 5: Existing integrity codes suffice

**Decision:** Do not add new `ProjectionViolationCode` entries for execution
progress. Existing codes (`MISSING_RECEIPT`, `STALE_RECEIPT`,
`AUTHORITY_UNBACKED`) cover all assessment scenarios.

**Rationale:** The execution progress is assessed the same way as other
projection data: check for receipt/envelope/audit backing on the terminal
event. No new violation semantics are needed.

**Risk:** None.

## Gap Analysis

### Gap A: No runtime event collection in projection builder

`projection.py` has no mechanism to collect or pass runtime events into
`build_projection()`. Currently the builder collects receipts, coordination
state, provider status, and storage data — but not runtime stream events.

**Resolution:** P4b. The `build_projection()` signature would gain an
optional `runtime_events` parameter. When provided, the function calls
`execution_progress_from_runtime_events()` and populates `progress_events`.

### Gap B: ProgressTimeline widget has no renderer

The widget name exists in the taxonomy but no Textual widget class renders it.

**Resolution:** P4c. Implement `ProgressTimelineWidget` in
`vibe/cli/textual_ui/rig_console/widgets/` following the pattern of
`EvidenceRailWidget` (content-light, scrollable, status-driven).

### Gap C: No session-to-execution linkage

`SessionPaneProjection` has `status` and `last_heartbeat_at` fields but no
way to link to an `ExecutionProgressProjection`. Multiple executions may
exist per session (e.g., fleet tasks).

**Resolution:** Deferred. The `ExecutionProgressProjection` carries
`request_id` and `lease_id` which can be matched to session leases via the
coordination store. This is a UI composition concern, not a data model concern.

## Cross-References

- [ExecutionProgressProjection Design](../governance/execution-progress-projection.md)
- [RuntimeSupervisor Architecture](../governance/runtime-supervisor.md)
- [Relay Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Rig-to-Relay Runtime Audit](rig-to-relay-runtime-audit.md)
- [Port Roadmap](port-roadmap.md)
- [Concept Map](concept-map.md)
