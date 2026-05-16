# Lane B — Planner Failure Warnings, RepoIndex Reality, Budget Semantics

Date: 2026-05-15. HEAD: 63cdc9e2.

## Other lane reports read

| Report | Status |
|---|---|
| `docs/audits/context/context-assembly-plan-v1.md` | Not found |
| `docs/audits/context/context-planner-v1.md` | Not found |
| `docs/audits/context/context-renderer-contract-unification-v1.md` | Not found |
| `docs/audits/context/context-failure-security-hardening-v1.md` | Not found |
| `docs/audits/context/context-assembler-final-reconciliation.md` | Not found |
| `docs/audits/context/gap-reports/lane-a-compiler-renderer-gaps.md` | Not found |
| `docs/audits/context/gap-reports/lane-c-security-final-gaps.md` | Not found |

No other lane reports exist yet. Lane B is the first reconciliation lane.

## Files changed

| File | Δ | Purpose |
|---|---|---|
| `rig_relay/context/planner.py` | +20/-25 | Refactored `_safe_find()` and `_safe_find_dict()` to return `(result, error)` tuples. Removed outer `try/except Exception` wrapper from RepoIndex expansion. Added per-method warning emission for `find_tests`, `find_docs`, `find_schemas`, `find_related`. Clamped negative `max_tokens` to 0. |
| `tests/context/test_context_planner_failure_hardening.py` | **new** (7 tests) | Per-method failure warnings, repo_index_none warnings, content-light error messages |
| `tests/context/test_context_planner_budget_semantics.py` | **new** (12 tests) | Budget invariants (never exceeded, tiny budget priority, negative clamped, omissions preserve IDs), privacy (no absolute paths, collision omission), candidate defaults (trust/cache tiers) |

## Planner warnings — query-level failure model

**Before:** `_safe_find` and `_safe_find_dict` returned empty results on failure. Individual method failures were invisible — only a broad `repo_index_unavailable` warning fired if ALL methods failed (wrapped in outer `try/except`).

**After:** Each RepoIndex method call (`find_tests`, `find_docs`, `find_schemas`, `find_related`) independently records a `repo_index_query_failed` warning with the method name and truncated error. Planning continues with whatever results succeeded.

## Budget semantics

| Behavior | Status |
|---|---|
| `max_tokens` positive → never exceeded | ✅ Tested |
| Tiny budget keeps highest priority | ✅ Tested |
| Negative `max_tokens` → clamped to 0 | ✅ Tested |
| Budget omissions preserve `candidate_id` + `estimated_tokens` | ✅ Tested |
| Large budget selects all non-risk | ✅ Tested |
| `include_receipts` only as omission gate | Documented: discovery is compiler-owned |

## Gaps closed

| Gap | Resolution |
|---|---|
| `_safe_find` silent failures | Now returns `(result, error)` tuples with truncated error strings |
| Individual RepoIndex method failures invisible | Per-method `repo_index_query_failed` warnings emitted |
| `workspace_root` unused | Kept as reserved for future repo-relative validation |
| `max_tokens` negative allowed | Clamped to 0 with `max(0, ...)` |

## Gaps left open

| Gap | Owner | Reason |
|---|---|---|
| Receipt discovery not implemented | Compiler/Lane A | Planner marks `include_receipts` as omission-only gate; actual receipt candidates come from compiler |
| `workspace_root` not used for validation | Full planner slice | Reserved for repo-relative path validation in a future hardening slice |
| `include_other_agents` not gated | Planner slice | Flag exists in model but active work candidates not yet filtered by this flag |

## Cross-lane follow-up

| What | Who |
|---|---|
| Wire planner into `compiler.execute()` | Lane A |
| Add receipt discovery candidates | Lane A |
| Add `include_other_agents` gating | Planner hardening slice |

## Final status recommendation: **INTEGRATED_WITH_GAPS**

The planner is now truthful about RepoIndex failures, budget semantics are explicit, and trust/cache tier defaults are verified. The remaining gaps (receipt discovery, workspace validation, agent filtering) are well-scoped and owned by specific lanes.
