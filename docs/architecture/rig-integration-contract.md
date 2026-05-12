# Rig Integration Contract

This document defines the architectural and runtime boundaries between **Rig** (the governed control plane) and **Rig Relay** (the interactive agent harness). It establishes the shared contracts and marriage of assumptions required to ensure Rig Relay can eventually fold cleanly into the Rig ecosystem.

## 1. Authority Boundaries

- **Rig owns**: The **Workspace**. The workspace is the root of authority, owning repository roots, base-branch policies, validation gates, lane registries, and durable receipts.
- **Rig Relay owns**: The **Session**. A session is a single interactive run of an agent loop, managing model calls, tool executions, and local context.
- **Marriage**: Rig Relay sessions must eventually attach to a Rig `workspace_id` and, optionally, an `lane_id`. The agent loop is a worker within a workspace, not an independent authority.

## 2. Mutation & Policy

- **Rig Doctrine**: No silent mutation of main, no auto-apply without review, and explicit validation gates.
- **Relay Role**: Interactive patching and verification. Modes like `auto-approve` or `accept-edits` are local harness conveniences and must never override workspace-level policy.
- **Marriage**: Relay respects the mutation model of the attached workspace. "Agent profiles" do not grant authority; workspace policy does.

## 3. Worktree & Lane Model

- **Rig Model**: AgentLanes map to isolated Git worktrees. Each lane has one branch, one agent identity, one task identity, and explicit history.
- **Relay Model**: Runs in a working directory.
- **Marriage**: In embedded mode, Rig Relay accepts `repo_root`, `worktree_path`, `branch`, and `task_id` from Rig and restricts all operations to that lane.

## 4. Artifact & Storage Root

- **Canonical Root**: `.rig/relay/` within the project root.
- **Relay Artifacts**: Session logs, context accounting, and local observability events live in `.rig/relay/sessions/<session_id>/`.
- **Marriage**: Rig Relay avoids creating `.rig-relay` or `.vibe` directories for new project-local state. It uses `.rig/relay/` as its primary home for local truth.

## 5. Event Semantics: Telemetry vs. Authority

- **Rig Status**: Progress streams are telemetry (informative). Receipts and projections are authority (durable truth).
- **Relay Status**: Observability events are diagnostic.
- **Marriage**: Rig Relay events (JSONL) are non-authoritative unless promoted to Rig receipts. Event names use `rig.relay.*` (e.g., `rig.relay.context.request_accounted`) to avoid namespace collisions and clarify intent.

## 6. Tool Authority & Risk Classes

- **Rig Safety**: Tools must advertise risk and scope.
- **Relay Execution**: Tools are the primary mutation vector.
- **Marriage**: Rig Relay tools categorize themselves into risk classes that Rig can govern:
    - `read_only`: No side effects (e.g., `read_file`, `ls`).
    - `workspace_write`: Local filesystem mutation in the active lane.
    - `git_read`: Inspection of git state (e.g., `git log`, `git diff`).
    - `git_mutation`: Side effects on git (e.g., `commit`, `branch`).
    - `network`: External requests.
    - `credential`: Access to secrets.

## 7. Context & Accounting

- **Rig Role**: Aggregates and analyzes context usage across the workspace.
- **Relay Role**: Instruments every request with granular character counts, fingerprints, and bloat analysis.
- **Marriage**: Relay produces `request_accounted` events; Rig can analyze them later.

## 8. Embedded Invocation Schema (Proposed)

When Rig invokes Rig Relay, it provides a structured context:

```json
{
  "schema_version": "rig.relay.invocation.v1",
  "workspace_id": "ws_...",
  "lane_id": "lane_...",
  "operation_id": "op_...",
  "repo_root": "/path/to/repo",
  "worktree_path": "/path/to/worktree",
  "branch": "agent/task/name",
  "task": "Fix deterministic git tools",
  "mode": "inspect|patch|verify",
  "artifact_root": ".rig/relay/sessions/<session_id>",
  "tool_policy": {
    "allowed_classes": ["read_only", "git_read", "workspace_write"],
    "forbidden_classes": ["destructive_git", "external_side_effect"]
  }
}
```

## 9. Result Schema (Proposed)

Relay returns its execution summary:

```json
{
  "schema_version": "rig.relay.result.v1",
  "session_id": "relay_...",
  "operation_id": "op_...",
  "status": "completed|blocked|failed|cancelled",
  "events_jsonl": ".rig/relay/sessions/.../events.jsonl",
  "observability_jsonl": ".rig/relay/sessions/.../observability.jsonl",
  "receipt_candidates": [],
  "files_touched": [],
  "next_actions": []
}
```
