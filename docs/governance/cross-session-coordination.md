# Cross-Session Coordination

Rig Relay sessions coordinate through typed state, not chat transcripts.

Core coordination primitives:
- task claims
- path reservations
- heartbeats
- published artifacts
- structured conflicts
- handoffs
- compact state projections

Local implementation uses a file-backed coordination store under `.build/rig-relay/coordination/`.
The store is append-only where practical and uses atomic replacement for durable state files.

Doctrine:
- Read reservations may overlap.
- Write reservations must not overlap.
- Expired leases become stale, not silently deleted.
- Child sessions should publish artifacts and status updates through the coordination plane.
- Parent sessions consume compact projections, not raw transcripts.

This is the shared coordination layer that future delegate/fleet orchestration will use for real-time session visibility.

## Evolution: Fleet Coordination

As of Phase Q (2026-05), Rig Relay is evolving towards a **Fleet Coordination Plane**. This model extends the local-first cross-session primitives to support orchestrator-driven fleets:

- **Orchestrator Authority**: The orchestrator is the sole authority for mutating shared files; agents submit patch proposals.
- **Unified Fleet Log**: Coordination events use the `rig.fleet.*` namespace.
- **Inter-Agent Messaging**: A new `AgentMessage` primitive enables typed coordination (blockers, help needed) without informal chat.
- **Mission Context**: The `mission_id` groups related fleet sessions.

See [Fleet Coordination Plane](fleet-coordination-plane.md) for the full specification.

## Coordination Events

Every coordination primitive emits a canonical event row into the session's `observability.jsonl` stream.
These events are the structured source for delegate/fleet evaluation datasets — they turn runtime orchestration into measurable behavioral evidence.

### Normalized Payload Contracts

As of the Coordination Dataset Row Normalization milestone, every `coord.*` and checkpoint event uses a normalized payload contract designed for reliable transformation into derived evaluation rows. Payloads are:

- **Hash-heavy, content-light**: file paths are replaced with salted SHA256 hashes (`sha256:<hex>`). No raw file contents, raw prompts, or model outputs appear in normalized payloads.
- **Canonical field names**: all payloads use consistent field names (`session_id`, `task_id`, `event_kind`, `status`, `path_hashes`, `path_count`, `artifact_sha256`, `conflict_kind`, etc.).
- **Null-omission consistent**: unavailable fields are omitted (or set to `null`) rather than populated with placeholder values.
- **Schema-backed**: four new evaluation schemas define the row contracts — see `docs/schemas/` for `rig.relay.cross_session_coordination.v1`, `rig.relay.coordination_conflict.v1`, `rig.relay.artifact_reuse.v1`, and `rig.relay.checkpoint_eval.v1`.

This normalization is what enables future exporters to produce clean derived datasets without ad-hoc field mapping.

### Session Lifecycle Events

| Event Name | Description |
|------------|-------------|
| `coord.session.registered` | A new session registers in the coordination plane. |
| `coord.session.heartbeat` | Periodic liveness signal from an active session. |

### Task Claim Events

| Event Name | Description |
|------------|-------------|
| `coord.task.claimed` | A session claims a task and begins work. |
| `coord.task.released` | A session releases a task claim (completed, failed, or abandoned). |

### Path Reservation Events

| Event Name | Description |
|------------|-------------|
| `coord.path.reserved` | A session reserves one or more paths for read or write. |
| `coord.path.released` | A session releases a path reservation. |
| `coord.path.reservation_refused` | A reservation request is refused due to an existing write reservation. |

### Artifact Events

| Event Name | Description |
|------------|-------------|
| `coord.artifact.published` | A session publishes a typed artifact (search results, git state, tool output) for reuse by other sessions. |

### Conflict Events

| Event Name | Description |
|------------|-------------|
| `coord.conflict.reported` | A session reports a coordination conflict (path overlap, stale lease, dirty file collision). |

### Handoff Events

| Event Name | Description |
|------------|-------------|
| `coord.handoff.requested` | A session requests a handoff of responsibility to another session. |
| `coord.handoff.accepted` | The target session accepts the handoff. |
| `coord.handoff.rejected` | The target session rejects the handoff. |

### Lease Lifecycle Events

| Event Name | Description |
|------------|-------------|
| `coord.projection.read` | A session reads a compact state projection (consumes coordination state without raw transcripts). |
| `coord.lease.expired` | A lease reaches its TTL without renewal. |
| `coord.lease.marked_stale` | A lease is explicitly marked stale (superseded or invalidated). |

## Lease Lifecycle

Leases are exclusive or shared claims on resources (tasks, paths, artifacts) with a time-to-live (TTL).
They move through a defined lifecycle:

| State | Description |
|-------|-------------|
| `requested` | A session has requested a lease but it has not yet been granted. |
| `granted` | The lease is active and the holder has exclusive or shared access per the reservation mode. |
| `renewed` | The lease holder has extended the TTL before expiry. |
| `released` | The holder voluntarily releases the lease. |
| `expired` | The TTL elapsed without renewal. The lease is stale but NOT deleted. |
| `stale` | The lease has been explicitly marked stale by a coordinator or takeover event. |
| `superseded` | A newer lease for the same resource has been granted to a different holder. |
| `refused` | The lease request was denied (write overlap, quota, or policy). |

**Critical rules:**

1. **Expired does not mean deleted.** Expired leases remain in the coordination store as evidence. Analysis of expired leases reveals hung sessions, slow providers, and timeout policy gaps.

2. **Stale does not mean safe to overwrite.** A stale lease on a path does not imply the path is clean. The session that held the lease may have mutated files. Any new session targeting a stale-leased path MUST capture a fresh dirty file snapshot before proceeding.

3. **Takeover requires a new dirty snapshot and a takeover event.** If Session B wants to take over a stale lease from Session A, it MUST:
   - Capture a new `DirtyFileSnapshot` of the affected paths.
   - Emit a `coord.lease.marked_stale` event referencing the prior lease.
   - Emit a `coord.path.reserved` event with the new reservation.
   - Report any detected file changes since the original lease was granted.

## CoordinationStore Interface

The coordination store exposes a typed interface for runtime orchestration.
The initial implementation is local and file-backed under `.build/rig-relay/coordination/`.
The interface is designed to be compatible with a future watchable backend (e.g., NATS JetStream KV).

```
CoordinationStore:
  - append_event(event) -> event_id
  - register_session(session_id, metadata) -> None
  - heartbeat(session_id) -> None
  - claim_task(session_id, task_id, scope) -> claim_result
  - reserve_paths(session_id, paths, mode) -> reservation_result
  - release_paths(session_id, paths) -> None
  - publish_artifact(session_id, artifact_kind, artifact_sha256, metadata) -> artifact_id
  - report_conflict(session_id, conflict_kind, details) -> conflict_id
  - request_handoff(session_id, target_session_id, scope) -> handoff_result
  - read_projection(session_id) -> compact_projection
  - watch_projection(callback) -> subscription
```

**Method semantics:**

- `append_event`: Append a typed coordination event. Returns the event ID for receipt chaining.
- `register_session`: Register a new session in the coordination plane with metadata (agent profile, provider, model, thinking config).
- `heartbeat`: Update the session's liveness timestamp. Sessions without a heartbeat within TTL are considered expired.
- `claim_task`: Attempt to claim a task. Returns granted/refused with reason.
- `reserve_paths`: Reserve paths for read or write. Write reservations are exclusive. Read reservations may overlap. Returns per-path grant/refusal.
- `release_paths`: Release previously reserved paths.
- `publish_artifact`: Register a typed artifact produced by a session so other sessions can discover and reuse it instead of duplicating work.
- `report_conflict`: Record a coordination conflict with structured details (path overlap, stale lease, dirty file collision).
- `request_handoff`: Request transfer of responsibility for a scope to another session.
- `read_projection`: Return a compact state projection of the coordination plane — active sessions, current reservations, published artifacts, recent conflicts. This is what parent sessions consume instead of raw transcripts.
- `watch_projection`: Subscribe to projection updates. Returns a subscription handle. Enables real-time "air traffic control" when multiple sessions are active.

### Future Backend: Watchable Store

The `CoordinationStore` interface is designed to be backend-agnostic.
The initial file-backed implementation writes JSONL event logs and atomic state files.

A future watchable backend (e.g., NATS JetStream KV) would:
- Support `watch_projection()` natively via key-value watch subscriptions.
- Retain key history per resource (leases, reservations, artifacts).
- Enable real-time coordination across multiple Rig Relay CLI processes.
- Scale to fleet orchestration without polling.

The file-backed store remains the default local-first implementation.
Watchable backends are opt-in and require explicit configuration.

## Dataset Impact

**Coordination events are not just runtime state. They are the structured event source for delegate/fleet evaluation datasets.**

Every `coord.*` event emitted to `observability.jsonl` becomes a row in the derived evaluation datasets defined in the [Usage Data Doctrine](usage-data-doctrine.md). This means:

1. **Cross-session coordination is measurable.** You can answer questions like:
   - Which task types produce the most path reservation refusals?
   - Which agent profiles cause stale leases (hung sessions)?
   - Which paths are most contended across concurrent sessions?
   - Does artifact reuse reduce duplicate search work?
   - How often do handoffs succeed vs. get rejected?

2. **The coordination layer becomes the eval corpus for fleet orchestration.**
   Rather than designing fleet scheduling heuristics in the dark, Rig Relay can derive scheduling policies from coordination event data.

3. **OpenTelemetry trace model alignment.**
   Coordination events follow the span model: each event is a span with a trace ID (session_id), parent span (parent_session_id), and links to related spans (task_id, conflict targets). This aligns with OpenTelemetry's guidance on fan-out operations and correlating related activities across traces. Fleet/delegate orchestration maps directly: one parent mission fans out into several child sessions, then an aggregator links the results back together.

4. **Compact projections are the dataset join key.**
   When a parent session reads a compact projection, the `coord.projection.read` event captures what it saw — active sessions, reservations, artifacts, conflicts. This projection becomes the ground-truth reference for evaluating whether the parent made correct delegation decisions.

### Derived Datasets

The coordination event stream feeds these derived datasets (defined in [Usage Data Doctrine](usage-data-doctrine.md)):

| Dataset | Source Events |
|---------|---------------|
| `cross_session_coordination_dataset.jsonl` | All `coord.*` events |
| `coordination_conflict_dataset.jsonl` | `coord.conflict.reported`, `coord.path.reservation_refused`, `coord.lease.expired`, `coord.lease.marked_stale` |
| `artifact_reuse_dataset.jsonl` | `coord.artifact.published`, `coord.projection.read` |
| `fleet_decomposition_dataset.jsonl` | `coord.task.claimed`, `coord.task.released`, `coord.handoff.*` |

An exporter (`scripts/rig_relay_export_coordination_datasets.py`) reads the coordination event stream and writes these datasets as schema-validated JSONL. See the [Usage Data Doctrine](usage-data-doctrine.md) for usage and mapping details.

## Local-First Design

The coordination plane is local-first by default. It operates within a single Rig Relay home directory and does not require a network connection, a running daemon, or an external service.

**Current:** File-backed store under `.build/rig-relay/coordination/`.
**Future:** Optional watchable backend (NATS JetStream KV or similar) for multi-process fleet orchestration.
**Never:** Remote-first coordination that requires cloud connectivity for local sessions.

This preserves the usage data doctrine's privacy boundary: no coordination data leaves the machine without explicit opt-in.

## Governed Checkpoint Commits

Agents may create local checkpoint commits at session end for their own session-owned files.
This provides clean local save points while keeping publication as a separate milestone-gated authority.

### Policy

- Agents may create local checkpoint commits for session-owned, mission-scoped files.
- Agents must push checkpointed commits for mission-owned files exactly once after the internal prepublication review loop has admitted the candidate boundary and a named milestone grants publication authorization. Agents may NOT push ad hoc, and they may not amend, rebase, merge, reset, clean, stash, restore, or commit unrelated files.
- Direct `git commit` and `git add` via bash are blocked — use the `checkpoint` tool instead.
- Publication is a separate authority from checkpointing. The milestone-authorized publisher may be a human or an agent acting on the named review slice; the published commit must remain within the mission-owned checkpointed boundary.

### Checkpoint Flow

1. At session start: capture branch, HEAD, dirty files, protected files, path reservations.
2. During session: record files touched through write_file/search_replace/coordination events.
3. At session end: compute `candidate_commit_files = files_touched ∩ mission_scope ∩ path_reservations_owned`.
4. Refuse commit if: overlapping write leases, untracked dirty files, unresolved conflicts, paths outside scope.
5. Stage only candidate files.
6. Commit with generated message: `checkpoint(<task_id>): <mission summary>`
7. Emit checkpoint artifact with session_id, task_id, files_committed, commit_sha, pre/post HEAD, validation hashes.
8. Never push in the checkpoint flow. Publication happens only through the milestone-authorized publication flow.

### Refusal Conditions

The `checkpoint` tool refuses when:
- `include_paths` is empty and `allow_partial` is false.
- Unresolved conflicts exist in the working tree.
- Unrelated staged files exist (staged by another session).
- Any include_path does not exist or is outside the repo root.
- Any include_path overlaps another active write reservation.
- Any include_path contains pre-existing dirty changes not safely patched by this session.

### Commit Message Format

```
checkpoint(<task_id>): <mission summary>

Session: <session_id>
Task: <task_id>
Agent profile: <profile>
Parent session: <parent_session_id or none>
Files:
- <path>
Validation:
- <command>
```

### Checkpoint Event Emission

The checkpoint tool now emits `rig.relay.checkpoint.committed` and `rig.relay.checkpoint.refused` events via `log_local_event` into the session's `observability.jsonl` stream. These events use the normalized payload contracts defined in `docs/schemas/rig.relay.checkpoint_eval.v1.schema.json`.

Payloads are hash-heavy and content-light:
- **Committed**: `session_id`, `task_id`, `branch`, `pre_commit_head`, `post_commit_head`, `commit_sha`, `files_committed_count`, `validation_summary_hash`, `checkpoint_artifact_sha256`, `status` (`"committed"`).
- **Refused**: `session_id`, `task_id`, `refusal_code`, `status` (`"refused"`), `warnings`.

No raw file contents, validation logs, or diff bodies are included.

### Checkpoint Artifact

```json
{
  "schema_version": "rig.relay.checkpoint.artifact.v1",
  "artifact_kind": "checkpoint_commit",
  "session_id": "...",
  "task_id": "...",
  "branch": "...",
  "pre_commit_head": "...",
  "post_commit_head": "...",
  "commit_sha": "...",
  "files_committed": [...],
  "validation_summary_hash": "sha256:...",
  "status": "committed",
  "warnings": [],
  "created_at": "..."
}
```

### Dataset Reports

Coordination events can be inspected via the dataset report generator
(`scripts/rig_relay_dataset_report.py`). The report includes a dedicated
Coordination section showing:

- Event counts by coordination event name
- Breakdown: task claims, path reservations, reservation refusals, conflicts, heartbeats

Reports are generated locally and are content-light, never including raw payload
contents from coordination events.

```bash
uv run python scripts/rig_relay_dataset_report.py
```

See the [Usage Data Doctrine](usage-data-doctrine.md#dataset-reports) for the
full report specification and privacy safeguards.


## Review Packet Protocol

Rig Relay provides a local review packet protocol for human/model review of completed missions.
Review packets bridge the gap between a completed mission (with its final report, artifacts, datasets,
and coordination state) and the next mission prompt (refined by a human or model reviewer).

Review packets are the continuation mechanism for coordination sessions:
- A session's coordination state (active claims, reservations, artifacts, conflicts) can be summarized
  and included in the review packet as an optional manifest.
- The reviewer's response becomes the seed for the next mission prompt, which may continue the same
  session or start a new child session.
- Review packets do not embed raw transcripts or raw coordination state — they reference the
  coordination summary by path, keeping the packet content-light.

See the [Review Packet Protocol section in the Usage Data Doctrine](usage-data-doctrine.md#review-packet-protocol)
for the full specification, including:
- Packet layout (5 files per packet)
- 6 review kinds (next_slice, risk_review, prompt_generation, commit_review, dataset_review, architecture_review)
- Schema fields and validation
- Content-light safeguards
- Reviewer response format and flow

Review packets are created with:

```bash
uv run python scripts/rig_relay_create_review_packet.py \
    --session-id session_20250101_000000 \
    --final-report .build/rig-relay/reviews/latest/final_report.md \
    --review-kind next_slice \
    --coordination-summary .build/rig-relay/coordination/projection.json
```

The review packet protocol is ChatGPT-Mac-app-independent and works with any text editor or model
that can write a Markdown file.


## Reviewer Orchestrator Protocol

Rig Relay defines a reviewer orchestrator protocol for multi-mission sprint execution.
The reviewer reads a [sprint cockpit](reviewer-orchestrator.md) packet, launches up to 4 bounded
child sessions through specialized tools, monitors coordination state, aggregates child reports,
and decides the next sprint action.

See the [Reviewer Orchestrator Doctrine](reviewer-orchestrator.md) for the full protocol specification,
packet schemas, security boundaries, and bootstrap implementation status.
The dry-run spawn planner (`scripts/rig_relay_spawn_session.py`) validates mission packets against
coordination constraints before any child session is launched.
The live current-state pulse (`scripts/rig_relay_current_state.py`) provides the reviewer with
a compact, content-light snapshot of active children, reservations, conflicts, stale leases,
and deterministic recommendations — enabling the reviewer to decide when to launch, wait,
inspect, or mark sessions stale without reading raw coordination state.
The pending work queue (see [Delegate/Fleet Orchestration Doctrine](delegate-fleet-orchestration.md))
provides the durable backlog that completes the autonomous loop: the reviewer pulls ready work
from the queue, dispatches children, monitors state, aggregates results, and updates the queue.
packet schemas, security boundaries, and bootstrap implementation status.

## Governance Principle

**Agents can checkpoint, then publish only the checkpointed slice exactly once after the internal prepublication review loop has admitted the candidate boundary and milestone authorization is granted.**
