# Coordination Guard Availability Audit

## Scope

Audit target: why governed edit tools are being blocked by the coordination guard and whether the cause is real active protection, stale leases, overly broad reservations, missing expiry, broken path normalization, or a tool integration bug.

This audit is read-only. It does not delete leases, bypass the guard, or mutate `/Users/user/.rig/relay`.

## Git State

- Branch: `main`
- HEAD: `384e486`
- Dirty status: pre-existing dirty files were already present before this audit; they were not modified by this audit.

## Coordination Guard Layout

Lease and coordination state live under:

- `.build/rig-relay/coordination/sessions/`
- `.build/rig-relay/coordination/tasks/`
- `.build/rig-relay/coordination/leases/paths/`
- `.build/rig-relay/coordination/events.jsonl`

The authoritative store is `rig_relay/coordination/store.py`. Lease cleanup logic exists in `rig_relay/coordination/cleanup_leases.py`.

## Guard Mechanics Observed

### Dirty-file protection

`rig_relay/governance/dirty_guard.py` captures the repo dirty set at mission start using `git status --porcelain=v1` and blocks writes to paths that were already dirty unless the caller supplies an expected hash for the protected file.

This is correct active protection for pre-existing dirty files.

### Coordination reservations

`rig_relay/coordination/store.py` stores path reservations in `.build/rig-relay/coordination/leases/paths/*.json` and claims in `.build/rig-relay/coordination/tasks/*.json`.

`search_replace` and `write_file` both claim coordination and reserve write paths before mutating. When reservation fails, they raise `ToolError("... coordination reservation refused")`.

## Inventory Summary

Read-only inventory of the coordination store on this repo snapshot:

- Lease/task records scanned: `512`
- Active records: `318`
- Released records: `193`
- Stale records: `1`
- Unique active path targets: `94`
- Unique active paths that overlap current git-dirty files: `52`

The overlap with git-dirty files indicates that a large share of the blocking is real protection of existing user-owned or prior-agent-owned changes.

## Blocked Tool Names

The blocked governed mutation surfaces observed in this audit are:

- `search_replace`
- `write_file`
- coordination-aware write/checkpoint flows that consult the same reservation store

These tools are blocked when the coordination store refuses a reservation or when the dirty guard marks the target as protected.

## Blocked Paths

The most frequent blocked paths are concentrated in the current mutation backlog:

- `vibe/core/tools/builtins/search_replace.py`
- `vibe/core/tools/builtins/validate.py`
- `tests/tools/test_validate.py`
- `rig_relay/evidence/model_observations.py`
- `scripts/rig_relay_contribute_telemetry_bundle.py`
- `rig_relay/evidence/receipt_index.py`
- `tests/evidence/test_receipt_index.py`
- `docs/governance/telemetry-contribution-policy.md`
- `tests/test_observation_consent_integration.py`
- `tests/tools/test_tool_receipt_emission.py`
- `tests/tools/test_hardened_tools.py`
- `tests/tools/test_bash_hardening.py`
- `tests/test_model_observations.py`
- `vibe/core/telemetry/constants.py`
- `vibe/core/tools/builtins/bash.py`

There is also a clean-path reservation example:

- `docs/audits/rig-intake-cannibalization-plan.md`

That means the guard is not only protecting dirty files; it is also carrying forward explicit coordination reservations from active or recent missions.

## Active vs Stale Classification

### Active protection

Most blocked paths are explained by active coordination records plus pre-existing dirty files. This is expected behavior.

### Stale lease

At least one stale lease was present:

- Lease file: `.build/rig-relay/coordination/leases/paths/cbb9f7f7b6feca9630da295cd47372af998cf2d615f355c14e68cc5730e5fd90.json`
- Session: `session_20260513_220723_3b1ecec2`
- Task: `call_00_0BqXT2mIh4vx09Leo1b69752`
- Path: `/Users/user/Developer/GitHub/rig-relay/tests/scripts/test_desktop_projection.py`
- Expiry: `2026-05-13T22:13:03.918976+00:00`

This is a stale lease candidate, not evidence of a current live owner.

### Broad scope risk

The reservation set is broader than the current mutation slice in a few places. The same mission family has reservations spanning many unrelated files, so a tool may be blocked even when the caller is trying to edit a different file in the same repo.

This suggests the guard is sometimes enforcing a valid lease at too coarse a scope rather than failing open.

### Path normalization risk

`rig_relay/coordination/store.py` normalizes paths for payloads, but some lookup and conflict checks mix raw input paths and normalized paths. Reservation files are keyed by a composite hash, while conflict lookup also hashes raw paths for existence checks.

That is a plausible source of false conflicts or stale-release friction, especially for equivalent but differently-formatted paths.

## Root Cause Assessment

### Correct active protection

Yes, for most of the observed blocking.

Evidence:

- 52 unique active paths overlap current git-dirty files.
- The repo has a large pre-existing dirty set.
- The coordination store contains many active reservations tied to current mission files.

### Stale lease

Present, but not the primary blocker.

Evidence:

- At least one expired reservation still exists as a stale record.

### Overly broad lease scope

Likely contributing factor.

Evidence:

- Active reservations span 94 unique paths while current mutations are concentrated in a smaller set of files.
- Some reserved paths are in audit/docs or adjacent tool files rather than the exact target slice.

### Missing lease expiry

Not the main issue.

Evidence:

- Expiry fields are present on the records.
- The issue is more about cleanup and scope than absence of expiry metadata.

### Broken path normalization

Plausible and worth fixing.

Evidence:

- `store.py` compares raw and normalized paths in different places.
- Reservation file identity and lookup are not using a single obvious canonical key path throughout the code.

### Tool integration bug

Yes.

Evidence:

- `search_replace` and `write_file` convert reservation refusal into `ToolError` instead of a structured result envelope.
- That makes blocked outcomes harder to reason about and easier for agents to work around with raw bash.

## Minimal Fix Recommendation

1. Keep the guard enabled.
2. Narrow reservation scope where possible so unrelated edits do not inherit broad blocks.
3. ~~Make reservation refusal return a structured blocked result instead of a generic `ToolError` for governed edit tools~~ **COMPLETED** — see Structured Blocking Implementation below.
4. Normalize path identity through one canonical function for reservation write, conflict lookup, release, and expiry processing.
5. Add a focused regression test for stale lease discovery and for a clean path that is incorrectly blocked.

## Structured Blocking Implementation

The third recommendation from the audit — returning structured `blocked`/`refused` results instead of generic `ToolError` — has been implemented for both `write_file` and `search_replace`.

### Changes to `write_file`

**File**: `vibe/core/tools/builtins/write_file.py`

1. **`WriteFileResult`** gained three new fields:
   - `status: str = "success"` — `"success"`, `"blocked"` (coordination), or `"refused"` (dirty guard)
   - `error_kind: str | None = None` — `"path_reserved"`, `"dirty_file_protected"`, `"expected_hash_mismatch"`, `"protected_file_missing"`
   - `refusal_reason: str | None = None` — human-readable detail from the guard

2. **`_classify_write_guard_refusal(check)`** — classifies `WriteGuardResult.reason` into a structured `error_kind`:
   - `stale_hash` / `hash_mismatch` → `"expected_hash_mismatch"`
   - `no_overwrite_flag` / `missing_expected_hash` → `"dirty_file_protected"`
   - `protected_file_missing` → `"protected_file_missing"`
   - fallback → `"dirty_file_protected"`

3. **Coordination reservation failure** (`_maybe_claim_coordination()`): now returns `False` instead of `raise ToolError(...)`.

4. **`run()` coordination failure**: yields `WriteFileResult(status="blocked", error_kind="path_reserved", ...)` when coordination store is available but reservation is refused.

5. **`run()` guard failure**: yields `WriteFileResult(status="refused", error_kind=<classified>, refusal_reason=check.detail, ...)` instead of `raise ToolError(...)`.

### Changes to `search_replace`

**File**: `vibe/core/tools/builtins/search_replace.py`

1. **Coordination reservation failure** (`_claim_coordination()`): now returns `False` instead of `raise ToolError(...)`.

2. **`run()` coordination failure**: yields `SearchReplaceResult(status="blocked", error_kind="path_reserved", ...)` when coordination store is available but reservation is refused.

### Error Kind Taxonomy

| `error_kind` | When emitted |
|---|---|
| `path_reserved` | Coordination reservation refused — path has an active lease from another session |
| `dirty_file_protected` | Dirty guard blocks write because `allow_overwrite_protected=True` was not set or `expected_before_sha256` was not provided |
| `expected_hash_mismatch` | `expected_before_sha256` does not match current file bytes |
| `protected_file_missing` | File that was dirty at mission start no longer exists |

### Design Decisions

1. **Conditional blocking**: Coordination failures only yield blocked results when the coordination store is available. If the store is absent (e.g., legacy tests), `_claim_coordination()` returns `False` and `run()` proceeds normally. This preserves backward compatibility.

2. **No path normalization change**: `normalize_path` in coordination models still only calls `as_posix()` without `resolve()`. Equivalent relative/absolute paths will not match. This was deferred to a follow-up.

3. **Content-light refusals**: Both `WriteFileResult` and `SearchReplaceResult` set `content=""` (and `after_sha256=""`) on blocked/refused results. No raw file contents, diffs, search text, or replace text leaked into refusal metadata.

### Tests Added

All in `tests/tools/test_hardened_tools.py`:

| Test | Verifies |
|---|---|
| `test_write_file_blocked_by_active_lease_returns_structured` | Coordination lease blocks → `status="blocked"`, `error_kind="path_reserved"` |
| `test_write_file_blocked_by_dirty_guard_returns_structured` | Dirty guard blocks → `status="refused"`, `error_kind="dirty_file_protected"` |
| `test_write_file_hash_mismatch_returns_structured` | Stale hash → `status="refused"`, `error_kind="expected_hash_mismatch"` |
| `test_write_file_correct_hash_succeeds` | Correct hash → `status="success"`, bytes written |
| `test_write_file_refusal_is_content_light` | No raw file contents in refusal dump |
| `test_search_replace_blocked_by_active_lease_returns_structured` | Coordination lease blocks → `status="blocked"`, `error_kind="path_reserved"` |
| `test_search_replace_refusal_is_content_light` | No raw search/replace text in refusal dump |
| `test_path_normalization_equivalent_forms` | `normalize_path` does NOT resolve — documents limitation |

Coordination-blocking tests use direct `CoordinationStore` reservations (not WriteFile-based setup) to avoid the WriteFile `finally` block releasing the lease prematurely.

### Validation

- **Tests**: 67/67 pass (29 in `test_hardened_tools.py`, 20 in `test_dirty_file.py`, 18 in `test_store.py`)
- **Lint**: `ruff check` clean, `ruff format` clean
- **Types**: `pyright` clean (0 errors, 0 warnings on changed files)
- **Schemas**: 78/78 schema validations pass

### Remaining Issues (deferred)

1. **Path normalization**: `normalize_path` needs `.resolve()` to match equivalent relative/absolute paths.
2. **Stale lease cleanup**: At least one stale lease remains in the coordination store.
3. **Broad lease scope**: Reservations spanning 94 unique paths create false positives.

## Safe Stale-Lease Cleanup Command

Yes, a safe cleanup command is useful, but it should remain archive-first and dry-run-first.

Recommended safe sequence:

1. Run the coordination lease cleanup script in dry-run mode.
2. If the result is clearly stale/released, archive first rather than delete.
3. Only consider deletion after inspecting the archive and confirming there is no live ownership.

The existing cleanup module already supports archive mode and destructive removal, so the safe operational answer is to prefer archive mode and keep deletion out of this audit mission.

## Validation

Focused read-only validation was performed by inspecting:

- `rig_relay/coordination/store.py`
- `rig_relay/coordination/cleanup_leases.py`
- `rig_relay/coordination/current_state.py`
- `rig_relay/governance/dirty_guard.py`

No files under `/Users/user/.rig/relay` were modified.
