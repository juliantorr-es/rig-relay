# Delegate/Fleet Orchestration Doctrine

Rig Relay's delegate/fleet orchestration model governs how a reviewer/orchestrator agent
selects ready work from a durable pending work queue, dispatches bounded child missions,
monitors progress through the current-state pulse, aggregates evidence from completed
children, and decides the next action.

This doctrine builds on the [Reviewer Orchestrator Doctrine](reviewer-orchestrator.md)
and adds the **pending work queue** as the durable backlog that completes the autonomous
loop:

```
cockpit → queue_plan → spawn_plan → spawn_execute → current_state → child_result → parent_convergence_report → queue update
```

Without a durable queue, the reviewer "thinks of tasks out of nowhere." With it, the
reviewer pulls ready work from a persistent backlog, dispatches only what is safe under
coordination constraints, and leaves sequential work pending until the dependency graph
allows it to move.

## Desktop Intent API

The desktop Intent API (`rig_relay/desktop/intents.py`) provides governed,
schema-validated access to safe orchestration actions from the desktop cockpit.
Protected mutation intents (including `spawn.execute`, `fleet.execute`, and
`delegate.execute`) are explicitly refused with `authorization_required=true`
until receipt-gated intent execution exists in a future slice.

See `docs/governance/desktop-cockpit-ui.md` for the full intent catalog.

## Canonical Concepts

### Delegate

A **delegate** is one bounded child session launched from one ready work item. The child
receives a typed mission packet that defines allowed paths, tool policy, coordination
policy, checkpoint policy, and completion criteria. The child operates within these bounds
and returns a child session result.

A delegate is the atomic unit of orchestration work.

### Fleet

A **fleet** is a bounded set of child sessions launched from multiple ready work items
in parallel. Fleets respect:

- `max_parallel_sessions` (default 4)
- Dependency ordering (sequential items dispatch only after upstream items complete)
- Path-lease coordination (no overlapping write reservations)
- Profile/policy validation per item
- Validation-stage ordering (test after implement, review after test)

Fleets are the scalable unit of orchestration work.

### Reviewer / Orchestrator

The **reviewer/orchestrator** is the responsible parent agent. It:

1. Reads the sprint cockpit to understand the repo state, coordination state, and dataset
   completeness.
2. Computes a ready work plan from the durable pending work queue.
3. Dispatches each ready work item through spawn planning and (eventually) spawn execution.
4. Monitors child sessions through the current-state pulse.
5. Aggregates child session results into a parent convergence report.
6. Updates the work queue (mark completed, advance dependencies, add new items).
7. Decides next action: continue dispatching, request human review, or propose push.

When two or more read-side or application-service boundaries are published and frozen, the next authorized work SHOULD preferentially be a named integration milestone that exposes those boundaries through the desktop Gridline Interface or an approved static publication surface. The reviewer MUST NOT continue opening isolated substrate expansion missions solely because adjacent backend opportunities remain available when the product can already consume released boundaries.

The reviewer **does not edit files directly**. It **does not run arbitrary shell commands**.
It orchestrates through typed artifacts only.

### Agents as Tools

The **agents-as-tools** pattern is the default orchestration style. Child agents are invoked
as bounded, typed workers — like calling a function — and return structured results to the
reviewer. The reviewer remains the responsible caller throughout.

Characteristics:
- The reviewer selects the work item, crafts the mission packet, and dispatches.
- The child executes within bounds and returns a result.
- The reviewer inspects the result and decides the next action.
- No implicit transfer of authority.

This follows the OpenAI orchestration distinction: agents-as-tools keep the main agent
responsible; handoffs transfer control. Rig Relay defaults to agents-as-tools.

### Handoff

A **handoff** is an explicit transfer of responsibility from one session to another.
Handoffs are **not the default**. They require:

1. A typed handoff event (request, accept, or reject).
2. A new mission/ownership boundary.
3. The original session releasing its claim.

Handoffs are used only when explicitly desired — e.g., a researcher discovers a bug that
requires a separate implementer mission, and explicitly passes the context.

### Supervisor Graph Semantics

The orchestration model follows a **supervisor graph** pattern, matching the industry
LangGraph supervisor architecture:

- The reviewer/orchestrator is the supervisor node.
- Each child session is a worker node.
- Edges represent dispatch, dependency, and result flow.
- The graph is acyclic during a single orchestration iteration.
- Sequential items form a chain; parallel items fan out and fan in.

### Stateful Orchestration

The orchestration is **stateful** across sessions:

- The pending work queue persists across child session boundaries.
- Coordination state (sessions, leases, artifacts, conflicts) persists in the
  coordination store.
- The parent convergence report captures the aggregate state.
- If the reviewer crashes or is interrupted, it can reload the queue and
  coordination state and resume.

### Replay/Debug Mindset

Every orchestration artifact is typed, versioned, and content-light:

- Coordination events carry schema versions, event hashes, and salted path hashes.
- Spawn plans capture the decision with refusal codes.
- Current state pulses capture the live projection.
- Parent convergence reports capture the aggregate evidence.

This enables replay debugging: given the same queue and coordination state, a reviewer
should produce the same decisions.

### Workspaces

A **workspace** is a Git worktree or isolated checkout for concurrent mutation:

- Single-checkout concurrency defaults to one writer plus multiple readers/testers.
- Multi-writer concurrency requires non-overlapping paths in the same checkout, or
  separate Git worktrees.
- Worktree creation is deferred to a future slice.

### Spec-Scoped Tasks

Every work item is scoped to a specification:

- `allowed_paths` and `forbidden_paths` constrain file access.
- `tool_policy` constrains write and bash access.
- `coordination_policy` constrains coordination access.
- `validation_commands` define the pass/fail criteria.
- `done_when` defines human-readable completion criteria.

A work item cannot exceed its spec scope.

### Human Oversight

Human oversight is the authority boundary:

- Checkpointed commits may be published for upstream consumption only after a named milestone and explicit publication authorization.
- Agents create checkpoints for session-owned files; the user or a milestone-authorized publication step decides when to publish the checkpointed slice.
- If the parent convergence report recommends human review, the reviewer pauses and
  presents the evidence.
- The reviewer never bypasses Git policy or dirty-file guard.

### Release Boundary Declaration

Every child result and parent convergence report MUST clearly distinguish:

1. The released boundary.
2. The stated consumer purpose.
3. Deferred seams.
4. Blocking defects that make the released boundary unsafe or false.
5. Freeze status.

The report MUST NOT describe a deferred seam as a blocker unless the seam invalidates the released boundary. The report MUST NOT declare a lane released while its tracked audit or canonical status artifact still says `candidate_local` or `blocked_release`.

### Validation Stages

Work items pass through validation stages:

1. **Schema validation**: The mission packet and spawn plan validate against their schemas.
2. **Coordination validation**: Active child count, path leases, and conflicts are checked.
3. **Queue validation**: Dependencies, item status, and parallelism policy are checked.
4. **Execution validation**: Child runs validation commands on completion.
5. **Convergence validation**: Parent aggregates child results and decides next action.

### Boundary-Scoped Review Rule

When reviewing a lane completion claim, reject the claim only for defects that falsify the explicitly released boundary, its stated consumer purpose, its canonical evidence contract, or its publication truth.
Do not demand new upstream contracts, downstream integrations, stronger capability classes, UI wiring, transport replacement, or new query/report features unless the lane explicitly claims them or their absence makes the released boundary unsafe.
When a worthwhile issue is outside the claimed boundary, record it as a deferred integration requirement and allow the lane to close if its narrow release is truthful.

### Pending Work Queue

The **pending work queue** is the durable backlog of work items. It is the canonical
missing object that completes the orchestration loop.

A work item has a status that progresses through:

```
pending → ready → claimed → dispatched → running → completed
                                                         ↓
                                              failed / refused / cancelled / superseded
```

Blocked/waiting states interrupt progression:

- `waiting_dependency`: One or more dependencies are not yet complete.
- `waiting_lease`: Required path leases are held by another session.
- `waiting_validation_stage`: A validation stage has not been reached.
- `blocked_by_conflict`: A coordination conflict blocks the item.
- `blocked_by_human_review`: Human attention is required before proceeding.
- `blocked_by_failed_parent`: A parent/upstream item failed.

A work item becomes **ready** when:

1. Its status is `pending` or `ready`.
2. All dependencies are completed.
3. Active child count is below `max_parallel_sessions`.
4. Requested write paths do not overlap active write reservations.
5. Profile/tool policy is valid.
6. Validation/checkpoint policy is acceptable.
7. Storage budget is not `fleet_blocked` (checked via `compute_storage_summary()`). See
   [Storage Retention Policy § Fleet Preflight Enforcement](storage-retention-policy.md#fleet-preflight-enforcement).

## Canonical Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    Pending Work Queue                        │
│  Items: pending, ready, blocked, waiting, running, completed│
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Ready Work Plan (queue_plan)                    │
│  Ready items → dispatch candidates                          │
│  Blocked/waiting items → reasons visible                     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Spawn Plan (spawn_session --dry-run)            │
│  Validates mission packet + coordination constraints         │
│  Returns can_spawn or refusal_code                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Spawn Execute (spawn_session --execute)         │
│  Launches bounded child session                              │
│  Sets work item status = dispatched/running                  │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Current State Pulse (current_state)             │
│  Monitors heartbeat, risk, conflicts, stale leases           │
│  Reviewer decides: wait, inspect, or proceed                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Child Session Result (mission result)           │
│  status: completed / failed / cancelled / timed_out / refused│
│  validation_summary, files_changed, findings                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Parent Convergence Report                       │
│  Fan-in of all child results                                  │
│  overall_status, recommendations, new_findings, blockers      │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              Queue Update                                    │
│  Mark completed items done                                   │
│  Advance dependency graph                                    │
│  Add new work items if discovered                            │
│  Loop back to queue_plan                                     │
└─────────────────────────────────────────────────────────────┘
```

## Work Item Statuses

| Status | Description |
|--------|-------------|
| `pending` | Created but not yet evaluated for readiness |
| `ready` | All conditions met, ready for dispatch |
| `claimed` | Claimed by dispatcher, not yet handed to child |
| `dispatched` | Child session launched, running |
| `running` | Child confirmed running via heartbeat |
| `blocked` | Generic blocked state |
| `waiting_dependency` | Waiting for dependencies to complete |
| `waiting_lease` | Waiting for path leases to become available |
| `waiting_validation_stage` | Waiting for a validation stage to be reached |
| `completed` | Child completed successfully |
| `failed` | Child failed validation or runtime error |
| `refused` | Spawn planner refused the mission |
| `cancelled` | Explicitly cancelled by reviewer |
| `superseded` | Replaced by a newer work item |

## Execution Modes

| Mode | Description |
|------|-------------|
| `delegate` | Single bounded child session |
| `fleet` | Multiple parallel child sessions |
| `sequential` | Sequential dispatch within a dependency chain |
| `validation` | Read-only validation pass after mutation |
| `documentation` | Documentation/reporting pass |
| `review` | Code review pass |

## Parallelism Policies

| Policy | Description |
|--------|-------------|
| `sequential` | Only one item at a time in this group |
| `parallel_if_safe` | Parallel if no write conflicts |
| `read_only_parallel` | Always parallel for read-only profiles |
| `single_writer_parallel_readers` | One writer + multiple readers |
| `worktree_required_multi_writer` | Requires Git worktree for multi-writer |

## Ready Work Plan

The ready work plan is computed from the pending work queue. It separates items into:

- **ready_items**: Items that can be dispatched now (all conditions met).
- **blocked_items**: Items that are blocked with a reason.
- **waiting_items**: Items waiting for dependencies or leases.

Each ready item includes enough information to construct a mission packet and run the
spawn planner: agent profile, allowed/forbidden paths, tool/coordination/checkpoint
policy, validation commands, and done_when criteria.

The plan also includes:
- Active child count and available slots.
- Deterministic recommendations (dispatch, wait, inspect, etc.).
- Warnings about coordination state.

## Parent Convergence Report

The parent convergence report is the reviewer's fan-in artifact. It summarizes:

- All child sessions completed, failed, or still running.
- Completed work items with their validation results.
- Blocked work items with reasons.
- Artifacts and checkpoints produced by children.
- Out-of-scope findings recorded by children.
- Recommended next action for the reviewer.

The report is content-light: it references artifacts by hash, not by embedding raw content.
It enables the reviewer to decide: dispatch more work, request human review, propose push,
or cancel failed items.

## Orchestration Loop Summary

```
preflight (storage check) → queue_plan → spawn_plan → spawn_execute → current_state → parent_convergence_report → queue update
```

The reviewer repeats this loop until the queue is empty, the sprint is blocked, or human
review is requested.

### Storage Preflight

Before each loop iteration, the orchestrator reads `current_state.storage_status` to verify:

- `budget_status` is not `fleet_blocked` — if blocked, the loop pauses and recommends GC.
- `stale_lease_count` is below warning threshold — high counts indicate coordination drift.

The preflight step uses `compute_storage_summary()` from `rig_relay.evidence.storage_lifecycle`,
which is called by both `generate_current_state()` and `build_projection()`.

See [Storage Retention Policy § Fleet Preflight Enforcement](storage-retention-policy.md#fleet-preflight-enforcement)
for the full rule set.

## References
- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](rig-to-relay-pattern-inventory.md)

- [Reviewer Orchestrator Doctrine](reviewer-orchestrator.md)
- [Cross-Session Coordination Doctrine](cross-session-coordination.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Review Packet Protocol](usage-data-doctrine.md#review-packet-protocol)
- [Work Item Schema](../schemas/rig.relay.work_item.v1.schema.json)
- [Work Queue Schema](../schemas/rig.relay.work_queue.v1.schema.json)
- [Ready Work Plan Schema](../schemas/rig.relay.ready_work_plan.v1.schema.json)
- [Parent Convergence Report Schema](../schemas/rig.relay.parent_convergence_report.v1.schema.json)
