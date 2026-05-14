# CI Path Trigger Map

> **Status**: Design Proposal
> **Date**: 2026-05-17
> **Scope**: Path-based trigger rules for domain-specific CI gates.

## Path Pattern Syntax

All paths are relative to repository root. Patterns use glob-style matching consistent with GitHub Actions `paths:` filters.

## Trigger Map

### Core Python Changes — Tier 1 (always run)

| Path Pattern | Gate(s) |
|-------------|---------|
| `**.py` | Ruff check, Ruff format (via pre-commit), pyright (via pre-commit) |
| `**.pyi` | Ruff check, Ruff format (via pre-commit), pyright (via pre-commit) |
| `pyproject.toml` | Ruff check, Ruff format, pre-commit, uv lock check |
| `uv.lock` | uv lock check, uv sync |

### Schema Changes — Tier 1 (always run when triggered)

| Path Pattern | Gate(s) |
|-------------|---------|
| `docs/schemas/*.json` | Schema validation (validate schemas script), Python contamination regression |
| `docs/schemas/rig.relay.artifact.*.json` | Artifact schema tests |
| `docs/schemas/rig.relay.contribution_*.json` | Telemetry contribution schema tests |
| `docs/schemas/rig.relay.bash_*.json` | Bash hardening tests |
| `docs/schemas/rig.relay.search_replace_*.json` | SearchReplace hardening tests |
| `docs/schemas/rig.relay.tool_receipt_index.v1.json` | Receipt index tests |
| `scripts/rig_relay_validate_schemas.py` | Schema validation gate (self-test) |

### Tool Hardening Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `vibe/core/tools/builtins/bash.py` | Bash hardening tests, tool determinism tests |
| `vibe/core/tools/builtins/search_replace.py` | SearchReplace hardening tests, arity tests, tool determinism tests |
| `vibe/core/tools/builtins/**` | Tool determinism tests |
| `vibe/core/tools/base.py` | Tool determinism tests, validation suite tests |
| `vibe/core/tools/**` | Tool determinism tests, tool contract coverage tests |

### Receipt / Evidence Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `rig_relay/evidence/**` | Receipt policy tests, receipt index tests, evidence tests |
| `rig_relay/evidence/model_observations.py` | Tool receipt emission tests |
| `rig_relay/evidence/tool_receipt_policy.py` | Receipt policy tests |
| `rig_relay/evidence/receipt_index.py` | Receipt index tests |
| `rig_relay/evidence/redaction.py` | Redaction tests |
| `vibe/core/agent_loop.py` | Tool receipt emission tests |
| `vibe/core/telemetry/constants.py` | Tool receipt emission tests |

### Agent Loop / Telemetry Changes — Tier 1 (always run)

| Path Pattern | Gate(s) |
|-------------|---------|
| `vibe/core/agent_loop.py` | Tool receipt emission tests |
| `vibe/core/telemetry/**` | Tool receipt emission tests |

### Coordination Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `rig_relay/coordination/**` | Coordination tests, coordination lease dry-run |
| `tests/coordination/**` | Coordination tests |

### Governance / Policy Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `docs/governance/**` | Governance tests |
| `docs/governance/usage-data-doctrine.md` | Telemetry contribution validation |
| `docs/governance/telemetry-contribution-policy.md` | Telemetry contribution validation |
| `docs/governance/cross-session-coordination.md` | Coordination tests |
| `AGENTS.md` | Conversation summary name tests, governance tests |

### Documentation Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `docs/conversations/*.md` | Conversation summary name tests |
| `docs/audits/**` | Docs tests (if any exist for audit data) |
| `docs/**/*.md` | Docs tests |
| `docs/schemas/*.json` | (See schema changes above) |

### Script Changes — Tier 2

| Path Pattern | Gate(s) |
|-------------|---------|
| `scripts/*.py` | Script tests |
| `scripts/rig_relay_validate_*.py` | Schema validation, receipt policy validation (self-test) |
| `tests/scripts/**` | Script tests |

### CI Workflow Changes — Tier 1 (always run)

| Path Pattern | Gate(s) |
|-------------|---------|
| `.github/workflows/*.yml` | action-validator (via pre-commit) |

### Build / Packaging Changes — Tier 3

| Path Pattern | Gate(s) |
|-------------|---------|
| `pyproject.toml` | uv lock check, build check |
| `uv.lock` | uv lock check, uv sync |
| `pyinstaller/**` | Build check |
| `vibe-acp.spec` | Build check |

### Desktop Cockpit Changes — Tier 4

| Path Pattern | Gate(s) |
|-------------|---------|
| `rig_relay/desktop/**` | Desktop tests (manual only) |
| `tests/desktop/**` | Desktop tests (manual only) |

## Combined Path Logic

When a PR modifies files matching multiple patterns, **all matching Tier 1 and Tier 2 gates run**. For example:

```
PR changes: vibe/core/tools/builtins/bash.py + docs/schemas/rig.relay.bash_receipt.v1.schema.json
Runs:
  Tier 1: full baseline (ruff, pyright, schema validation, receipt emission, lock check)
  Tier 2: bash hardening tests
  Tier 2: tool determinism tests
```

## Anti-Patterns

1. **Don't run Tier 2 on every PR** — path-filtering must prevent this.
2. **Don't duplicate Tier 1 checks in Tier 2** — Tier 1 always runs.
3. **Don't gate on test file changes alone** — test changes without source changes don't need domain-specific gates (full suite will catch them).
4. **Don't use `paths-ignore` where `paths` is clearer** — prefer positive `paths:` over negative `paths-ignore:`.
