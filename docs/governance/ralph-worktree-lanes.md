# Ralph Worktree Lanes — Background Isolation Model

Ralph may operate in background lanes under explicit policy.
A Ralph lane is a dedicated branch/worktree isolation boundary.
One bounded Ralph mission = one Ralph lane.

## Two separate approvals

**Lane-start approval** — governed by `RalphBackgroundPolicy`:
- Authorizes lane proposal and isolated work within policy limits.
- Does not authorize merge, push, or mutation of active lanes.

**Adoption approval** — governed by `RalphAdoptionProposal`:
- Required before any Ralph lane work enters an orchestrator lane.
- Separate human-in-the-loop decision.
- Binds to exact lane state (lane_id, branch_name, review_bundle_sha256).

## Lane lifecycle

```
proposed → lane_start_approved → active → sealed →
  adoption_proposed → adopted (by human/orchestrator)
                   → rejected
                   → expired
```

## Isolation guarantees

- Ralph commits only to Ralph-owned branches (prefix: `ralph/`).
- Ralph worktrees live under `.rig/worktrees/ralph/` (configurable).
- Ralph must not merge into orchestrator lanes or main.
- Ralph must not push remote.
- Ralph must not mutate files outside its worktree scope.
- Ralph must not delete untracked user files.

## Background policy

See `rig_relay/ralph/background_policy.py`. Key fields:

- `enabled` — master toggle (default: false)
- `max_active_lanes` — concurrent Ralph lane limit (default: 2)
- `max_pending_review_lanes` — finished lane limit (default: 10)
- `require_lane_start_approval` — require human OK before lane work
- `require_adoption_approval` — require human OK before adoption

## Widget projection

The Ralph widget shows:
- `background_enabled` — toggle state
- `active_lane_count` — in-progress lanes
- `finished_lane_count` — completed lanes
- `pending_review_count` — lanes awaiting review
- `top_adoption_proposal_id` — highest-relevance proposal

Toggle ON authorizes only lane creation/isolated work.
Toggle ON does not authorize merge, push, or adoption.

## Review session

When the user returns and clicks review, Ralph presents a special
orchestrator review session explaining:
- what was done, when, and why
- evidence refs and validation results
- changed files and review bundle hash
- adoption recommendation

This session is contract-only in the current phase.
No execution, no merge, no git commands.

## Related components

- `ToolRuntime` — future execution authority (not invoked by lanes)
- `WorktreeManager` — git worktree lifecycle (lanes will plug in later)
- `Analytics compiler` — consumes lane events and projections
- `Desktop HITL boundary` — renders widget, sends toggle/approve intents
