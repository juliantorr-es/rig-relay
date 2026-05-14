# Rig Fleet Coordination Plane

**Status: Phase 3 — Runtime Lease Hardening (Complete). Phase 0 — Patch Proposal Models (Complete, 2026-05).**

## 1. Vision

The Rig Fleet Coordination Plane is an orchestrator-owned mechanism that enables multiple agents to coordinate without file collisions or the overhead of one Git worktree per agent. It moves the authority for shared-file mutation from individual agents to the orchestrator, enforcing a "patch-based" workflow for shared resources.

Core principle: **Agents propose; Orchestrator disposes.**

## 2. Coordination Model

The model is built on typed, append-only, receipt-backed events, and maps directly to the existing Cross-Session Coordination primitives.

### Concept Mapping

| Fleet Concept | existing Concept | Implementation |
|---|---|---|
| **agent_id** | `session_id` | Identifies the specific agent instance. |
| **mission_id** | N/A | Grouping identifier for related fleet sessions. |
| **WorkClaim** | `CoordinationTaskClaim` | Runtime record of a task assignment. |
| **PathLease** | `CoordinationPathReservation`| Exclusive or shared lease on file paths. |
| **AgentMessage** | N/A | New primitive for inter-agent communication. |
| **PatchProposal** | N/A | New primitive for proposed file mutations. |

### Core Entities

| Entity | Description |
|--------|-------------|
| **AgentSession** | A durable identity for an active agent within a fleet mission. Maps to `CoordinationSession`. |
| **WorkClaim** | A claim on a specific mission, task, or subtask. Maps to `CoordinationTaskClaim`. |
| **PathLease** | An exclusive or shared lease on a set of file paths. Maps to `CoordinationPathReservation`. |
| **AgentMessage** | A typed message sent between agents or from agent to orchestrator. |
| **CoordinationEvent** | A canonical entry in the fleet event log (`rig.fleet.*`). |
| **ConflictNotice** | Evidence of a coordination collision. Maps to `CoordinationConflict`. |
| **PatchProposal** | A structured proposal to mutate files, containing metadata and artifact references (Phase 0). No embedded diffs. |
| **PatchDecision** | The orchestrator's decision (accept/reject/needs_revision/supersede) on a PatchProposal (Phase 0). |
| **FleetMergeDecision** | Legacy merge decision model. Superseded by PatchDecision in Phase 0. |

## 3. Lease Semantics

Path-level coordination prevents concurrent mutation of the same files.

- **Exclusive Write Lease**: Only one agent may hold a write lease on a path at a time.
- **Shared Read Lease**: Multiple agents may hold read leases on the same path.
- **Path Hashing Policy**:
  - **Internal**: The coordination store uses `stable_path_key` (repo-relative, un-salted) for collision detection.
  - **External**: The observability stream uses `salted_path_hash` (salted SHA256) for privacy-preserving event logs.
- **Lease Expiry**: Leases have a TTL and must be renewed by the holder. Expired leases become "stale".
- **Blocked Claims**: If a `claim_paths` request overlaps an existing exclusive lease, it is refused with a `blocked_by_lease` ConflictNotice.
- **Explicit Handoff**: An agent may voluntarily release a lease or request a handoff to another agent.

## 4. Orchestrator Authority

The orchestrator is the only entity with the authority to mutate the canonical worktree for shared files.

1. **Isolation**: Agents work in private scratch spaces or restricted subdirectories where they have exclusive authority.
2. **Proposal**: When an agent needs to change a shared file, it submits a `PatchProposal`.
3. **Validation**: The orchestrator (or a specialized validation agent) verifies the patch (lints, tests, collision checks).
4. **Application**: The orchestrator applies the accepted patch to the canonical worktree.
5. **Direct Mutation**: Guarded direct mutation is allowed only when an agent holds a verified exclusive write lease and the orchestrator has delegated mutation authority for that specific mission.

## 5. Operations

| Operation | Description |
|-----------|-------------|
| `claim_paths` | Request an exclusive or shared lease on one or more paths. |
| `release_paths` | Voluntarily release held leases. |
| `renew_lease` | Extend the TTL of an active lease. |
| `query_claims` | Inspect current active leases and work claims. |
| `send_message` | Send a typed message (e.g., `blocker`, `handoff`, `status_update`). |
| `report_blocker` | Signal that a task is blocked and identify the dependency. |
| `submit_patch` | Submit a `PatchProposal` for orchestrator review. |
| `request_review` | Signal that a piece of work is ready for human or model review. |
| `mark_done` | Signal completion of a work claim with an outcome summary. |

## 6. Event Semantics

The fleet event log (`events.jsonl`) is the source of truth.

- **Append-only**: Events are never deleted or modified.
- **Structure**: Every event is a JSON object with:
  - `schema_version`: (e.g., `rig.fleet.coordination_event.v1`)
  - `event_id`: Unique identifier (UUID).
  - `mission_id`: Link to the parent mission.
  - `agent_id`: Identity of the agent emitting the event.
  - `created_at`: ISO8601 timestamp.
  - `parent_event_id`: (Optional) Link to the event that triggered this one.
- **Content-Light**: No raw prompts, secrets, or large blobs (stdout/stderr) are allowed in the event log. Diffs appear only in dedicated `patch_proposal` artifacts, not in the event log itself.

## 7.5 Fleet Queue (Phase 0)

The fleet queue is an append-only event-sourced primitive that allows the orchestrator to accept typed queue items, order them deterministically, and dispatch eligible items one at a time.

### Queue Item Kinds

| Kind | Purpose |
|------|---------|
| `message` | Inter-agent or system message |
| `runtime_exec` | A runtime tool execution (validate, search_replace, write_file, bash) |
| `validate` | A validation-only run (read-only tool execution) |
| `handoff_note` | Orchestrator-directed handoff between agents |
| `pause` | Request to pause processing |
| `resume` | Request to resume processing |

### Item State Machine

```
    ┌─────────┐
    │ QUEUED  │─── cancel ──→ CANCELLED
    └────┬────┘
         │ mark_running
         v
    ┌─────────┐
    │ RUNNING │─── mark_completed ──→ COMPLETED
    └────┬────┘
         ├── mark_failed ──→ FAILED
         └── mark_blocked ──→ BLOCKED
```

Additional transition: `superseded` (set when a newer item replaces this one).

### Ordering Rules

1. Only items with status `queued` are eligible.
2. `depends_on` blocks an item until all dependencies reach a terminal state (completed, failed, cancelled, or superseded).
3. Items are sorted by: highest `priority` first, then `created_at` ascending (FIFO), then `queue_item_id` (deterministic tiebreaker).
4. Cancelled items are never runnable.

### Storage

- Canonical source: append-only JSONL (`FleetQueueEvent` rows).
- Current queue state (`FleetQueueSnapshot`) is derived by replaying events on read.
- No DuckDB indexing. No writes to `/Users/user/.rig/relay`.

### Content-Light

Queue events must not contain raw prompts, stdout, stderr, content, diffs, patches, secrets, argv, snippets, or file contents. Item payloads carry only summary/ref/hash.

### Phase 0 Queue Runner (2026-05)

`FleetQueueRunner` (in `rig_relay/coordination/fleet_queue_runner.py`) connects queue items to governed runtime execution.

Key behaviours:
- **One item per call**: `run_once()` selects the next runnable item, processes it, and returns a `FleetQueueRunnerResult`.
- **Event-sourced transitions**: running event before dispatch; completed/failed/blocked event after.
- **Supported item kinds**:
  - `validate` / `runtime_exec`: dispatched through `RuntimeToolExecutionRunner` (governed path with leases, auditing).
  - `message` / `handoff_note`: completed immediately, no runtime mutation.
  - `pause` / `resume`: completed immediately (no-op in Phase 0).
- **Unsupported kinds**: marked blocked with `error_kind: unsupported_queue_item_kind`.
- **Content-light result**: `FleetQueueRunnerResult` carries only `queue_item_id`, `decision`, `runtime_result_sha256`, `receipt_sha256`, `tool_name`, `error_kind`, `sanitised reason`, and `changed_paths`. No stdout, stderr, content, diffs, patches, prompts, secrets, argv, or snippets.

### Phase 0 Limitations

- No full scheduler: `next_runnable_item()` and `run_once()` run one item at a time.
- No parallel execution.
- No patch application or proposal integration.
- No TUI queue panel.
- Not thread-safe or multi-process safe (no file locking).
- No supervisor projection integration.
- No DuckDB index.

## 7.6 Fleet Projection / Read Model (Phase 0)

`FleetProjection` (in `rig_relay/coordination/fleet_projection.py`) is a content-light read model that summarizes fleet queue state, leases, patch proposals, blockers, and agent/session liveness for the Textual Rig Console TUI.

### Data Sources

The projection reads from existing fleet/coordination artifacts:
- **Fleet Queue**: `FleetQueue.list_items()` for `FleetQueueSnapshot` → status counts, next runnable item, replay diagnostics.
- **PathLeaseManager**: `query_active_leases()` for active lease counts and modes.
- **Patch proposals**: `.fleet/patch-proposals/*.json` for pending/applied/rejected/revised counts.
- **Coordination events**: Recent event count (future: agent sessions from coordination store).

Missing artifacts produce empty-safe defaults — the projection never crashes.

### Sub-models

| Model | Fields | Content-Light? |
|-------|--------|----------------|
| `FleetAgentSummary` | total_agents, active_sessions, recent_heartbeats, stale_sessions | Yes |
| `FleetQueueSummary` | queued, running, blocked, completed, failed, cancelled, total, highest_priority, next_item, replay | Yes |
| `FleetQueueNextItem` | queue_item_id, kind, priority, created_at | Yes |
| `FleetReplayDiagnostics` | total_lines, valid_events, malformed_lines, invalid_events, skipped_unknown_kind, total_skipped | Yes |
| `FleetLeaseSummary` | total_active, exclusive_write, shared_read, stale, expired, path_count | Yes |
| `FleetBlockerSummary` | total_blockers, blocker_kinds, oldest_blocked_at | Yes |
| `FleetPatchProposalSummary` | pending, applied, rejected, revised, total, oldest_pending_at, latest_proposal_id | Yes |
| `FleetProjection` (root) | schema_version, projection_id, created_at, fleet_name, agents, queue, leases, blockers, patches, recent_event_count | Yes |

### Worker Functions

- `build_queue_summary(queue: FleetQueue | None) → FleetQueueSummary`: Reads queue snapshot, builds counts + next item + replay diagnostics.
- `build_queue_summary_from_snapshot(snapshot: FleetQueueSnapshot) → FleetQueueSummary`: From an existing snapshot (no I/O).
- `build_lease_summary(coordination_root: Path | None) → FleetLeaseSummary`: Reads active leases from `PathLeaseManager`.
- `build_patch_proposal_summary(patch_root: Path | None) → FleetPatchProposalSummary`: Scans patch proposal JSON files.

### Content-Light Enforcement

All sub-models have `ConfigDict(extra="forbid")`. The `FleetProjection` JSON Schema has `additionalProperties:false` at every level (root, agents, queue, next_item, replay, leases, blockers, patches). Forbidden field names: `prompt`, `stdout`, `stderr`, `content`, `diff`, `patch`, `secret`, `argv`, `snippet`, `file_content`, `raw_prompt`, `raw_output`.

### TUI Integration

- `providers.py`: `_build_fleet_projection()` reads queue events from `coordination_root/queue/events.jsonl` and builds a `FleetQueueSummary` via `build_queue_summary(FleetQueue(...))`.
- `widgets/fleet_panel.py`: `FleetPanelWidget` renders queue, leases, blockers, patches, agents, next item, and replay diagnostics rows. Read-only — no mutation keybindings.

### Tests

43 tests in `tests/coordination/test_fleet_projection.py`, 22 tests in `tests/cli/textual_ui/rig_console/test_fleet_panel.py` (6 for next_item/replay formatting).

### Schema

`docs/schemas/rig.fleet.projection.v1.schema.json` — validates serialized `FleetProjection` JSON with `additionalProperties:false` on all nested objects.

## 7. Storage Design

- **Canonical Store**: Local files under `.rig/fleet/`.
  - `events.jsonl`: The primary event stream.
  - `leases/`: Active lease state (JSON).
  - `proposals/`: Patch artifacts.
- **Index Cache**: Optional DuckDB index for efficient querying.
  - Agents may READ from DuckDB.
  - Agents may NEVER directly write to DuckDB.
  - The orchestrator or a background process maintains the index from `events.jsonl`.
- **Concurrency**: File-system atomic replacement and optional flock are used as local-first guards.

## 8. Failure Behavior

- **Heartbeat Expiry**: Agents must heartbeat. A missed heartbeat triggers lease expiry.
- **Stale Lease Recovery**: The orchestrator may reclaim stale leases after a grace period.
- **Idempotency**: All operations (especially `claim_paths` and `submit_patch`) must be idempotent based on `event_id` or `proposal_id`.
- **Conflict Resolution**: The orchestrator is the final arbiter for conflicting claims.

## 9. UI/Projections

The Fleet Coordination Plane provides compact projections for:
- **Fleet Pulse**: Active agents and their current tasks.
- **Lease Map**: Visual or tabular view of path contention.
- **Message Board**: Recent inter-agent communications.
- **Review Queue**: Pending patch proposals and review requests.

## 10. Phase 0 — Patch Proposal Workflow

**Design principle**: Agents propose; orchestrator disposes.

Phase 0 implements the minimal artifact workflow: agents create `PatchProposal` models, and orchestrators issue `PatchDecision` models. Patch application is deferred to a future phase.

### Models

Defined in `rig_relay/coordination/patch_proposal.py`. Re-exported through `fleet_models.py` → `models.py`.

| Model | Purpose |
|-------|---------|
| `PatchProposal` | Describes intended mutations: proposal_id, mission_id, agent_id, title, summary, touched_paths (with hashes), expected_before_sha256, and artifact_refs. |
| `PatchProposalArtifactRef` | Content-light reference to an external diff/patch artifact (path, sha256, size_bytes, media_type). |
| `PatchDecision` | Orchestrator decision on a proposal: accepted, rejected, needs_revision, or superseded. |
| `CreateProposalResult` | Dataclass holding the created proposal and its stable fingerprint. |

### Proposal Status Lifecycle

```
    ┌─────────┐
    │ pending  │
    └────┬─────┘
         │
    ┌────┴──────┐
    │ orchestrator │
    │  decides  │
    └────┬──────┘
         ├──→ accepted
         ├──→ rejected
         ├──→ needs_revision
         └──→ superseded
```

### Content-Light Boundary

- **Never embedded**: raw diffs, patches, file contents, stdout, stderr, secrets.
- **Metadata only**: `PatchProposal` carries touched_paths, hashes, and artifact refs.
- **Artifact refs**: point to external diff files by path+sha256. The raw diff lives outside the coordination event stream.
- **Fingerprint**: `compute_proposal_fingerprint` computes a stable SHA256 over all fields except `proposal_id` and `schema_version`. Used for deduplication and change detection.

### Relationship to Path Leases

- **Independent**: A PatchProposal does not require a held path lease. Agents may submit proposals for any paths.
- **Application gate**: In a future phase, the orchestrator will acquire path leases before applying accepted proposals.
- **Pre-flight check**: The `expected_before_sha256` field records expected file states at proposal time. The orchestrator can verify these against actual file hashes before applying.

### Orchestrator Authority

- **Only the orchestrator creates PatchDecisions.**
- **Only the orchestrator applies patches** (future phase).
- Agents propose; the orchestrator disposes.

### Deferred Features (Post-Phase 0)

- **Patch application**: No code applies proposals to the worktree. Only models exist.
- **Lease integration**: No automatic lease acquisition on proposal acceptance.
- **Orchestrator loop**: No runtime loop that polls for pending proposals and auto-decides.
- **Revisions**: No `needs_revision` → resubmit → re-decide cycle enforcement.
- **Supersede propagation**: No automatic cascading of superseded status to dependent proposals.
- **TUI panel**: No queue or proposal review panel in the cockpit.
