# CI Implementation Roadmap

> **Status**: Established — Stage 1 Implemented
> **Date**: 2026-05-17 (Stage 1: 2026-05-17)
> **Scope**: Staged implementation plan for CI gate architecture.
> **Stage 1 implemented**: See ci-surface-audit.md for CI coverage updates.

## Overview

Seven stages, ordered by dependency and risk. Each stage builds on the previous. Implementation should not skip stages — each stage has specific exit criteria that must be met before the next begins.


---

## Stage 0 — Audit and Inventory Only

**Status: COMPLETE** (this document set)

**Goal:** Document all existing CI, validation, and governance surfaces. Design the tiered gate architecture. Do not change any workflows.

**Artifacts produced:**
- `docs/audits/ci/ci-surface-audit.md` — surface inventory and gap analysis
- `docs/audits/ci/ci-check-inventory.jsonl` — 41-record structured check inventory
- `docs/audits/ci/ci-gate-architecture.md` — 5-tier gate design
- `docs/audits/ci/ci-path-trigger-map.md` — path-based trigger rules
- `docs/audits/ci/ci-validate-alignment.md` — CI ↔ validate profile mapping
- `docs/audits/ci/ci-implementation-roadmap.md` — this document

**Files changed:** None (new docs only).

**Risks:** None — read-only design stage.

**Exit criteria:**
- [x] All 6 audit documents created
- [x] Check inventory JSONL is parseable
- [x] Existing CI workflows documented
- [x] Gaps identified
- [x] Redundancies identified
- [x] Validate-tool alignment designed

---

## Stage 1 — Required PR Baseline

**Goal:** Add missing Tier 1 gates to the existing `ci.yml` without restructuring the workflow.

**Likely files affected:**
- `.github/workflows/ci.yml` — add steps to pre-commit and tests jobs
- No new workflow files

**Checks added:**
1. Schema validation: `uv run python scripts/rig_relay_validate_schemas.py` (pre-commit job)
2. Schema Python contamination: `uv run pytest tests/coordination/test_schema_validation.py -k test_no_schema_contains_python_syntax -n0` (pre-commit job)
3. Tool receipt emission: `uv run pytest tests/tools/test_tool_receipt_emission.py -n0` (tests job)
4. uv lock check: `uv lock --check` (pre-commit job)

**Workflow removals:**
1. Delete `.github/workflows/pylint.yml`
2. Delete `.github/workflows/python-package-conda.yml`

**Risks:**
- Adding steps increases CI time — mitigate by keeping them fast (<30s total)
- Deleting stale workflows may break external expectations — verify no external consumers

**Exit criteria:**
- [x] All 4 new PR baseline checks pass in CI
- [x] Stale workflows deleted
- [x] CI time increase <30s
- [x] No false positives on clean PRs
- [x] No false negatives on intentionally broken PRs

---

## Stage 2 — Path-Aware Specialized Gates

**Goal:** Add Tier 2 path-filtered jobs to `ci.yml` so domain-specific tests only run when relevant paths change.

**Likely files affected:**
- `.github/workflows/ci.yml` — add conditional jobs using `paths:` filter or `dorny/paths-filter` action

**Checks added (as conditional jobs):**
1. Bash hardening (on `vibe/core/tools/builtins/bash.py` or `docs/schemas/rig.relay.bash_*`)
2. SearchReplace hardening (on `vibe/core/tools/builtins/search_replace.py` or `docs/schemas/rig.relay.search_replace_*`)
3. Evidence/receipt tests (on `rig_relay/evidence/**`)
4. Coordination tests (on `rig_relay/coordination/**`)
5. Script tests (on `scripts/**` or `tests/scripts/**`)
6. Governance/docs tests (on `docs/governance/**` or `docs/**/*.md`)

**Risks:**
- Path filter misconfiguration can cause false passes (gate doesn't run when it should)
- Too many conditional jobs cause workflow YAML bloat
- `dorny/paths-filter` is an external action — pin version and review

**Exit criteria:**
- [ ] Each Tier 2 gate triggers only on its path pattern
- [ ] Each Tier 2 gate passes on known-good paths
- [ ] PRs without matching paths do not trigger Tier 2 gates
- [ ] No more than 3 parallel Tier 2 jobs at once

---

## Stage 3 — Receipt Policy and Evidence Index Gates

**Goal:** Integrate the receipt policy validator (`scripts/rig_relay_validate_tool_receipts.py`) as a standalone CI step, including synthetic receipt data for validation.

**Likely files affected:**
- `.github/workflows/ci.yml` — add receipt policy validation step in tests job
- `tests/fixtures/` — possibly create synthetic observability JSONL fixture

**Checks added:**
1. Receipt policy validation on synthetic data: `uv run python scripts/rig_relay_validate_tool_receipts.py <fixture-path>`
2. Receipt index tests (already covered by evidence tests in Stage 2)

**Risks:**
- Synthetic fixture must be kept in sync with real receipt schema — add test to detect drift
- Receipt policy validator expects a JSONL file — must create or generate one in CI

**Exit criteria:**
- [ ] Receipt policy validator runs on synthetic data in CI
- [ ] Synthetic fixture is version-controlled and schema-tested
- [ ] Policy violation in synthetic data blocks PR

---

## Stage 4 — Validate-Tool Backed CI Profiles

**Goal:** Implement the `validate` tool with its first profiles. CI workflows become thin wrappers that call `validate <profile>` instead of inline commands.

**Likely files affected:**
- `vibe/core/tools/builtins/validate.py` — new validate tool module
- `vibe/core/tools/__init__.py` — register validate tool
- `tests/tools/test_validate.py` — extend for profile dispatch
- `.github/workflows/ci.yml` — replace inline commands with `validate <profile>` calls

**Profiles implemented (Stage 4 scope):**
- `quick` — git status, focused ruff, focused pytest, lock check
- `python` — ruff check, ruff format, pyright
- `schemas` — schema validation, Python contamination, artifact/telemetry schemas
- `receipt-policy` — receipt emission tests, receipt policy validator, evidence tests

**Risks:**
- validate tool must be available in CI before workflows can reference it
- Profile definition must be deterministic and well-tested
- Pre-commit hooks still own ruff/pyright — avoid dual gating

**Exit criteria:**
- [ ] validate tool exists with `quick`, `python`, `schemas`, `receipt-policy` profiles
- [ ] Each profile runs the correct commands and exits appropriately
- [ ] CI workflows call validate profiles for at least 3 gates
- [ ] No regression in existing CI behavior

---

## Stage 5 — Promotion-Readiness Gate

**Goal:** Implement Tier 3 promotion gate as a separate workflow or reusable workflow call. This is the final quality gate before merge to main.

**Likely files affected:**
- `.github/workflows/promotion-readiness.yml` — new workflow (reusable or triggered)
- `.github/workflows/ci.yml` — may reference promotion readiness

**Checks added:**
1. All Tier 1 + Tier 2 (scoped to changes)
2. Full pytest suite (except snapshots, network-dependent)
3. Snapshot tests (continue-on-error)
4. Dirty workspace check (`git status --porcelain`)
5. `uv sync --locked` (full sync check, not just lock)
6. `uv build` (dry-run)

**Risks:**
- Full pytest suite is slow (~5-10 min) — may need to optimize before gating promotion
- Dirty workspace check is meaningful only if CI runs on merge queue or after local validation

**Exit criteria:**
- [ ] Promotion readiness workflow exists and passes on clean PRs
- [ ] Fails on known-broken PRs
- [ ] Full test suite completes within 10 minutes
- [ ] Dirty workspace check integrated

---

## Stage 6 — Nightly / Deep Audit Gates

**Goal:** Implement Tier 4 nightly and manual audit workflows.

**Likely files affected:**
- `.github/workflows/nightly-audit.yml` — new scheduled workflow
- `.github/workflows/manual-audit.yml` — workflow_dispatch workflow

**Checks added:**
1. Stale coordination lease audit (nightly)
2. Full platform build matrix (nightly or pre-release)
3. Snapshot regeneration check (nightly)
4. Generated docs drift detection (nightly)
5. Desktop cockpit tests (manual dispatch)

**Risks:**
- Nightly workflows consume CI minutes — keep them efficient
- Desktop cockpit tests may fail in headless environments

**Exit criteria:**
- [ ] Nightly workflow runs on schedule
- [ ] Stale lease detection does not produce false positives
- [ ] Full platform build completes within 30 minutes
- [ ] Manual dispatch triggers desktop tests

---

## Stage 7 — Fleet / Delegate Lane CI Integration

**Goal:** Integrate CI with the fleet/delegate lane orchestration system for multi-agent CI pipelines.

**Likely files affected:**
- `.github/workflows/fleet-ci.yml` — new workflow for parallel lane execution
- `rig_relay/coordination/delegate_fleet.py` — possibly extend for CI orchestration

**Checks added:**
1. Parallel delegation of CI checks across lanes
2. Fleet-level coordination validation
3. Worktree script safety validation

**Risks:**
- Fleet orchestration in CI is experimental — high complexity
- Requires coordination backend to be CI-compatible

**Exit criteria:**
- [ ] Fleet CI workflow exists and can delegate checks to parallel lanes
- [ ] Results from all lanes are aggregated and reported

---

## Dependency Graph

```
Stage 0 (audit) ──→ Stage 1 (baseline) ──→ Stage 2 (path-aware) ──→ Stage 3 (receipt gates)
                                                      │
                                                      ↓
                                            Stage 4 (validate tool)
                                                      │
                                                      ↓
                                            Stage 5 (promotion gate)
                                                      │
                                                      ↓
                                            Stage 6 (nightly audits)
                                                      │
                                                      ↓
                                            Stage 7 (fleet CI)
```

Stage 1 is complete. Stage 2 is the next implementation target. Stage 4 depends on Stage 2 (validate profiles should match path triggers). Stage 5 depends on Stage 4. Stages 6 and 7 are independent of Stages 3–5.

## Recommended First Slice

The highest-value, lowest-risk first implementation is **Stage 1 + stale workflow removal**:

1. Add `uv run python scripts/rig_relay_validate_schemas.py` to the pre-commit job in `ci.yml`
2. Add `uv run pytest tests/coordination/test_schema_validation.py -k test_no_schema_contains_python_syntax -n0` to the pre-commit job
3. Add `uv run pytest tests/tools/test_tool_receipt_emission.py -n0` to the tests job
4. Add `uv lock --check` to the pre-commit job
5. Delete `pylint.yml` and `python-package-conda.yml`

This adds approximately 30 seconds to CI time while closing the three most critical gaps:
- Schema files can no longer be silently corrupted
- Content-light receipt wiring is gated on every PR
- Lockfile drift is detected immediately
- Stale legacy infrastructure is removed
