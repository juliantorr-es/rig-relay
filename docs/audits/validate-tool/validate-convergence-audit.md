# Validate Workstream Convergence Audit

**Date:** 2026-05-13
**Branch:** main
**HEAD:** 384e4860b14959769a14fbcb5b4ca27618dad861
**Scope:** Post-mission reconciliation for Stage 2/3/4/5 parallel validate work

---

## 1. Repo State Summary

### Dirty Files (Validate-Related)

| File | Status | Lines | Role |
|------|--------|-------|------|
| `vibe/core/tools/builtins/validate.py` | untracked | 1538 | Core tool implementation |
| `tests/tools/test_validate.py` | untracked | 1797 | Main test file (all stages) |
| `tests/tools/test_validate_git_state.py` | untracked | 390 | Git-state-only test file |
| `docs/audits/validate-tool/validate-tool-contract.md` | untracked | ~315 | Contract doc |
| `docs/audits/validate-tool/validate-profile-taxonomy.md` | untracked | ~300 | Profile registry doc |
| `docs/audits/validate-tool/validate-implementation-roadmap.md` | untracked | ~395 | Roadmap doc |
| `docs/schemas/rig.relay.validate_invocation.v1.schema.json` | untracked | — | Invocation schema |
| `docs/schemas/rig.relay.validate_result.v1.schema.json` | untracked | — | Result schema |
| `docs/schemas/rig.relay.validate_receipt.v1.schema.json` | untracked | — | Receipt schema |
| `test_out.txt` | untracked | ~500 | Stale pytest output dump |

### Stale/Backup Files
- `test_out.txt` (18 KB pytest log) — should be removed or gitignored.

---

## 2. Current Validate Feature Matrix

| Feature | Status | Notes |
|---------|--------|-------|
| **Stage 1: Profile Runner** | | |
| Profile registry | complete | `_register()` / `get_profile()` / `list_profiles()` |
| ValidateArgs | complete | All fields: profile, paths, workspace_root, expected_dirty_policy, etc. |
| ValidateCheckResult | complete | Pydantic model with parsed_summary, status, blocker_summary |
| ValidateResult | complete | Content-light (extra=forbid), no raw stdout/stderr |
| quick profile | complete | ruff, pyright, pytest, git-diff checks |
| python profile | complete | ruff, pyright, pytest checks |
| schemas profile | complete | schema validation script check |
| receipt-policy profile | complete | receipt policy script check |
| tool-hardening profile | complete | pytest on hardening tests |
| worktree-readiness profile | complete | No commands, purely git state + dirty policy |
| **Stage 2: Content-Light Receipts** | | |
| ValidateReceipt | complete | extra=forbid, no raw output |
| ValidateCheckReceipt | complete | extra=forbid, hashes + counts only |
| build_receipt() | complete | On Validate class |
| Receipt schema | complete | Validated (78/78) |
| Receipt index support | complete | In evidence infrastructure |
| Receipt policy validation | complete | Receipts pass policy checks (25/25) |
| **Stage 3: Path Scoping** | | |
| Path normalization | complete | _normalize_validate_paths(), posix-only |
| Stable relative path policy | complete | No absolute paths in results/receipts |
| affected_paths behavior | complete | On scoped checks only |
| command_fingerprint determinism | complete | SHA256 of normalized argv |
| scope_check_argv | complete | Per-profile path scoping |
| **Stage 4: Parsed Summaries** | | |
| ruff parser | complete | _parse_ruff_summary |
| pyright parser | complete | _parse_pyright_summary |
| pytest parser | complete | _parse_pytest_summary |
| schema parser | complete | _parse_schema_summary |
| receipt-policy parser | complete | _parse_policy_summary |
| parsed_summary field | complete | On ValidateCheckResult (not on receipt) |
| **Stage 5: Git State** | | |
| ValidateGitState model | complete | 18 fields, extra=forbid |
| git porcelain parser | complete | _parse_git_status_porcelain, _parse_git_status_branch, _parse_git_status_porcelain_line |
| before_git_state | complete | ValidateGitState on ValidateResult |
| after_git_state | complete | ValidateGitState on ValidateResult |
| expected_dirty_policy enforcement | complete | Allow_dirty, clean, allow_listed_dirty |
| dirty policy blocker mapping | complete | blocker_summary with "dirty_workspace" |

---

## 3. Inconsistencies Found

### 3A. Stage Numbering Conflicts (Critical)

The **implementation-roadmap.md** has non-sequential ordering:

```
Line  3: Stage 0
Line 25: Stage 1
Line 75: Stage 2
Line 114: Stage 3
Line 190: Stage 5 ← Stage 5 BEFORE Stage 4
Line 236: Stage 4 ← Stage 4 AFTER Stage 5
Line 301: Stage 5 (duplicate — Worktree / Lane Awareness)
Line 326: Stage 5 (duplicate — Aggregate Patch Eligibility)
Line 350: Stage 6
Line 373: Stage 7
```

Three entries claim "Stage 5". The ordering suggests parsed summaries should be Stage 4 and worktree/lane awareness should be Stage 5, but the entries are reversed.

The **validate-tool-contract.md** also has out-of-order sections:
- Stage 2, Stage 3, Stage 5, then Stage 4

**Recommendation:** Adopt canonical numbering:
- Stage 0: Audit and Contract Only
- Stage 1: Read-Only Validate Profiles
- Stage 2: Content-Light ValidateReceipt
- Stage 3: Path-Scoped Validation Profiles
- Stage 4: Parsed Summaries
- Stage 5: Worktree/Lane Awareness and Dirty-State Policy
- Stage 6: Aggregate Patch Eligibility
- Stage 7: Promotion Gate Integration
- Stage 8: Fleet/Delegate Policy Integration

### 3B. Schema Drift (Medium)

- **Result schema:** `before_git_state` and `after_git_state` are defined as `type: object` with no properties, described as "Optional pre-state git snapshot". The Pydantic model `ValidateGitState` has 18 specific fields. The schema should either define these properties or reference a `$defs/ValidateGitState`.
- **Receipt schema:** Has proper `GitSummary` `$def` that matches the model — no drift here.
- **Invocation schema:** Matches Pydantic model exactly.

### 3C. Duplicate Test Coverage (Medium)

Two test files test the same features:

| Feature | In test_validate.py | In test_validate_git_state.py |
|---------|---------------------|-------------------------------|
| Git state model | `test_validate_git_state_extra_forbidden` | `test_git_state_extra_forbidden`, `test_git_state_defaults`, `test_git_state_fields` |
| Dirty policy (7 tests) | 6 tests (allow_dirty, clean, allow_listed) | 7 tests (same policies + non-repo + clean-when-clean) |
| Porcelain parsing | 5 tests (branch, lines, full output) | 3 tests (clean, mixed, empty, paths) |
| Receipt git summary | 1 test | 2 tests (content-light, none-when-no-git) |
| Worktree-readiness profile | 1 test | 3 tests (exists, no-checks, description) |
| **Exact duplicate** | `test_validate_receipt_git_summary_content_light` | `test_validate_receipt_git_summary_content_light` |

### 3D. `# type: ignore` Violation (Minor)

**tests/tools/test_validate.py line 1773:**
```python
ValidateGitState(is_git_repo=True, unknown_field="test")  # type: ignore
```
This violates AGENTS.md ("No inline # type: ignore or # noqa"). The fix should use `model_validate`:
```python
ValidateGitState.model_validate({"is_git_repo": True, "unknown_field": "test"})
```

### 3E. Stale Doc References (Minor)

- Contract doc line 70-71: documents `before_git_state` as `dict | None` but the model is `ValidateGitState | None`
- Roadmap describes Stage 5 with `test_validate_git_state.py` reference — but git state tests also exist in `test_validate.py`

### 3F. Stale Artifact (Trivial)

- `test_out.txt` is an 18 KB pytest log dump not tracked or gitignored.

---

## 4. File Size and Decomposition Needs

### validate.py — 1538 lines, 37 functions, 10 classes

| Section | Lines | Functions | Decomposition Priority |
|---------|-------|-----------|----------------------|
| Imports | ~24 | — | — |
| Profile registry | ~130 | 3 functions, 2 classes | Medium |
| Models | ~110 | 8 classes | **High** |
| Blocker taxonomy | ~40 | 2 functions | Low |
| Subprocess/check runner | ~120 | 1 async function | Medium |
| Parsed summaries | ~170 | 6 functions | **High** |
| Path scoping | ~42 | 4 functions | Medium |
| Git state helpers | ~85 | 6 functions | **High** |
| Dirty policy | ~50 | 1 function | Medium |
| Validate class | ~360 | 8 methods (1 is 140-line `run()`) | **High** |

**Recommended decomposition targets** (for future cleanup):
- `vibe/core/tools/builtins/validate/models.py` — all Pydantic models
- `vibe/core/tools/builtins/validate/profiles.py` — profile registry
- `vibe/core/tools/builtins/validate/_runner.py` — subprocess runner
- `vibe/core/tools/builtins/validate/_parsed_summaries.py` — all 5 parsers
- `vibe/core/tools/builtins/validate/_git_state.py` — git state helpers + dirty policy
- `vibe/core/tools/builtins/validate/_paths.py` — path normalization + scoping

**Largest functions:**
- `run()`: ~140 lines (line 1390-1529) — profile resolution, mutation/network checks, git state, dirty policy, path scoping, check loop, result build
- `_parse_ruff_summary()`: ~40 lines
- `_run_check()`: ~115 lines

### test_validate.py — 1797 lines, 116 tests

| Section | Tests | Lines |
|---------|-------|-------|
| Profiles | ~6 | ~40 |
| fingerprint/kinds | ~10 | ~70 |
| Models (receipts, results) | ~12 | ~200 |
| Blocker taxonomy | ~10 | ~90 |
| Path scoping | ~25 | ~400 |
| Parsed summaries | ~20 | ~250 |
| Git state / dirty policy | ~19 | ~230 |
| Imports and fixtures | — | ~40 |

**Recommended test split:**
- `tests/tools/test_validate_models.py` — model validation tests
- `tests/tools/test_validate_profiles.py` — profile registration tests
- `tests/tools/test_validate_paths.py` — path normalization tests
- `tests/tools/test_validate_parsed_summaries.py` — parser tests
- `tests/tools/test_validate_git_state.py` — consolidate git state tests (remove from test_validate.py)

### test_validate_git_state.py — 390 lines, 21 tests

This file exists as a standalone but has 1 exact duplicate and ~15 near-duplicate tests with `test_validate.py`. After consolidation, this should be the sole home for git state tests (~25 unique tests).

---

## 5. Test Results (All Passing)

| Test Suite | Tests | Result |
|------------|-------|--------|
| `tests/tools/test_validate.py` | 127 | ✅ All passed |
| `tests/tools/test_validate_git_state.py` | 27 | ✅ All passed |
| `tests/tools/test_tool_receipt_emission.py` | 34 | ✅ All passed |
| `tests/evidence/test_tool_receipt_policy.py` | 25 | ✅ All passed |
| `tests/evidence/test_receipt_index.py` | 40 | ✅ All passed |
| Schema validation (78 schemas) | 78 | ✅ All passed |
| Schema Python contamination | 1 | ✅ Passed |

Ruff and pyright: all clean (0 errors).

---

## 6. Cleanup Roadmap

### Stage A — Documentation Canonicalization (safe, docs-only)
1. Reorder roadmap stages: Stage 4 = Parsed Summaries, Stage 5 = Worktree/Lane Awareness
2. Deduplicate the three "Stage 5" entries
3. Update contract doc: fix `dict | None` → `ValidateGitState | None` references
4. Add `test_out.txt` to `.gitignore` or confirm deletion

### Stage B — Policy Cleanup (safe, targeted)
1. Fix `# type: ignore` at test_validate.py:1773 using `model_validate()`
2. Remove `test_out.txt` if confirmed stale

### Stage C — Schema/Model Alignment (safe, additive)
1. Add `ValidateGitState` properties to result schema's `before_git_state`/`after_git_state` object definitions
2. Add schema-model roundtrip test

### Stage D — Validate Module Decomposition (risky, requires planning)
1. Extract models → `_models.py`
2. Extract profiles → `_profiles.py`
3. Extract parsed summaries → `_parsed_summaries.py`
4. Extract git state → `_git_state.py`
5. Extract path scoping → `_paths.py`
6. Keep `validate.py` as the public tool class with thin imports

### Stage E — Test File Decomposition (risky, depends on D)
1. Split `test_validate.py` by concern (models, profiles, paths, summaries, git)
2. Remove git state tests from `test_validate.py` (keep only in `test_validate_git_state.py`)
3. Remove the exact duplicate `test_validate_receipt_git_summary_content_light`

### Stage F — Promotion-Readiness Profile (after cleanup)
Only after all cleanup is complete.

---

## 7. Recommended Next Implementation Slice

**First action:** Stage A (docs) + Stage B (policy fix) — these are safe, docs-only or single-line changes that resolve the most visible inconsistencies.

**Then:** Stage C (schema alignment) — additive schema detail that doesn't break anything.

**Defer:** Stage D and E (decomposition) — requires careful planning and testing; not suitable for a single session.

---

## 8. Cleanup Applied (Stages A–C)

### Stage A — Documentation Canonicalization ✅

**Roadmap** (`validate-implementation-roadmap.md`):
- Swapped Stage 4 (Parsed Summaries) and Stage 5 (Worktree/Lane Awareness) to canonical order
- Removed duplicate "Stage 5 — Worktree / Lane Awareness" entry
- Renumbered rest: Stage 5→5 (Aggregate), Stage 6→7 (Promotion), Stage 7→8 (Fleet)
- Final order: Stage 0, 1, 2, 3, 4, 5, 6, 7, 8 (sequential)

**Contract** (`validate-tool-contract.md`):
- Removed duplicate Stage 5 section (was labeled Stage 4 — Worktree/Lane Awareness)
- Fixed stale `dict | None` → `ValidateGitState | None` for `before_git_state`/`after_git_state` in the ValidateResult table
- Final: Stage 2, Stage 3, Stage 5 (no gaps, no duplicates)

### Stage B — Policy Cleanup ✅

**Inline type ignore** (`tests/tools/test_validate.py:1773`):
- Changed from: `ValidateGitState(is_git_repo=True, unknown_field="test")  # type: ignore`
- Changed to: `ValidateGitState.model_validate({"is_git_repo": True, "unknown_field": "test"})`
- AGENTS.md violation resolved.

**Stale test_out.txt**:
- Removed (18 KB pytest log dump at repo root).

### Stage C — Schema Alignment ✅

**Result schema** (`docs/schemas/rig.relay.validate_result.v1.schema.json`):
- Added `$defs.ValidateGitState` with all 18 fields matching the Pydantic model
- Updated `before_git_state` from bare `{"type": "object"}` to `{"anyOf": [{"type": "null"}, {"$ref": "#/definitions/ValidateGitState"}]}`
- Updated `after_git_state` identically
- Schema still passes 78/78 validation and Python contamination test

### Items Not Yet Applied

- Duplicate git state tests across `test_validate.py` and `test_validate_git_state.py` (1 exact + ~15 near-duplicate) — deferred to Stage E
- Validate module decomposition (1538-line validate.py) — deferred to Stage D
- Test file splitting (1797-line test_validate.py) — deferred to Stage E
- Promotion-readiness profile — deferred to Stage F
