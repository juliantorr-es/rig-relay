# Rig Fleet Coordination Plane

**Status: Foundation Implemented (Phase 3 Closure, 2026-05).**

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
| **PatchProposal** | A structured proposal to mutate files, containing a diff and rationale. |
| **MergeDecision** | The orchestrator's decision (accept/reject/revise) on a patch proposal. |

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
