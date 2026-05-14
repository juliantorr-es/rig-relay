# Bash Usage Audit for Validate Design

## Scope

This audit synthesizes existing bash hardening evidence, tool-usage aggregates, validator scripts, and test surfaces to design a deterministic `validate` tool. It does not implement `validate`.

## Evidence Sources

- `docs/audits/tool-usage-analysis/tool-usage-summary.md`
- `docs/audits/tool-usage-analysis/tool-usage-aggregates.json`
- `docs/audits/tool-hardening/bash-deterministic-envelope.md`
- `docs/audits/tool-hardening/search-replace-patch-contract.md`
- `scripts/rig_relay_validate_schemas.py`
- `scripts/rig_relay_validate_tool_receipts.py`
- `tests/tools/test_bash.py`
- `tests/tools/test_bash_hardening.py`
- `tests/tools/test_validation_suite.py`
- `tests/tools/test_tool_receipt_emission.py`

## What the Current Data Says

The local tool-usage audit shows bash is the dominant high-authority command surface.

| Metric | Value |
|---|---:|
| Calls | 5,023 |
| Failures | 337 |
| Failure rate | 6.71% |
| p95 latency | 10,469 ms |
| p95 output | 8,012 bytes |

The strongest empirical signal is not raw command text. It is command family pressure:

- validation commands are frequent and already script-shaped
- inspection commands are frequent and mostly read-only
- Git introspection is common and high-authority
- schema and receipt validation already exist as standalone scripts
- mutation commands are already separated by tool boundaries, so bash should not become a general mutation gateway

## Command Categories

### Validation / Test Execution

Observed command family:

- `uv run pytest`
- `uv run pytest tests/...`
- `uv run pytest -n0 ...`
- `uv run pyright ...`
- `uv run ruff check ...`
- `uv run ruff format ...`
- `uv run ruff format --check ...`
- `uv run python scripts/rig_relay_validate_schemas.py`
- `uv run python scripts/rig_relay_validate_tool_receipts.py ...`

Empirical role:

- high frequency in this repo
- deterministic enough to model as first-class validate profiles
- mostly read-only, with clear pass/fail semantics

Recommendation:

- absorb into `validate`
- keep bash fallback for ad hoc or one-off command composition

### Git Introspection

Observed command family:

- `git status`
- `git diff`
- `git log`
- `git show`
- `git ls-files`
- `git branch`

Empirical role:

- read-only but high leverage
- used for promotion/readiness and dirty-state checks
- should be deterministic and content-light

Recommendation:

- absorb into `validate` for readiness checks
- later migrate to a dedicated deterministic Git-read surface if needed

### File / Content Inspection

Observed command family:

- `rg ...`
- `find ...`
- `ls ...`
- `sed ...`
- `jq ...`
- `du ...`
- `stat ...`

Empirical role:

- common inspection layer
- low mutation risk
- useful for audits and repository discovery

Recommendation:

- keep bash for ad hoc inspection
- absorb only repeatable read-only checks into `validate`

### Report / Dataset Generation

Observed command family:

- `uv run python scripts/rig_relay_*.py`
- validation and export scripts

Empirical role:

- deterministic pipeline steps
- often depends on a known repo root or evidence root

Recommendation:

- absorb fixed report-generation checks into `validate`
- keep free-form report generation in bash when it is exploratory

### Mutation / Destructive / Refused Commands

Observed command family:

- repo mutation commands
- file edits
- Git write operations
- cleanup / pruning / archive operations

Empirical role:

- should not be the default validate target
- usually need a separate governed tool or explicit mutation surface

Recommendation:

- exclude from `validate` by default
- gate via explicit mutation profiles if they ever become eligible

## Validate Absorption Rules

`validate` should absorb commands when all are true:

- command is deterministic or close to deterministic
- exit code is enough to decide pass/fail
- output can be summarized content-light
- command is read-only or check-only
- the command is a repeated workflow primitive, not a one-off exploration

`validate` should stay out of bash when any are true:

- command is exploratory or ad hoc
- command is interactive
- command depends on arbitrary shell expansion
- command mutates state
- command needs raw stdout as the main product

## Gaps in Current Data

- raw bash command text is not preserved in the content-light observability stream
- exact command-family counts are therefore partially inferred from validator scripts and hardening docs
- failure classification for bash commands is still mostly external to the command text
- no canonical `command_kind` field exists yet

## Conclusion

The strongest `validate` candidates are:

1. `pytest`
2. `pyright`
3. `ruff check`
4. schema validation scripts
5. receipt-policy validation scripts
6. git cleanliness / readiness checks

These are the commands most likely to benefit from deterministic profiles, structured receipts, and blocker taxonomy.
