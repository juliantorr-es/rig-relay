# CI–Validate Alignment

> **Status**: Design Proposal
> **Date**: 2026-05-17
> **Scope**: Mapping between CI gate tiers and future `validate` tool profiles.

## Principle

Every CI gate should have a corresponding `validate` profile so that:
- Agents can run the same checks locally via `validate <profile>` that CI runs remotely.
- The `validate` tool becomes the single source of truth for check definitions.
- CI workflow files become thin wrappers that call `validate` profiles.

## Profile Mapping

### Validate Profile → CI Gate Tier

| Validate Profile | CI Tier | CI Gate(s) | Notes |
|-----------------|---------|-------------|-------|
| `quick` | Tier 0 | Local smoke (git status, focused ruff, focused pytest, lock check) | Agents use before handoff. Not in CI. |
| `python` | Tier 1 | Ruff, pyright, focused unit tests | Core Python surface. Runs via pre-commit today. |
| `schemas` | Tier 1 | Schema validation script, Python contamination regression | Should be in every PR baseline. |
| `schemas` (extended) | Tier 2 | Artifact schemas, telemetry contribution schemas | Path-triggered on schema changes. |
| `receipt-policy` | Tier 1 | Tool receipt emission tests | Core agent loop wiring — always run. |
| `receipt-policy` (extended) | Tier 2 | Receipt index tests, evidence tests, redaction tests | Path-triggered on evidence changes. |
| `tool-hardening` | Tier 2 | Bash hardening, SearchReplace hardening, determinism tests | Path-triggered on tool changes. |
| `governance` | Tier 2 | Governance tests, docs tests, conversation names | Path-triggered on governance/doc changes. |
| `worktree-readiness` | Tier 3 | Dirty workspace check, coordination tests, script tests | Pre-promotion check. |
| `promotion-readiness` | Tier 3 | All Tiers 1+2 scoped + full suite + uv sync + build | Final gate before merge. |

### CI Gate → Validate Profile (reverse map)

| CI Gate | Validate Profile | Ownership |
|---------|-----------------|-----------|
| Ruff check | `python` (part of) | Built-in |
| Pyright | `python` (part of) | Built-in |
| Schema validation | `schemas` | Built-in |
| Schema Python contamination | `schemas` | Built-in |
| Tool receipt emission | `receipt-policy` | Built-in |
| uv lock check | `python` (part of) | Built-in |
| CLI smoke | `quick` (part of) | Built-in |
| Bash hardening | `tool-hardening` | Domain |
| SearchReplace hardening | `tool-hardening` | Domain |
| Tool determinism | `tool-hardening` | Domain |
| Receipt policy validation | `receipt-policy` | Domain |
| Coordination tests | `worktree-readiness` | Domain |
| Evidence tests | `receipt-policy` | Domain |
| Script tests | `worktree-readiness` | Domain |
| Governance tests | `governance` | Domain |
| Docs tests | `governance` | Domain |
| Full pytest suite | `promotion-readiness` | Domain |
| Snapshot tests | `promotion-readiness` | Domain |
| Dirty workspace check | `worktree-readiness` | Built-in |
| Build check | `promotion-readiness` | Built-in |

## What CI Should Do Now vs What Validate Should Own Later

### CI owns now (before validate tool exists):

1. Orchestrate pre-commit hooks (ruff, pyright, typos, formatting)
2. Run focused test files as separate CI jobs
3. Run validation scripts as CI steps
4. Enforce path-based gating via `paths:` filters
5. Run full pytest suite as promotion gate
6. Build and publish artifacts
7. Check uv lock consistency

### Validate should own later (after validate tool is implemented):

1. Define check commands and profiles in a registry (not in CI YAML)
2. Run the same checks locally and in CI
3. Emit content-light receipts for each check
4. Classify blockers (test_failure, lint_failure, schema_failure, etc.)
5. Support `--check-only` (CI mode) and `--fix` (local mode) variants
6. Consolidate duplicate check commands across scripts

### Migration Path

```
Stage 0-1 (today):             CI YAML defines all commands directly
Stage 2 (CI refactor):         CI YAML calls validate profiles
Stage 3 (validate maturity):   validate tool has profile registry, CI is thin wrapper
```

## Consolidation Opportunities

The following duplicate or overlapping commands should eventually consolidate under `validate`:

| Current | Redundant With | Consolidate Into |
|---------|---------------|-----------------|
| `scripts/rig_relay_validate_schemas.py` | `tests/coordination/test_schema_validation.py::test_no_schema_contains_python_syntax` | `validate schemas` |
| `scripts/rig_relay_validate_tool_receipts.py` | `tests/evidence/test_tool_receipt_policy.py` | `validate receipt-policy` |
| `scripts/rig_relay_validate_telemetry_bundle.py` | Manual testing only | `validate schemas` or `validate governance` |
| `pylint.yml` (stale) | `ruff` via pre-commit | Remove, no consolidation needed |
| `python-package-conda.yml` (stale) | `ruff` via pre-commit | Remove, no consolidation needed |

## Validate Profile Definitions (for CI wiring)

When the validate tool is implemented, each profile should map to these commands:

### `validate quick`
```yaml
steps:
  - git status --short --branch
  - uv run ruff check --fix <changed-files>
  - uv run pytest -n0 <changed-test-files>
  - uv lock --check
```

### `validate python`
```yaml
steps:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pyright
```

### `validate schemas`
```yaml
steps:
  - uv run python scripts/rig_relay_validate_schemas.py
  - uv run pytest tests/coordination/test_schema_validation.py -k test_no_schema_contains_python_syntax -n0
  - uv run pytest tests/schemas/ -n0
  - uv run pytest tests/scripts/test_telemetry_contribution_schemas.py -n0
```

### `validate receipt-policy`
```yaml
steps:
  - uv run pytest tests/tools/test_tool_receipt_emission.py -n0
  - uv run pytest tests/evidence/ -n0
```

### `validate tool-hardening`
```yaml
steps:
  - uv run pytest tests/tools/test_bash_hardening.py tests/tools/test_bash.py -n0
  - uv run pytest tests/tools/test_hardened_tools.py tests/tools/test_arity.py -n0
  - uv run pytest tests/tools/test_determinism.py -n0
```

### `validate governance`
```yaml
steps:
  - uv run pytest tests/governance/ -n0
  - uv run pytest tests/docs/ -n0
```

### `validate worktree-readiness`
```yaml
steps:
  - git status --porcelain
  - uv run pytest tests/coordination/ -n0
  - uv run pytest tests/scripts/ -n0 (filtered)
  - uv run pytest tests/tools/ -n0 (targeted tool tests)
```

### `validate promotion-readiness`
```yaml
steps:
  - validate quick
  - validate python
  - validate schemas
  - validate receipt-policy
  - validate governance
  - uv run pytest --ignore tests/snapshots
  - uv run pytest tests/snapshots (continue-on-error)
  - uv sync --locked
  - uv build
```
