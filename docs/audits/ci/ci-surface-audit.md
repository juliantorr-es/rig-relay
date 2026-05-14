# CI Surface Audit

> **Status**: Established
> **Date**: 2026-05-17 (updated Stage 1 implementation)
> **Branch**: main
> **HEAD**: 384e486
> **Scope**: Full inventory of CI, validation, lint, typecheck, schema, receipt, governance, build, and coordination surfaces.
> **Stage 1 complete**: 4 missing Tier 1 gates added to ci.yml; 2 stale workflows removed.

## Executive Summary

Rig Relay has accumulated substantial governance and determinism infrastructure but **no dedicated CI surface design**. Current CI is inherited from mistral-vibe: a single `ci.yml` that runs pre-commit hooks + full pytest suite, plus several stale legacy workflows. New governance subsystems (schemas, receipts, tool hardening, coordination, evidence) have no dedicated CI gating — they only run as undifferentiated parts of the full test suite.

**Key findings:**

1. **Two stale legacy workflows** (`pylint.yml`, `python-package-conda.yml`) run on every push against ancient Python versions using pip/conda — completely redundant with ruff in pre-commit.
2. **Schema validation is absent from CI** — 74 JSON schema files are only validated ad-hoc.
3. **Content-light receipt policy has no CI gate** — the validator exists but isn't automated.
4. **Full pytest suite is slow** (~361 test files) and runs on every PR without path-based scoping.
5. **No `uv lock --check` or `uv sync --locked --dry-run`** in CI — lockfile drift is undetected.
6. **No dirty-workspace check** — the AGENTS.md rules are behavioral, not automated.
7. **Coordination lease health** — no automated stale-lease detection.
8. **validate-tool profiles** exist as design artifacts but have zero CI backing.

## Existing CI Workflows

| Workflow | Trigger | What it does | Health |
|----------|---------|-------------|--------|
| `ci.yml` | PR to main, push to main | pre-commit (ruff, pyright, typos, action-validator, TOML/YAML, whitespace) + full pytest (--ignore tests/snapshots) + snapshot tests | Healthy primary gate |
| `build-and-upload.yml` | Release, PR to main, dispatch | Build platform binaries (PyInstaller + Nix) across 5 platforms, smoke test, attach to release | Healthy for builds |
| `release.yml` | Release, dispatch | Publish to PyPI and Zed extension store | Healthy for releases |
| `issue-labeler.yml` | Issue opened | Auto-label issues by component | Working |
| `pylint.yml` | ~~Any push~~ | ~~pylint on Python 3.8–3.10 with pip~~ | **REMOVED (Stage 1)** |
| `python-package-conda.yml` | ~~Any push~~ | ~~conda + flake8 on Python 3.10~~ | **REMOVED (Stage 1)** |

## Validation Script Inventory

| Script | Purpose | CI Coverage | Priority |
|--------|---------|-------------|----------|
| `scripts/rig_relay_validate_schemas.py` | Validate all JSON schemas parse and have no Python contamination | **None** | Critical |
| `scripts/rig_relay_validate_tool_receipts.py` | Validate content-light receipt policy on JSONL files | **None** | High |
| `scripts/rig_relay_validate_telemetry_bundle.py` | Validate telemetry bundle structure | **None** | Medium |
| `scripts/rig_relay_cleanup_coordination_leases.py --dry-run` | Detect stale coordination leases | **None** | Low |

## Check Inventory Summary

See `ci-check-inventory.jsonl` for the full 41-record inventory.

### By Category

| Category | Count | Key Checks |
|----------|-------|------------|
| unit_tests | 2 | Full suite, focused path-based |
| linting | 4 | ruff check, ruff format, pre-commit, pylint (stale) |
| typechecking | 1 | pyright |
| schema_validation | 4 | schema parseability, artifact schemas, telemetry contribution schemas, Python contamination |
| receipt_policy | 5 | receipt policy validator, receipt index, emission tests, evidence tests, redaction |
| tool_hardening | 3 | bash hardening, search_replace hardening, determinism contracts |
| coordination | 2 | coordination tests, lease verify |
| governance | 6 | governance tests, docs tests, JSONL parseability, worktree script safety, AGENTS.md consistency, generated docs drift |
| integration_tests | 3 | script tests, CLI smoke, desktop cockpit |
| package_build | 3 | build-and-upload, pyproject health, uv lock check |
| git_hygiene | 2 | dirty workspace check, amend check |
| meta | 2 | issue labeler, CI self-check (action-validator) |
| REMOVE | 2 | pylint stale, conda stale |

### By Cost Tier

| Tier | Count | Notes |
|------|-------|-------|
| fast | 23 | Read-only, sub-5-second typical |
| medium | 9 | Read-only, 5–30 seconds |
| slow | 6 | >30 seconds or parallel-heavy |
| REMOVE | 2 | Stale workflows |

### By Current CI Coverage

| Coverage | Count |
|----------|-------|
| PR required via ci.yml/pre-commit | 12 |
| PR required via separate CI job | 2 (full tests, snapshot tests) |
| On release/delivery | 3 (build, release, labeler) |
| **None** | **24** |

**Stage 1 added 4 new CI gates. 18 of 41 checks now have CI coverage. 20 checks remain unautomated.**

## Key Gaps

### Critical — resolved in Stage 1
1. ✅ Schema validation (validate schemas script + Python contamination regression test) — added to ci.yml pre-commit job
2. ✅ Tool receipt emission tests (core agent loop wiring) — added to ci.yml tests job
3. ✅ `uv lock --check` (lockfile consistency) — added to ci.yml pre-commit job
4. ❌ Still open: Focused unit tests on changed paths (instead of full suite) — deferred to Tier 2

### High — missing from domain-specific gates
5. Receipt policy validator in CI
6. Bash hardening tests on bash changes
7. SearchReplace hardening tests on search_replace changes
8. Evidence tests on evidence changes
9. Coordination tests on coordination changes

### Stale / Redundant
10. ✅ `pylint.yml` — REMOVED (Stage 1)
11. ✅ `python-package-conda.yml` — REMOVED (Stage 1)

### Remaining missing infrastructure
12. ❌ No JSONL parseability check for audit data files
13. ❌ No dirty workspace check in CI
14. ❌ No coordination lease health check
15. ❌ No generated docs drift detection

## Risk Assessment

| Risk | Checks Affected | Impact |
|------|----------------|--------|
| Schema corruption not caught in CI | schema-validation, schema-python-contamination | Schema files could be silently broken |
| Content-light policy regression | receipt-policy-validation, tool-receipt-emission-tests | Raw output could leak into telemetry |
| Tool hardening regression | bash-hardening-tests, searchreplace-hardening-tests | Deterministic envelope could break |
| Lockfile drift | uv-lock-check, pyproject-uv-health | Dependency conflicts at build time |
| Coordination state corruption | coordination-tests, coordination-lease-verify | Cross-session coordination failures |
| Full suite cost | unit-tests-full | Slows PR feedback loop unnecessarily |

## Out-of-Scope Findings

See `docs/findings/out-of-scope-findings.jsonl` for findings recorded during this audit.
