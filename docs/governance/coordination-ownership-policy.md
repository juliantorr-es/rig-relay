# Coordination Ownership Policy

**Status: Adopted (Phase K, 2026-05).**

Defines how path reservations and task claims are owned, renewed, and
conflict-detected in Rig Relay's coordination store.

## Ownership Model

Every task claim and path reservation carries two identity fields:

- `session_id` — identifies the agent session (e.g. a rig-relay console
  session or a CI pipeline invocation).
- `task_id` — identifies the work item within that session (e.g. a single
  tool invocation or agent subtask).

The tuple `(session_id, task_id)` is the **ownership key**.

## Policy: Same-Owner Renewal

A task claim or path reservation whose `(session_id, task_id)` matches the
existing record **is allowed to renew**. Renewal refreshes the expiry/TTL
without creating duplicate lease files.

| Case | Existing Owner | Requesting Owner | Result |
|------|---------------|------------------|--------|
| A | — | — | Reserve succeeds |
| B | same session + same task | same session + same task | Reserve succeeds (renewal) |
| C | same session + different task | same session + different task | Blocked with `path_write_overlap` |
| D | different session | any | Blocked with `path_write_overlap` |
| E | stale/expired | any | Treated as no reservation |

### Case A — No existing reservation

`reserve_paths` and `claim_task` succeed normally.

### Case B — Same-owner renewal

`claim_task`: When the existing task claim has the same `session_id` and
`task_id`, the claim is refreshed (expiry extended, TTL updated). No conflict
is recorded. The existing behavior (blocking all re-claims) was the root cause
of coordination refusal during same-session multi-step workflows.

`reserve_paths`: The path lease file key incorporates `session_id`,
`task_id`, and the normalized path list. When the same owner calls
`reserve_paths` again, the same key is generated and the file is overwritten.
No duplicate lease files are created.

### Case C — Same session, different task

Blocked with a structured conflict. Within a single session, two different
tasks may race for the same path. The first to claim wins; the second is
refused. This prevents intra-session path contention.

### Case D — Cross-session

Blocked with a structured conflict. This is the original coordination guard
behavior and is preserved unchanged. Cross-session path overlap requires
explicit conflict resolution (serialize, split scope, or wait for stale).

### Case E — Stale / expired

Existing stale-lease handling applies. Expired claims and reservations are
treated as inactive during `read_state_projection` and during conflict checks.
A new claim or reservation is allowed to proceed as if no prior record exists.

## Implementation

The carve-out lives in `CoordinationStore.claim_task()` in
`rig_relay/coordination/store.py`. The change is narrow:

```python
if expires_dt > now:
    same_owner = (
        existing.session_id == session_id
        and existing.task_id == task_id
    )
    if not same_owner:
        # Create conflict, return allowed=False
        ...
    # same_owner falls through to claim creation below
```

`reserve_paths()` already handles same-owner correctly via the
`_iter_reservations()` prefix check (skips same `session_id` + `task_id`).
No changes were needed in `reserve_paths` for this slice.

## Relationship with Dirty Guard

The coordination ownership policy is **independent** of the dirty file guard:

- The dirty guard (`vibe/core/governance/guard.py`) checks file state
  (modified/staged/untracked) and enforces `expected_before_sha256`.
- The coordination ownership policy checks session/task identity and lease
  conflicts.
- Both must pass before a mutation tool can write. A same-owner coordination
  renewal does not bypass the dirty guard.
- A dirty guard refusal is independent of coordination state — the guard
  checks file content, not leases.

## Remaining Risks

1. **Same-session different-task is blocked for path reservations** but
   `claim_task` is per-task-id, so different tasks inherently target different
   claim keys. The path reservation check (Case C) is the relevant blocker.
2. **No background lease reaping**. Stale leases are only detected during
   `read_state_projection()` and conflict checks. A dedicated reaper is
   deferred.
3. ~~Lease file key mismatch~~ **Resolved**. The dead per-path hash lookup
   (`check 2`) in `reserve_paths` was removed. All conflict detection now
   uses the canonical iteration-based check (`_iter_reservations()`) which
   reads all lease files regardless of filename format.
