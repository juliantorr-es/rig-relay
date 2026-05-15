# Desktop HITL Boundary

Rig Relay's desktop surface operates under a strict human-in-the-loop
(HITL) contract. The desktop UI renders backend projections and sends
intents. The backend validates state and owns all policy. Execution
remains disabled until a separate Relay execution contract exists.

## Layered responsibility

```
Desktop UI       Renders projections, sends intents.
                 Dumb renderer — no policy, no hashing, no ranking.

Desktop Backend  Validates state, processes intents.
                 Owns policy, refusal codes, approval gating.

Ralph            Owns Ralph state transitions (scan, approve, decline).
                 Consumes projections, produces rank and mission.

Relay            Executes approved missions (future).
                 Not yet wired through this boundary.
```

## Action boundaries

| Layer | Allowed | Forbidden |
|---|---|---|
| Frontend | Render backend projections. Send backend-defined action payloads. Display refusal codes + messages. | Compute hashes. Rank candidates. Infer approval policy. Decide `execution_enabled`. Inspect raw scanner internals. |
| Backend | Validate run_id, scan_id, panel_sha256, mission_candidate_sha256. Apply structured refusal codes. Own state transitions. | Execute approved missions. Write to canonical findings. Mutate source code. Open external network calls. |
| Ralph (v0.7) | Scan projections. Rank by deterministic policy. Produce approval-ready panel. Accept/decline with identity binding. | Execute missions. Schedule daemon runs. Mutate state outside intent handlers. |

## Intent result envelope

All desktop intents that reach this boundary return:

```json
{
  "schema_version": "rig.desktop.intent_result.v1",
  "intent_kind": "ralph_approve",
  "ok": false,
  "status": "refused",
  "error_code": "stale_panel_hash",
  "message": "Panel hash does not match current state.",
  "execution_enabled": false
}
```

`ok: true` means the intent was accepted. `ok: false` means it was
refused. `execution_enabled` is always `false` in this phase.

## Identity binding

Approval/decline decisions are bound to four identities:

- `run_id` — the desktop run session that produced this scan
- `scan_id` — the specific scan within that run
- `panel_sha256` — content hash of the panel shown to the user
- `mission_candidate_sha256` — content hash of the mission candidate

All four must match the current backend state. Any mismatch produces a
structured refusal code.

## Refusal codes

| Code | Meaning |
|---|---|
| `no_scan_state` | No scan has been run |
| `stale_run_id` | Run ID doesn't match — state replaced |
| `stale_scan_id` | Scan ID doesn't match — rescan occurred |
| `stale_panel_hash` | Panel hash mismatch |
| `stale_mission_hash` | Mission candidate hash mismatch |
| `missing_mission_candidate` | No candidate present |
| `unsupported_action` | Unknown intent |
| `invalid_payload` | Required fields missing |
| `execution_disabled` | Execution not yet implemented |
| `internal_error` | Unexpected failure |

## Execution contract (future)

When execution is implemented, it will be a separate contract:

- Execution requires explicit approval through this HITL boundary
- Approved decisions reference exact run_id + scan_id + hashes
- The execution path validates hashes before acting
- The execution path emits receipts
- The execution path returns results through the same intent envelope

No execution path will bypass the HITL boundary.

## Desktop event vocabulary

Stable event names for future analytics compiler integration:

- `rig.desktop.ralph.scan.requested`
- `rig.desktop.ralph.scan.completed`
- `rig.desktop.ralph.approval.requested`
- `rig.desktop.ralph.approval.accepted`
- `rig.desktop.ralph.approval.refused`
- `rig.desktop.ralph.decline.accepted`
- `rig.desktop.ralph.rescan.completed`

## Durable state (v0.8)

Ralph run state is now persisted through `RalphRunStateStore`:

- In-memory for tests and transient use
- Filesystem-backed under `.rig/ralph/runs/`
- One JSON file per run_id
- Current run pointer tracked via `.rig/ralph/current_run.json`
- Atomic writes via temp file + rename

Run state includes:
- `run_id`, `scan_id`, `status`, `phase`, `approval_state`
- `panel_sha256`, `mission_candidate_sha256`, `input_snapshot_sha256`
- `execution_enabled` (always false)
- `created_at`, `updated_at`, `expires_at`
- `latest_decision_event_id`, `latest_decision_receipt_sha256`

## Decision events and receipts (v0.8)

Every approve/decline/refusal produces:

1. A `DecisionEvent` appended to `.rig/ralph/events/ralph_decisions.jsonl`
   (append-only JSONL ledger)
2. A `DecisionReceipt` stored under `.rig/ralph/receipts/`
   (content-addressed JSON file)

Event kinds: `ralph.decision.approved`, `ralph.decision.declined`,
`ralph.decision.refused`, `ralph.decision.expired`.

`event_sha256` and `receipt_sha256` are separate, computed from
stable fields (timestamps excluded).

## Desktop event stream (v0.8)

`DesktopEventSink` interface with `InMemoryDesktopEventSink` and
`NoOpDesktopEventSink` implementations. Events carry `event_sha256`
computed from stable fields. Future: JSONL sink, analytics compiler
integration.

## Read-only mission contract (v0.8)

`RalphReadOnlyMissionRequest/Plan/Result` define the future execution
contract without implementing execution. All plans return
`execution_enabled=False` and `implementation_status=contract_only`.

Forbidden capabilities include: source_code_mutation, git_commit,
external_network_calls, background_recursion, etc.

## ToolRuntime boundary

See `docs/governance/tool-runtime-boundary.md` for the full
ToolRuntime boundary definition. Ralph is not ToolRuntime.
ToolRuntime will be the future owner of governed tool execution.
