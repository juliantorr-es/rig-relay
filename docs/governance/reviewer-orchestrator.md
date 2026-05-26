# Reviewer Orchestrator Doctrine

Rig Relay's reviewer orchestrator protocol defines how a manager agent reads a full
sprint cockpit, launches bounded child missions through a specialized tool, monitors
coordination state, aggregates child reports, and decides the next sprint action.

This doctrine governs the **reviewer-as-orchestrator** pattern — the most restrictively
safe path to autonomous multi-mission execution.

## Core Principles

### Reviewer is Orchestrator, Not Direct Editor

- The reviewer reads the sprint cockpit and mission brief.
- The reviewer **does not edit files directly**.
- The reviewer **does not run arbitrary shell commands**.
- The reviewer may only launch bounded child missions through `rig_relay_spawn_session`
  or equivalent high-level tools.

### Bounded Autonomy

Child sessions receive a typed mission packet that defines:

- Allowed and forbidden file paths
- Tool policy (write access, bash access, bash allowlist)
- Coordination policy (claim task, reserve paths, heartbeat)
- Checkpoint policy (off, prompt, auto)
- Completion criteria (`done_when`)
- Maximum runtime

**Child sessions cannot exceed their mission packet bounds.**

### Max Parallel Sessions

The default maximum is **4 concurrent child sessions**. This ceiling exists because:

- The current coordination layer is local/file-backed.
- More than 4 concurrent sessions creates coordination noise faster than throughput.
- The repo is in rapid motion and overlapping write scopes are dangerous.

### Default Concurrency Pattern

The safe default is **one writer + multiple readers/testers**:

| Profile | Write | Read | Purpose |
|---------|-------|------|---------|
| implementer | Yes | Yes | Scoped file mutation |
| tester | No | Yes | Validation only |
| reviewer/researcher | No | Yes | Read-only audit |
| documenter | Yes (docs only) | Yes | Docs/findings/report updates |

For read-only sprint analysis, all four can run in parallel.
For mutation work, only one writer per path is allowed.

### Multi-Writer Requires Non-Overlapping Paths or Worktrees

- Two writers may operate concurrently only if their `allowed_paths` sets do not overlap.
- For true multi-writer mode across the same paths, use `git worktree` — it is designed
  to let one repository have multiple working trees on different branches.

### Reviewer Must Inspect Coordination State Before Launch

Before launching any child mission, the reviewer MUST:

1. Read the current coordination projection (active sessions, path leases, conflicts).
2. Verify no write lease overlap exists with the intended mission.
3. Verify the sprint's `max_parallel_sessions` limit is not exceeded.
4. Verify storage budget is not `fleet_blocked` — check `current_state.storage_status.budget_status`
   or `projection.storage.budget_status`. See [Storage Retention Policy § Fleet Preflight
   Enforcement](storage-retention-policy.md#fleet-preflight-enforcement) for thresholds.

### Reviewer Must Aggregate Reports Before Follow-Up

Before launching a follow-up mission, the reviewer MUST:

1. Collect all complete child session results.
2. Check for failures, conflicts, or blocked paths.
3. Decide: clean → propose manual push / next sprint; blocked → launch one bounded fix mission.

### Boundary-Scoped Closure

A child mission closes when its explicitly declared boundary is published, production-proven for its stated consumer purpose, reconstructable from governing evidence, and free of defects inside that boundary. Deferred upstream, downstream, cross-lane, UI, transport, or broader capability gaps do not keep the child open unless they make the released boundary unsafe or false.

The reviewer MUST distinguish:

- `candidate_local` from `published_narrow_release`;
- `published_narrow_release` from `frozen_pending_integration`;
- blocked release defects from deferred integration seams.

A claim-adversary pass for a child mission is boundary-scoped. It attacks the released boundary and its stated consumer purpose only. The reviewer MUST NOT require unrelated seams, stronger future architecture, or broader integration as a condition of closing a truthful narrow release.

### Reviewer Never Bypasses Git Policy

- The reviewer never pushes, merges, rebases, resets, cleans, stashes, or bypasses checkpoint policy.
- The reviewer never runs `git commit` or `git add` directly.
- Checkpoints are created by child sessions through the existing `checkpoint` tool, governed
  by dirty-file guard, path leases, and checkpoint policy.

## Desktop Intent API

The desktop Intent API (see `rig_relay/desktop/intents.py`) provides a governed
entry point for safe orchestration actions from the desktop cockpit:

- **Dry-run only**: All intents are read-only or dry-run. Protected mutation
  intents are explicitly refused.
- **Schema-validated**: Every intent is validated against the request schema
  before dispatch.
- **Content-light results**: Counts, statuses, hashes, and refs only — never
  raw data.
- **Future receipt-gated**: Protected intents return `authorization_required=true`
  and will be wired through authorization receipts in a future slice.

Allowed intents: `refresh_projection`, `generate_refinement_report`,
`run_storage_audit`, `run_queue_plan_dry_run`, `run_spawn_plan_dry_run`,
`create_refinement_packets`, and others.

See `docs/governance/desktop-cockpit-ui.md` for the full intent catalog.

## Packet Types

The reviewer orchestrator protocol uses four packet types:

### 1. Sprint Cockpit (`rig.relay.sprint_cockpit.v1`)

Created at sprint start by `scripts/rig_relay_create_sprint_cockpit.py`.
Contains the full context the reviewer needs to plan missions:

- `sprint_id`, `branch`, `head`, `repo_state_sha256`
- `dirty_summary` (tracked, untracked, protected dirty counts)
- `coordination_summary` (active sessions, tasks, write leases, conflicts)
- `dataset_summary` (observability events, coordination events, tool calls, findings)
- `open_findings` (content-light: id, severity, title)
- `recent_checkpoints` (session_id, commit_sha, status)
- `active_sessions` and `active_path_reservations`
- `sprint_mission`, `constraints`, `available_reviewer_tools`

Stored as `.build/rig-relay/cockpit/current_sprint_cockpit.json` with companion
Markdown at `.build/rig-relay/cockpit/current_sprint_cockpit.md`.

Content-light: never includes raw file contents, prompts, model outputs, stdout/stderr,
or diffs.

### 2. Mission Packet (`rig.relay.mission_packet.v1`)

Created by the reviewer for each child session. Defines the mission bounds:

- `mission_id`, `parent_sprint_id`, `parent_review_id`
- `agent_profile` (implementer, tester, reviewer, documenter)
- `mission_title`, `instructions`
- `allowed_paths`, `forbidden_paths`
- `tool_policy` (allow_write, allow_bash, bash_allowlist)
- `coordination_policy` (claim_task, reserve_paths, heartbeat)
- `checkpoint_policy` (off, prompt, auto)
- `validation_commands`, `done_when`, `max_runtime_seconds`

Built-in refinement packet generators may create a narrower packet schema for derived implementation slices, but the reviewer still expects the same bounded-mission properties: explicit scope, clear validation, and content-light instructions.

### 3. Child Session Result (`rig.relay.child_session_result.v1`)

Produced by each completed child session. Returned to the reviewer for aggregation:

- `mission_id`, `session_id`, `status`
- `final_report_path`, `artifact_manifest_path`
- `checkpoint_commit_sha`, `files_changed`
- `validation_summary`, `findings_recorded`
- `warnings`, `recommended_next_action`, `runtime_seconds`

### 4. Sprint Aggregate Report (`rig.relay.sprint_aggregate_report.v1`)

Produced by the reviewer after collecting all child results. Decides next action:

- `sprint_id`, `parent_review_id`
- `child_results` (summaries with status, validation pass/fail)
- `overall_status` (clean, blocked, partial, failed)
- `recommended_next_action`, `new_findings`, `blockers`

## Security Boundaries

1. **No unrestricted shell for the reviewer.** Only high-level tools like
   `rig_relay_spawn_session`, `rig_relay_read_cockpit`, `rig_relay_read_coordination_state`,
   `rig_relay_read_dataset_report`, `rig_relay_cancel_session`, `rig_relay_request_checkpoint`,
   `rig_relay_aggregate_reports` are allowed.

2. **Child sessions cannot escape their mission packet.** The mission packet defines
   allowed paths, write access, bash access, and coordination access. Attempts to
   exceed bounds are refused by the tool layer.

3. **Checkpoints require a governed tool, not direct git.** The `checkpoint` tool enforces
   dirty-file guard, path leases, and checkpoint policy. The reviewer cannot create or
   bypass checkpoints.

4. **Coordination is the source of truth.** Before every launch and every follow-up,
   the reviewer reads the coordination projection. Stale or missing projections block
   further action.

## Reviewer Orchestrator Prompt

```markdown
You are the Rig Relay sprint orchestrator.
You do not edit files directly.
You do not run shell commands directly.
You may only launch bounded child missions through rig_relay_spawn_session.
You must keep at most 4 child sessions active.
You must prefer one writer plus read-only reviewers/testers.
You must inspect coordination state before launching new work.
You must avoid overlapping write scopes.
You must aggregate child final reports before deciding the next mission.
You must never push, merge, rebase, reset, clean, stash, or bypass checkpoint policy.
You must prioritize product-facing integration once safe narrow releases exist.
You must not keep reopening a lane merely because a stronger architecture is discoverable.
You must distinguish released, deferred, blocked, and frozen states.
```

## Bootstrap Implementation Status

The following components exist:

- [x] 4 JSON Schemas (sprint_cockpit, mission_packet, child_session_result, sprint_aggregate_report)
- [x] Cockpit generator script (`scripts/rig_relay_create_sprint_cockpit.py`)
- [x] Tests for cockpit generator and schema validation
- [x] Doctrine document (this file)
- [x] `rig_relay_spawn_session` dry-run planner (`scripts/rig_relay_spawn_session.py`)
- [x] `rig_relay_current_state` live orchestration pulse (`scripts/rig_relay_current_state.py`)
- [ ] `rig_relay_spawn_session` executor (real subprocess spawning — deferred)
- [ ] `rig_relay_read_cockpit` tool (read the cockpit packet — deferred)
- [ ] `rig_relay_aggregate_reports` tool (collect and summarize child results — deferred)
- [ ] Full autonomous reviewer loop (deferred — requires tool implementation above)

## References
- [Rig-to-Relay Porting Doctrine](rig-to-relay-porting-doctrine.md)
- [Rig-to-Relay Pattern Inventory](rig-to-relay-pattern-inventory.md)

- [Delegate/Fleet Orchestration Doctrine](delegate-fleet-orchestration.md)
- [Cross-Session Coordination Doctrine](cross-session-coordination.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Review Packet Protocol](usage-data-doctrine.md#review-packet-protocol)
- [Work Item Schema](../schemas/rig.relay.work_item.v1.schema.json)
- [Work Queue Schema](../schemas/rig.relay.work_queue.v1.schema.json)
- [Ready Work Plan Schema](../schemas/rig.relay.ready_work_plan.v1.schema.json)
- [Git Discipline Rules](../AGENTS.md#git)
- [Dirty-File Preservation](../AGENTS.md#dirty-file-preservation)
