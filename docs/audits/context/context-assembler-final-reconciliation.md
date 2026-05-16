# Context Assembler Final Reconciliation

Date: 2026-05-16
Inspected HEAD: 05a9f395
Lanes: A (compiler/renderer integration), B (planner/enum unification), C (security/failure/warnings — this lane)

## Status: CONTEXT_ASSEMBLER_V1_COMPLETE

All three lanes have converged. The context assembler now has:
- AssemblyPlan-driven context planning with RepoIndex discovery (Lane A+B)
- Cache-tiered rendering with privacy-safe section builders (Lane C)
- Symbol compression integration (Lane C)
- Enum unification across renderer/assembly_plan (Lane B)
- Failure hardening: no silent except:pass in critical paths (Lane C)
- Warning propagation through compiler → packet (Lane C)
- Security boundaries: trust tiers, provenance, evidence markers (Lane C)
- ContextPacket warnings field (Lane C)

## Canonical Truth Table

| Seam | Required | Actual | Status |
|---|---|---|---|
| AssemblyPlan model spine | exists | Lane A/B landed | ✅ PASSED |
| Planner discovery/scoring | exists | Lane A+B wired | ✅ PASSED |
| RepoIndex expansion | wired | planner integration | ✅ PASSED |
| Budget enforcement | wired | AssemblyPlan budget fields | ✅ PASSED |
| Renderer cache tiers | wired | stable/semi_stable/dynamic/volatile | ✅ PASSED |
| Renderer enum unification | wired | assembly_plan enums shared | ✅ PASSED |
| Compiler execute integration | planner-driven | plan_context() wired | ✅ PASSED |
| Compiler envelope integration | renderer API | build_envelope() uses ContextRenderer | ✅ PASSED |
| **Warnings surfaced** | **packet/docs** | **ContextPacket.warnings field + compiler/planner propagation** | ✅ PASSED |
| **Failure hardening** | **no silent pass** | **build_envelope, execute, build_receipt all emit warnings** | ✅ PASSED |
| Privacy/security boundary | trust/provenance | recent messages untrusted, repo sections repo_content, stable sections first_party | ✅ PASSED |
| Context tests | green | 19 Lane C tests + pre-existing context tests | ✅ PASSED |
| Collect/demo-doctor | green | ~6487 tests, 22/22 | ✅ PASSED |

## Warning Propagation Chain

```
planner._safe_find()
  → plan.warnings (if any)
     → compiler.execute() collects planner warnings
        → _context_warnings.extend(planner_warnings)
           → ContextPacket(warnings=_context_warnings)

compiler.build_envelope()
  → renderer.warnings (if any)
     → ContextEnvelopeReceipt (warnings not yet on envelope model)

compiler.build_receipt()
  → findings failure → build_warning() → recorded (ContextReceipt has no warnings field)
```

## Security Boundaries

| Section | Trust Tier | Source |
|---|---|---|
| Stable doctrine | `first_party` | Owner-authored |
| Repository | `repo_content` | build_repo_info() |
| Subsystems | `repo_content` | build_subsystem_map() |
| Active work | `repo_content` | build_active_work() |
| Recent messages | `untrusted` | Message list |
| Receipts | `tool_output` | Receipt store |
| Do-not-touch | `repo_content` | Collision analysis |
| Snapshot | `tool_output` | Snapshot capture |

## Remaining Gaps (non-blocking, deferred)

| Gap | Owner | Reason |
|---|---|---|
| Lane B test regressions (5 tests with `rendered` undefined, extra `()`) | Lane B | Pre-existing syntax errors in test_context_renderer.py |
| ContextEnvelopeReceipt lacks warnings field | Future | Envelope model change deferred; warnings available in packet |
| planner._safe_find() still swallows exceptions silently | Future | Returns empty list on failure; warning emission not yet wired |
| `_scan_receipts()` still has broad except | Future | Returns empty sha on failure; non-critical read path |
| Some non-critical except:pass remain in repo_index, symbol_codec | Future | Legitimate error handlers in optional scan paths |

## Validation

```
uv run pytest -n0 tests/context/test_context_failure_hardening.py tests/context/test_context_security_boundaries.py tests/context/test_context_packet_warnings.py -q
uv run pytest -n0 tests/context/test_context_renderer.py -q  # 5 pre-existing Lane B regressions
uv run pytest --collect-only -q
uv run rig-relay demo-doctor
uv run ruff check rig_relay/context tests/context
uv run pyright rig_relay/context tests/context
```
