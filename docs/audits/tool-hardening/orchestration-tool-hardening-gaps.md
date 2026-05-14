# Orchestration Tool Hardening Gaps

## Surfaces

- `coordination`
- `checkpoint`
- `validate`
- `session_lifecycle`
- `receipt_index`
- lane / worktree / promotion scripts

## Current Role

- `coordination` manages claims, leases, artifacts, and handoffs.
- `checkpoint` creates governed local commits.
- `validate` now acts as the read-only readiness gate.
- `receipt_index` summarizes content-light evidence.

## Current Risk

These surfaces can become new mutation channels if they are not anchored to hardened mutation and validation tools.

## Hardening Gaps

1. **Boundary enforcement**
   - Orchestration should not directly mutate unless it routes through hardened surfaces.

2. **Evidence lineage**
   - Orchestration should emit receipts or indexable evidence when it changes state.

3. **Dirty workspace respect**
   - Orchestration should preserve user-owned dirty files and fail closed on ambiguous state.

4. **Schema consistency**
   - Coordination, checkpoint, and validate should share a receipt and blocker vocabulary where possible.

5. **Promotion discipline**
   - Promotion should rely on validate plus evidence indices, not ad hoc shell checks.

## Priority

Orchestration hardening is second-order:

- finish mutation tools first
- then harden inspection tools
- then enforce orchestration prerequisites

## Safe Usage Rule

Do not let orchestration become a shortcut around hardened mutation or validation surfaces.
