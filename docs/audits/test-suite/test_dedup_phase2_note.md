# Test Deduplication Phase 2 — normalize high-value AST duplicate clusters

**Date**: 2026-05-16

## Preflight

- `scripts/rig_relay_test_duplicate_audit.py`: ruff clean, pyright clean
- Audit runs: 5970 tests scanned, max-exact-duplicate-groups=1 passes

## Audit Inspection Findings

The 35 normalized AST groups are mostly **false positives** from over-aggressive normalization. The normalizer strips model/variable names, so per-model validation tests (`test_rejects_unknown_fields` on `DecisionReason` vs `BlockedIntent` vs `AllowedIntent`) appear identical. These are legitimate separate tests — each model needs its own validation.

The 618 assert-shape groups are statistical clusters (largest: 479 members across 142 files). Not actionable without per-class analysis.

## Groups Parametrized

### test_governance_engine.py — TestGovernanceEngine

**Before**: 20 individual test methods, each calling `GovernanceEngine.evaluate_action_legality()` with hardcoded parameters and asserting a specific decision or reason code.

**After**: 2 parametrized contract matrices + 4 remaining distinct tests = 20 cases:

| Matrix | Cases | Parametrized IDs |
|---|---|---|
| Decision outcome | 11 | `allowed_read_only_intent`, `blocked_provider_trust_tier`, `blocked_provider_unavailable`, `blocked_provider_error`, `not_blocked_unavailable_read_only`, `requires_review_mutation`, `allows_mutation_when_allow_mutation`, `requires_review_network`, `allows_network_when_allow_network`, `blocked_dirty_policy`, `not_applicable_no_capabilities` |
| Reason codes | 5 | `reason_provider_trust_tier_blocked`, `reason_mutation_requires_review`, `reason_network_requires_review`, `reason_dirty_policy_violated`, `reason_no_requested_capabilities` |
| Remaining | 4 | `test_allowed_read_only_includes_allowed_intent`, `test_blocked_intent_includes_reason_code`, `test_blocked_when_multiple_checks_fail`, `test_pure_no_side_effects` |

**Failure diagnostics preserved**: Each parametrized case has a human-readable ID. When a test fails, the node ID (e.g., `test_evaluate_action_legality_decision[blocked_provider_trust_tier]`) immediately identifies the scenario.

## Audit Metrics

| Metric | Before | After |
|---|---|---|
| Scanned | 5966 | 5970 |
| Exact body groups | 1 | 1 |
| Normalized AST groups | 35 | 35 |
| Assert shape groups | 618 | 616 |
| Collected | 6236 | 6266 |

Note: Parametrized cases expand the collected count. Audit metrics show minimal change because the normalizer strips variable names — parametrized matrices with different kwargs look structurally similar to the audit.

## Files Changed

| File | Change |
|---|---|
| `scripts/rig_relay_test_duplicate_audit.py` | Fixed 5 ruff findings, added `_TRUNCATE_LIMIT`, fixed return type annotation |
| `tests/governance/test_governance_engine.py` | 20 individual tests → 2 parametrized matrices + 4 distinct tests |

## Guardrail

- `--max-exact-duplicate-groups=1` continues to pass (1 group remaining by design — shared helper pattern)
- Normalized AST threshold not added — groups are false positives, not actionable for ratcheting

## Deferred

| Group | Reason |
|---|---|
| test_config_resolution.py (P2) | Per-model resolution tests — not duplicates |
| test_bash.py (P3) | Dirty file, parallel lane active |
| test_fuzzy.py (P4) | Different edge cases — parametrization would require branching logic |
| test_backend_adapters | anthropic ↔ vertex_anthropic overlap needs adapter contract audit, not test dedup |
