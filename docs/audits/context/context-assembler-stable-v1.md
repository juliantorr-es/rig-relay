# Context Assembler Stable v1

Date: 2026-05-18. HEAD: 7b4e5166.

## Status: CONTEXT_ASSEMBLER_STABLE_V1

The context assembler is stable, tested, and privacy-hardened. All critical-path
failures emit structured warnings. No silent `except: pass` remains in the
compiler, planner, or renderer execution paths.

## Stable API

| Component | Entry point | Contract |
|---|---|---|
| `ContextRequest` | `rig_relay/context/models.py` | Scope, budget, freshness, output, compression |
| `ContextPacket` | `rig_relay/context/models.py` | Canonical output with warnings, recommended_context, do_not_touch |
| `ContextAssemblyPlan` | `rig_relay/context/assembly_plan.py` | Candidates, selections, omissions, budget ledger, warnings, hashes |
| `ContextRenderer` | `rig_relay/context/renderer.py` | Cache-tiered sections, privacy-safe metadata, compression |
| `plan_context()` | `rig_relay/context/planner.py` | Deterministic discovery, RepoIndex expansion, scoring, budget enforcement |

## Source truth

| File | Status |
|---|---|
| `compiler.py` | `execute()` calls `plan_context()` with `RepoContextIndex(root)`. `build_envelope()` uses `renderer.section_count`. `build_receipt()` has no bare `except: pass`. `_scan_receipts()` emits warnings on read failure. |
| `planner.py` | `_safe_find()` and `_safe_find_dict()` return `(result, error)` tuples. Per-method RepoIndex warnings emitted. Negative `max_tokens` clamped. |
| `renderer.py` | Imports `CacheTier`/`TrustTier` from `assembly_plan.py`. `section_metadata` returns `list[ContextRenderedSection]` — no raw content. |
| `assembly_plan.py` | Full model spine: `ContextCandidate`, `ContextSelection`, `ContextOmission`, `ContextBudgetLedger`, `ContextAssemblyWarning`, `ContextAssemblyPlan`. |
| `models.py` | `ContextPacket` has `warnings: list[dict[str, Any]]`. |
| `warnings.py` | `ContextWarningCode` with 13 codes. `build_warning()` helper. `exception_class_name()` helper. |

## Warning policy

| Artifact | Warnings? | Rationale |
|---|---|---|
| `ContextPacket` | ✅ Yes | Primary carrier for request-execution warnings. Planner, RepoIndex, receipt-scan, and renderer warnings all flow here. |
| `ContextEnvelopeReceipt` | ❌ No (v1) | Remains prompt-envelope evidence. Warnings available via `ContextPacket`. Future model change if needed. |
| `ContextReceipt` | ❌ No (v1) | Remains summary evidence. Warnings available via `ContextPacket`. Future model change if needed. |

## Privacy policy

- Recent messages: `role` + `sha256` + `byte_count` only. No raw content.
- Repository root: `root_hash` only. No raw path.
- Git head: `head_hash` only.
- Collision paths: `path_hash` only.
- Receipt paths: repo-relative only.
- Warnings: `exception_class_name()` only. No raw exception messages, paths, or secrets.

## Cache layout

| Tier | Sections |
|---|---|
| `stable` | AGENTS/doctrine/schema — invariant rules |
| `semi_stable` | Repo topology, subsystem map |
| `dynamic` | Dirty files, active lanes, collisions |
| `volatile` | User task hash, recent message metadata, receipts |

## Security posture

Context evidence is NOT instructions. All rendered context is labeled with
`trust_tier` and `provenance`. Untrusted content (tool output, external docs)
is separated from first-party doctrine. The assembler does not amplify prompt
injection.

## Remaining future work

| Item | Status |
|---|---|
| Language adapters for non-Python repos | Future slice |
| Receipt/envelope warnings fields | Deferred — non-blocking |
| `include_other_agents` gating | Future planner slice |
| `workspace_root` validation | Future hardening slice |
| Symbol codec positive-savings compression | Exists in renderer, tested |
| Compiler.build_receipt findings integration | Deferred — uses `compute_findings_summary()` with warning |

## Validation

```
uv run pytest tests/context/ -q
  → 285 passed, 3 skipped

uv run pytest tests/context/test_context_stable_v1.py tests/context/test_context_final_closeout.py -q
  → all passed

uv run ruff check rig_relay/context tests/context
  → clean

uv run pyright rig_relay/context tests/context
  → 0 errors

uv run pytest --collect-only -q
  → 6533+ tests

uv run rig-relay demo-doctor
  → 22/22
```
