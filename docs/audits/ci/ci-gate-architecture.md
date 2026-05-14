# CI Gate Architecture

> **Status**: Design Proposal
> **Date**: 2026-05-17
> **Scope**: Tiered gate architecture for Rig Relay CI.

## Principles

1. **Fast feedback first** — the cheapest gate that catches a regression should run first.
2. **Path-aware gating** — only run domain-specific checks when relevant paths change.
3. **Read-only by default** — mutation (build, publish) is explicitly gated behind promotion or manual triggers.
4. **Content-light** — CI artifacts (logs, receipts) must not contain raw source code or secrets.
5. **Validate-tool alignment** — each CI gate should map to a future `validate` profile.
6. **No dual gating** — avoid running duplicate checks (e.g. ruff via pre-commit AND via standalone command).

## Tier Definitions

### Tier 0 — Local Smoke / Preflight

- Fast (<5s), read-only
- Used by agents before handoff, by developers before commit
- Future `validate quick` profile

**Checks:**
- `git status --short --branch` — dirty state awareness
- `uv run ruff check --fix <changed-files>` — focused lint
- `uv run pytest -n0 <changed-test-files>` — focused unit tests
- `uv lock --check` — lockfile consistency (fast)

**CI coverage:** None (local-only). Agents implement manually.

### Tier 1 — PR Required Baseline

- Deterministic, read-only (except forced formatting), moderate cost
- **Must pass for PR merge.** If any Tier 1 check fails, PR is blocked.
- Runs on **every PR to main** (not path-filtered).

**Checks:**
| Check | Command | Cost | CI Coverage Today |
|-------|---------|------|-------------------|
| Ruff check + format | `uv run pre-commit run --all-files` (ruff hooks) | Fast | ✅ (ci.yml pre-commit job) |
| Pyright typecheck | via pre-commit hook | Medium | ✅ (ci.yml pre-commit job) |
| TOML/YAML validity | via pre-commit hooks | Fast | ✅ (ci.yml pre-commit job) |
| Workflow YAML validation | action-validator via pre-commit | Fast | ✅ (ci.yml pre-commit job) |
| Schema validation | `uv run python scripts/rig_relay_validate_schemas.py` | Fast | ❌ Missing |
| Schema Python contamination | `uv run pytest tests/coordination/test_schema_validation.py -k test_no_schema_contains_python_syntax -n0` | Fast | ❌ Missing |
| Tool receipt emission | `uv run pytest tests/tools/test_tool_receipt_emission.py -n0` | Fast | ❌ Missing |
| uv lock consistency | `uv lock --check` | Fast | ❌ Missing |
| CLI smoke | `uv run rig-relay --help && uv run rig-relay-acp --help` | Fast | ✅ (ci.yml) |
| Typos check | via pre-commit hook | Fast | ✅ (ci.yml pre-commit job) |

**Not in Tier 1:** Full pytest suite, snapshot tests, build checks — too slow or environment-sensitive.

### Tier 2 — Domain-Specific Required Gates

- Run **only when relevant paths change** (see `ci-path-trigger-map.md`)
- Required for PR merge when triggered
- Moderate cost (5–30 seconds)

| Gate | Command | Path Trigger |
|------|---------|-------------|
| Bash hardening | `uv run pytest tests/tools/test_bash_hardening.py tests/tools/test_bash.py -n0` | `vibe/core/tools/builtins/bash.py`, `docs/schemas/rig.relay.bash_*` |
| SearchReplace hardening | `uv run pytest tests/tools/test_hardened_tools.py tests/tools/test_arity.py -n0` | `vibe/core/tools/builtins/search_replace.py`, `docs/schemas/rig.relay.search_replace_*` |
| Tool determinism | `uv run pytest tests/tools/test_determinism.py -n0` | `vibe/core/tools/**` |
| Receipt policy | `uv run pytest tests/evidence/ -n0` | `rig_relay/evidence/**` |
| Coordination | `uv run pytest tests/coordination/ -n0` | `rig_relay/coordination/**` |
| Governance tests | `uv run pytest tests/governance/ -n0` | `docs/governance/**`, `rig_relay/**` |
| Evidence tests | `uv run pytest tests/evidence/ -n0` | `rig_relay/evidence/**` |
| Script tests | `uv run pytest tests/scripts/ -n0` (filter network-dependent) | `scripts/**`, `tests/scripts/**` |
| Artifact schema tests | `uv run pytest tests/schemas/ -n0` | `docs/schemas/rig.relay.artifact.*` |
| Telemetry schema tests | `uv run pytest tests/scripts/test_telemetry_contribution_schemas.py -n0` | `docs/schemas/rig.relay.contribution_*` |
| Docs tests | `uv run pytest tests/docs/ -n0` | `docs/**` |
| Conversation summary names | `uv run pytest tests/docs/test_conversation_summary_names.py -n0` | `docs/conversations/**` |
| Coordination schema validation | `uv run pytest tests/coordination/test_schema_validation.py -n0` | `docs/schemas/*`, `rig_relay/coordination/**` |

### Tier 3 — Promotion Readiness

- Broader gate before promotion/merge to main
- Includes all Tier 1 + Tier 2 (scoped) + additional coverage
- Future `validate promotion-readiness` profile

**Additional checks beyond Tiers 1+2:**
- Full pytest suite (except snapshots, network-dependent)
- Snapshot tests (separate job, continue-on-error)
- Dirty workspace check (`git status --porcelain`)
- `uv sync --locked` (not just lock check)
- Build check: `uv build` (dry-run)

**Current CI coverage:** Full pytest (❌ not path-scoped), snapshot tests (✅ separate job). Build and dirty-workspace checks missing.

### Tier 4 — Nightly / Manual Deep Audit

- Expensive or environment-sensitive checks
- No PR blocking
- Run on schedule or manual dispatch

| Check | Frequency | Reason |
|-------|-----------|--------|
| Stale coordination lease audit | Nightly | Read-only, detects lease leaks |
| Full platform build matrix | Nightly or pre-release | Time-consuming (5 platforms) |
| Snapshot regeneration check | Nightly | Snapshot drift detection |
| Generated docs drift | Nightly | Detect stale audit data |
| Desktop cockpit tests | Manual | Environment-dependent (display server) |
| Cross-platform smoke tests | Pre-release | Requires build artifacts |
| PyPI release | Manual (release trigger) | Mutation/write operation |

## Migration from Current CI

### Keep as-is (healthy):
- `ci.yml` pre-commit job — add schema validation and receipt emission tests to it
- `ci.yml` snapshot-tests job — works as Tier 3
- `build-and-upload.yml` — healthy, stays as Tier 4
- `release.yml` — healthy, stays as manual
- `issue-labeler.yml` — healthy, stays as operational

### Add (new gates):
- Schema validation step to `ci.yml` pre-commit job
- Schema Python contamination step to `ci.yml` pre-commit job
- Tool receipt emission test step to `ci.yml` tests job
- `uv lock --check` step to `ci.yml` pre-commit job
- Path-aware domain-specific gates (Tier 2) as conditional jobs in `ci.yml`

### Remove (stale):
- `pylint.yml` — remove entire workflow
- `python-package-conda.yml` — remove entire workflow

### Consider:
- Restructure `ci.yml` from single `tests` job to path-filtered matrix jobs

## Cost Budget

| Tier | Estimated CI cost per PR |
|------|------------------------|
| Tier 0 (local) | 0 CI minutes |
| Tier 1 (baseline) | ~1–2 minutes |
| Tier 2 (if triggered) | ~30s–2 minutes per triggered gate |
| Tier 3 (promotion) | ~5–10 minutes |
| Tier 4 (nightly) | ~20–30 minutes total |

## Guard Against CI Overload

1. **Cap Tier 2 gates to 3 parallel jobs max** — avoid runner starvation
2. **Tier 1 must complete within 3 minutes** — if slower, split or optimize
3. **Network-dependent tests** (Google Drive, desktop) are never PR-blocking
4. **Snapshot tests are advisory only** — they use `continue-on-error` already
5. **Validate profiles should reuse CI gate definitions**, not duplicate them
