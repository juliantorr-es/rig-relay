# Test Suite Doctrine

## 1. Purpose

Rig Relay ships a test suite of 5,000+ collected tests. Without a doctrine, the suite accumulates debt: root-level orphan tests, mis-scoped test files buried in `tests/scripts/`, duplicate assertions across files, pycache-dependent collection, and tests that pass on one machine but fail on a clean clone.

This doctrine defines the bar a test must clear to be considered an **asset**. Everything else is **debt** and is quarantined, refactored, or removed on a scheduled migration.

## 2. The Five Asset Rules

> A test is an asset only if it is:
> 1. **Fast enough** for its tier.
> 2. **Scoped** to its source domain.
> 3. **Non-duplicative**.
> 4. **Deterministic** in a clean clone.
> 5. **Named** after the behavior it protects.

A test that fails any rule is **test debt**. Debt tests are not deleted immediately — they are marked, tracked in the relocation manifest, and triaged on a migration schedule (see §11).

## 3. Test Tiers

Every test belongs to exactly one tier. The tier determines runtime budget, execution frequency, and gate status.

| Tier | Marker | Max wall time (per test) | Must pass before |
|---|---|---|---|
| Smoke | `smoke` | 2 s | Demo, share, any push |
| Contract / Unit | (no marker, or `contract`) | 100 ms | CI default, any push |
| Integration | `integration` | 10 s | CI default |
| End-to-end | `e2e` | 120 s | Full-suite scheduled run |
| Packaging | `packaging` | 300 s | Release |
| Network | `network` | — | Full-suite only; opt-in |
| Provider | `provider` | — | Full-suite only; opt-in |
| Destructive | `destructive` | — | Full-suite only; opt-in |
| Slow (intentionally) | `slow` | — | Full-suite only |
| Flaky (known) | `flaky` | — | Quarantine only; never default |
| Legacy (to fix) | `legacy` | — | Quarantine only; never default |

**Runtime budget**: A test that exceeds its tier budget is either moved to a slower tier or refactored.

**Smoke tests** are the fastest confidence check. They must pass cold on every clean clone with zero network, zero credentials, zero pycache. Smoke tests answer: "Is this thing fundamentally broken?"

**Default local suite**: `uv run pytest -m "not slow and not legacy and not flaky and not network and not provider and not destructive"`

**Smoke suite**: `uv run pytest -m smoke`

**Full suite**: `uv run pytest`

## 4. Layout Doctrine

Test paths mirror source paths.

| Source module | Test path |
|---|---|
| `rig_relay/core/tools/validate.py` | `tests/tools/test_validate.py` |
| `rig_relay/ralph/scanner.py` | `tests/ralph/test_scanner.py` |
| `rig_relay/desktop/intents.py` | `tests/desktop/test_intents.py` |

Rules:
- Root-level `tests/test_*.py` files are **debt** unless the tested module has no sub-package (e.g., `rig_relay/*.py` top-level) or the test is on the allowlist.
- `tests/scripts/test_*.py` is **debt** unless the script under test lives in `scripts/`. Tests that map to `rig_relay/desktop/`, `rig_relay/evidence/`, `rig_relay/identity/`, etc. belong in the corresponding domain directory.
- `tests/stubs/` holds test doubles (`Fake*`).
- `tests/fixtures/` holds contract-test golden data.

**Allowlist**: A small number of root-level tests may be acceptable if the tested subject is genuinely cross-cutting (e.g., `tests/test_rig_relay.py` for the top-level entry point). Allowlisted tests are recorded in the relocation manifest with status `allowlisted`.

## 5. Naming Doctrine

A test name must describe the **behavior** or **outcome** it protects. It must not describe implementation trivia.

**Good**:
- `test_collect_git_state_returns_porcelain_sha256_on_clean_repo`
- `test_create_user_returns_403_when_unauthorized`
- `test_scanner_ranks_findings_by_severity_descending`

**Bad**:
- `test_basic`
- `test_works`
- `test_stuff`
- `test_sanity`
- `test_thing`
- `test_validate_1`, `test_validate_2`
- `test_something`

Bad-name tests are flagged by the audit tool and recorded as low-severity debt.

## 6. Determinism Doctrine

A deterministic test passes or fails for the same reason every time on a clean clone. It does not depend on:

1. **Pycache** — no `__pycache__/` reliance. The suite must collect cleanly with `PYTHONDONTWRITEBYTECODE=1`.
2. **Local files** — no hardcoded `/Users/` paths, no `~/.rig/` state from a prior run.
3. **Ambient credentials** — no `os.environ` reads without fixture isolation.
4. **Network** — no outbound HTTP unless marked `network` or `provider`.
5. **Execution order** — no test must rely on side effects from a prior test.
6. **Machine-specific paths** — no `/tmp/` paths that collide across users or runs.
7. **Time** — no bare `time.sleep()` without a reason documented in the test. Use `pytest-timeout` or event-based waiting instead.

**Conftest determinism**: `tests/conftest.py` must exist as a real source file. Tests that `import tests.conftest` must resolve against source, not pycache. The audit tool treats `tests/__pycache__/conftest*.pyc` with no `tests/conftest.py` source as a **critical** failure.

## 7. Duplication Doctrine

A duplicate test asserts the same behavior at the same layer without justification.

**Justified duplicates**:
- A contract test and an integration test may both check "tool X rejects invalid args" if the contract test checks the args model and the integration test checks the full invocation path.
- Different tiers are not duplicates by default.

**Unjustified duplicates** (debt):
- Two test files with the same target module and overlapping assertions.
- Two test functions with the same name in different files that test the same thing.
- A dedicated test file created as a cleaner replacement while the old tests were never removed (e.g., `test_validate_git_state.py` created while git-state tests remained in `test_validate.py`).

**Detection**: The audit tool flags candidate duplicates: same target module imported by multiple files, identical function names across sibling files. Manual review confirms whether they are true duplicates.

## 8. Default Local Suite

The command developers run after every change:

```
uv run pytest -m "not slow and not legacy and not flaky and not network and not provider and not destructive"
```

This excludes:
- Intentionally slow tests
- Known-flaky tests
- Tests requiring external network or provider APIs
- Destructive tests that mutate worktrees
- Legacy tests pending refactor

The default suite must complete in under 5 minutes on a developer machine and must not require network access.

## 9. Full Suite

```
uv run pytest
```

Runs everything. May require network, provider credentials, and a clean worktree. This is a scheduled CI job, not a per-push gate.

## 10. Legacy / Quarantine

Tests marked `legacy` or `flaky` are **quarantined** — they do not run in the default suite. They run only in the full suite or a dedicated quarantine job.

Quarantined tests are recorded in the relocation manifest with a remediation plan. They are either:
- Refactored to meet the five asset rules and re-tiered.
- Deleted if they test dead code, duplicate existing coverage, or can never be made deterministic.
- Permanently marked `flaky` with a documented reason if they test a nondeterministic system boundary that can't be mocked.

## 11. Migration Rules

1. **Do not bulk-move tests in one mission.** Migration is incremental, domain by domain.
2. **Do not delete tests without confirming coverage.** Run the audit tool first; check for the only-copy problem.
3. **Do not merge test files while active development is in progress** on the corresponding source domain (e.g., do not merge Bash tests while RuntimeSupervisor Bash work is active).
4. **When moving a test**, update the relocation manifest row from `pending` to `moved`.
5. **When merging duplicate tests**, remove the redundant file and update the manifest.
6. **When allowlisting a root-level test**, set `status: allowlisted` with a justification.
7. **Never mark a test `legacy` to hide a failure.** Legacy is a migration status, not a dumpster.

## 12. Enforcement

- The test quality audit tool (`scripts/rig_relay_test_quality_audit.py`) produces a machine-readable report in `docs/audits/test-suite/`.
- A report-only architecture test (`tests/architecture/test_test_quality_doctrine.py`) validates the audit tool on synthetic fixtures.
- CI gates (future):
  - **Smoke job**: `uv run pytest -m smoke` — must pass before merge.
  - **Default job**: `uv run pytest -m "not slow and not legacy and not flaky and not network and not provider and not destructive"`
  - **Full scheduled job**: `uv run pytest` — nightly or on-demand.
  - **Quarantine job**: `uv run pytest -m "legacy or flaky"` — informational; does not gate.
- Critical failures (missing conftest source, pycache-only conftest, unregistered markers) **hard-fail** the architecture test. Everything else is debt and does not gate.

## 13. Related Documents

- `docs/governance/usage-data-doctrine.md` — test observability events
- `docs/governance/dependency-policy.md` — test dependency rules
- `docs/audits/test-suite/test_relocation_manifest.jsonl` — migration tracker
- `docs/audits/test-suite/test_quality_report.json` — latest audit results
- `AGENTS.md` § Tests — test tooling and conventions
