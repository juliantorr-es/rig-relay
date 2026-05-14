# Worktree Manager — Governance & Safety

## Purpose

The `WorktreeManager` (`rig_relay.coordination.worktree_manager.py`) provides
relay-native git worktree lifecycle for agent/lane execution isolation.
Worktrees are checked out under a configurable `worktree_root` (default:
`<repo>/.rig/relay/worktrees/`) and are isolated from the main working tree.

## API

```python
mgr = WorktreeManager(
    repo_root=Path("/path/to/repo"),
    worktree_root=Path("/path/to/repo/.rig/relay/worktrees"),
)

# Create a linked worktree with a new branch
result = mgr.create(workspace_id="lane-42", branch_name="feat/lane-42")

# Remove a clean worktree (refuses dirty without force=True)
result = mgr.remove("lane-42")

# Force-remove a dirty worktree (use with caution)
result = mgr.remove("lane-42", force=True)

# Get HEAD SHA
sha = mgr.get_head_hash("lane-42")

# List all managed worktrees
records = mgr.list_worktrees()

# Inspect a single worktree (includes dirty detection)
record = mgr.inspect("lane-42")
```

## Safety & Path Policy

- All worktree paths must be children of `worktree_root`. Path traversal
  (`../`, `~`, absolute paths) via `workspace_id` is rejected.
- `workspace_id` is sanitized: no `/`, `\`, empty, too long, or path-traversal
  segments.
- `branch_name` is sanitized: no spaces, unsafe git ref characters, empty,
  too long, `.lock` suffix, `..`, or `@{` syntax.
- No `shell=True`. All git commands use argv subprocess calls via
  `_run_git()` with `cwd=repo_root`.

## Git Commands Used

| Operation | Command | Safety |
|-----------|---------|--------|
| create | `git worktree add -b <branch> <path> [<ref>]` | argv only |
| remove | `git worktree remove <path>` (refuses dirty) | argv only |
| remove (force) | `git worktree remove --force <path>` | argv only |
| list | `git worktree list --porcelain` | argv only, parsed |
| get_head | `git -C <path> rev-parse HEAD` | argv only |
| inspect | `git -C <path> status --porcelain` | argv only, no side effects |
| git check | `git rev-parse --git-dir` | argv only |

## Dirty Worktree Removal Behavior

- `remove(workspace_id)` without `force=True` checks for uncommitted changes
  via `git status --porcelain`. If output is non-empty, removal is refused
  with `error_kind="dirty_worktree"`.
- `remove(workspace_id, force=True)` passes `--force` to `git worktree remove`,
  allowing removal of dirty worktrees. Use with caution — uncommitted changes
  are discarded.
- Force removal is available but not the default. The calling layer
  (`ExecutionLease`, `RuntimeSupervisor`) should decide when force is
  appropriate (e.g., lease expiry).

## Coordination Integration Status

- **Current:** Minimal (A). WorktreeManager only manages git worktrees.
  No CoordinationStore integration for path reservation or lease lifecycle.
- **Planned (P2 follow-up):** Reserve worktree path via CoordinationStore
  before create; release on remove/failure.

## DirtyFileGuard Boundary

- `DirtyFileGuard` protects paths in the **main working tree** from accidental
  overwrite. It is NOT bypassed by WorktreeManager — WorktreeManager operates
  under `worktree_root`, not the main tree.
- WorktreeManager must not write arbitrary files in the main repo. Its
  filesystem footprint is limited to git worktree metadata (managed by
  `git worktree`) and the checked-out worktree files under `worktree_root`.
- Future `ExecutionLease` will bind tool execution to a worktree path,
  ensuring mutation tools operate in the isolated worktree rather than the
  main tree.

## Content-Light Policy

- `WorktreeRecord` contains no raw git output, no diffs, and no file contents.
- `WorktreeOperationResult` uses structured `error_kind` and `refusal_reason`
  fields — no raw stdout/stderr.
- `_GitCommandResult` (internal) hashes raw output but does not persist it.
- Schema (`docs/schemas/rig.relay.worktree.v1.schema.json`) enforces
  `additionalProperties: false` on all object types.

## Known Limitations

- No coordination lease integration (P2 follow-up).
- No execution integration — worktrees are created but not bound to
  `ExecutionLease` or `RuntimeSupervisor` yet.
- No automatic stale worktree cleanup — `list_worktrees()` reports missing
  worktrees but does not remove them.
- No `git worktree prune` or `git worktree repair` operations.
- WorktreeManager does not validate that `worktree_root` is outside the main
  working tree — this is the caller's responsibility.
