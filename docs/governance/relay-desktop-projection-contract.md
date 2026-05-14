# Relay Desktop Projection Contract

## Status

**Draft.** Derived from Rig's
[Workspace UI Projection Contract](https://github.com/juliantorr-es/Rig/blob/main/docs/architecture/workspace-ui-projection-contract.md)
and adapted for Rig Relay's desktop cockpit.

## Purpose

This contract defines the projection widgets that the backend may render into
the Rig Relay desktop cockpit. The frontend is a **renderer, not a governor**.

## Core Rule

**Backend authors the state. Frontend renders the state. Frontend emits
intentions only.**

- Frontend must not infer checkpointability, lane readiness, or promotion
  decisions.
- Frontend must not fabricate state.
- Missing data degrades to explicit placeholder text, not fabricated state.

## Widget Types

### OperatorHeader

Identifies the Relay session and operator.

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Current Relay session ID |
| `mode` | string | `headless`, `legacy_tui`, or `desktop` |
| `app_version` | string | Current Rig Relay version |
| `uptime_seconds` | integer | Session uptime |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Session lifecycle decisions, task claims

### SafetyState

Shows current safety posture.

| Field | Type | Description |
|---|---|---|
| `dirty_files` | integer | Number of dirty (modified/staged/untracked) files |
| `active_leases` | integer | Number of active coordination leases |
| `stale_leases` | integer | Number of expired leases |
| `authorization_required` | boolean | Whether next action needs authorization |
| `policy_guard_active` | boolean | Whether dirty-file guard is enforcing |

**Allowed intentions:** `refresh_projection`, `run_validation`

**Forbidden frontend inference:** Whether mutation is safe, whether guard
should be bypassed

### NextAction

Shows the backend-recommended next safe action.

| Field | Type | Description |
|---|---|---|
| `action` | string | Recommended action name |
| `rationale` | string | Why this action is recommended |
| `ready` | boolean | Whether the action can be taken now |
| `blockers` | string[] | Reasons the action is not ready |
| `validations_to_run` | string[] | Validations that should pass first |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Changing the recommendation, executing
without backend validation

### ActiveChildSessions

Shows active child sessions (delegate/fleet).

| Field | Type | Description |
|---|---|---|
| `active` | integer | Number of active child sessions |
| `max` | integer | Maximum allowed child sessions |
| `available_slots` | integer | Slots remaining |
| `active_writers` | integer | Child sessions holding write leases |
| `active_readers` | integer | Child sessions in read-only mode |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Creating child sessions, terminating child
sessions, promoting child sessions

### ValidationSummary

Summarizes the last validation run.

| Field | Type | Description |
|---|---|---|
| `status` | string | `passed`, `failed`, `not_run`, `running` |
| `passed_count` | integer | Number of passed checks |
| `failed_count` | integer | Number of failed checks |
| `warnings` | string[] | Non-blocking warnings |
| `last_run_at` | string | ISO 8601 timestamp |
| `duration_ms` | integer | Duration of last validation run |

**Allowed intentions:** `run_validation`, `refresh_projection`

**Forbidden frontend inference:** Whether validation results authorize mutation

### StorageBudget

Shows storage budget for build artifacts.

| Field | Type | Description |
|---|---|---|
| `status` | string | `ok`, `warn`, `over_budget`, `fleet_blocked` |
| `total_size_mb` | number | Total build artifact size |
| `prune_candidates` | integer | Files eligible for pruning |
| `rollup_candidates` | integer | JSONL files without Parquet rollup |
| `recommendations` | string[] | Recommended actions |

**Allowed intentions:** `gc_artifacts`, `refresh_projection`

**Forbidden frontend inference:** Automatic garbage collection, storage policy

### ReceiptTimeline

Shows bounded history of durable evidence.

| Field | Type | Description |
|---|---|---|
| `receipts` | array | Bounded list of recent receipt summaries |
| `receipts[n].kind` | string | Receipt kind (checkpoint, authorization, validation, etc.) |
| `receipts[n].summary` | string | Human-readable summary |
| `receipts[n].timestamp` | string | ISO 8601 timestamp |
| `receipts[n].sha256` | string | Receipt content hash |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Receipt creation, receipt verification policy

### LatestIntentResult

Shows the result of the last intent execution.

| Field | Type | Description |
|---|---|---|
| `intent_name` | string | Name of the executed intent |
| `status` | string | `completed`, `refused`, `failed`, `running` |
| `result_kind` | string | Type of result data |
| `output_ref_count` | integer | Number of output references |
| `result_sha256` | string | SHA256 of result JSON |
| `projection_seq` | integer | Projection sequence number |
| `completed_at` | string | ISO 8601 timestamp |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Re-executing failed intents without
authorization

### RefinementBacklog

Shows pending refinement items (optional, for built-in tool refinement).

| Field | Type | Description |
|---|---|---|
| `pending` | integer | Number of pending refinement items |
| `refined` | integer | Number of completed refinement items |
| `last_refined_at` | string | ISO 8601 timestamp |

**Allowed intentions:** `refresh_projection`

**Forbidden frontend inference:** Refinement policy decisions

## Widget Grouping

Widgets are rendered in three groups within the cockpit:

1. **Header zone** (always visible): OperatorHeader, SafetyState, NextAction
2. **Activity zone** (scrollable): ActiveChildSessions, ValidationSummary,
   StorageBudget, ReceiptTimeline, LatestIntentResult
3. **Footer zone** (collapsible): RefinementBacklog

## Contract Rules

1. Backend authors the widget state.
2. Frontend renders the widget state.
3. Frontend emits intentions only.
4. Frontend must not infer checkpointability, session readiness, promotion
   decisions, or storage policy.
5. Missing data degrades to explicit placeholder (e.g., `"available": false`,
   `"status": "unknown"`), not fabricated state.
6. Widget fields are drawn from actual artifact schemas — never invented or
   inferred.
7. Read-only actions are listed in `read_only_actions` on the projection.
   The frontend renders these as available buttons, not as authoritative
   approvals.

## Mapping from Rig Widgets

| Rig widget | Rig Relay widget | Adaptation |
|---|---|---|
| WorkspaceHeader | OperatorHeader | Session ID replaces workspace ID |
| WorkspaceGitState | SafetyState | Focus on dirty files + leases, not git state |
| WorkspaceLaneSummary | ActiveChildSessions | Child sessions replace lanes |
| AgentLaneCard | — | Deferred to port_next; ActiveChildSessionCard |
| LaneReviewCard | — | Deferred to port_next; ParentConvergenceCard |
| PromotionPlanCard | — | Deferred to port_next; ReadyWorkPlanCard |
| LaneRecommendationCard | NextAction | Direct mapping with Relay-specific fields |
| CommandProgressCard | — | Absorbed by progress event stream |
| ReceiptTimeline | ReceiptTimeline | Same widget, Relay receipt kinds |
| — | ValidationSummary | Rig Relay-specific |
| — | StorageBudget | Rig Relay-specific |
| — | LatestIntentResult | Rig Relay-specific |
| — | RefinementBacklog | Rig Relay-specific |

## Integrity Contract

The projection integrity assessment is a content-light check attached to
every desktop projection. It is **not a separate widget** — it decorates the
projection with trust metadata.

| Field | Type | Description |
|---|---|---|
| `integrity_status` | string | `verified`, `degraded`, `stale`, `orphaned`, `unknown` |
| `contract_status` | string | `satisfied`, `partial`, `violated`, `not_applicable` |
| `violation_count` | integer | Total integrity violations |
| `violations` | array | List of violation objects (code, message, severity, optional widget_name/receipt_id/path) |
| `checked_at` | string | ISO 8601 timestamp |
| `receipt_count` | integer | Number of receipt records evaluated |
| `stale_receipt_count` | integer | Receipts exceeding staleness threshold |
| `orphaned_receipt_count` | integer | Receipts missing session_id or tool_name |
| `authority_backed` | boolean | Whether all claimed authorities have receipt backing |

**Integrity status priority:** VERIFIED > STALE > ORPHANED > DEGRADED > UNKNOWN

**Contract status rules:**
- NOT_APPLICABLE when no authorities or widgets claimed
- SATISFIED when zero violations
- VIOLATED when any error-severity violation exists
- PARTIAL otherwise

**Forbidden frontend inference:** Modifying integrity policy, bypassing
violations, interpreting violations as authorization to mutate

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Desktop Projection Schema](../schemas/rig.relay.desktop_projection.v1.schema.json)
- [Projection Integrity Schema](../schemas/rig.relay.projection_integrity.v1.schema.json)
- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
