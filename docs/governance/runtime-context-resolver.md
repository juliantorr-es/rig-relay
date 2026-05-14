# Runtime Context Resolver

`RuntimeContextResolver` is the relay-native control-plane helper for deriving canonical runtime coordination context from an intent.

## Purpose

Agents should emit intents. They should not have to manually manage fragile coordination identifiers such as `session_id`, `task_id`, `lane_id`, or `lease_id`.

The resolver derives a read-mostly `RuntimeContext` that can be passed into tool and runtime control logic.

## What It Resolves

- `session_id`
- `task_id`
- `lane_id`
- `workspace_id`
- `worktree_path`
- `repo_root`
- `coordination_scope`
- `receipt_index_path`
- `dirty_policy`

## What It Does Automatically

- Infers `session_id` from current session metadata when available.
- Derives a deterministic `task_id` from the session plus intent shape when explicit `task_id` is missing and task creation is allowed.
- Infers `lane_id` from workspace/worktree context when available.
- Refuses unsafe paths outside the resolved repo/worktree scope.

## What It Does Not Do

- It does not acquire path reservations.
- It does not run subprocesses.
- It does not weaken the dirty guard.
- It does not force-remove worktrees.
- It does not perform mutation by itself.

## Error Behavior

- `session_required` when no session can be inferred.
- `task_required` when task creation is disallowed and no task_id is provided.
- `worktree_required` when a worktree is required but unavailable.
- `unsafe_path` when a requested path escapes the resolved scope.

## Future Integration

Later runtime and mutation surfaces can consume the resolved context instead of making every agent thread carry bookkeeping IDs directly. That keeps lease and session handling in the control plane, where it belongs.

