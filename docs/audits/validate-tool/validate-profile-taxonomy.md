# Validate Profile Taxonomy

## Profile Principles

Profiles should be stable, narrow, and named by purpose rather than by implementation detail.

## Initial Profiles

### `quick`

Purpose:

- fast sanity check for lane readiness

Command bundle:

- `git status --short --branch`
- focused `ruff check`
- focused `pytest`

Runtime tier:

- low

Use when:

- agent needs a quick pass/fail before deeper work

Proves:

- lane is not obviously broken
- repository state is not obviously dirty beyond policy

Does not prove:

- full suite health
- type correctness
- schema compliance

### `python`

Purpose:

- Python surface sanity

Command bundle:

- `uv run ruff check ...`
- `uv run pyright ...`
- focused `pytest`

Runtime tier:

- medium

Use when:

- validating Python code changes

Proves:

- lint
- type safety
- targeted test coverage

Does not prove:

- schema validation
- governance policy compliance

### `schemas`

Purpose:

- schema and receipt correctness

Command bundle:

- `uv run python scripts/rig_relay_validate_schemas.py`
- `uv run python scripts/rig_relay_validate_tool_receipts.py ...`

Runtime tier:

- low

Use when:

- schemas or receipts changed

Proves:

- schema files parse
- schema files validate
- content-light receipts remain clean

Does not prove:

- runtime behavior
- tool semantics

### `tool-hardening`

Purpose:

- validate deterministic tool envelopes and receipts

Command bundle:

- targeted tool tests
- receipt policy tests
- tool hardening tests

Runtime tier:

- medium

Use when:

- hardening `bash`, `search_replace`, `write_file`, or similar surfaces

Proves:

- structured statuses
- refusal behavior
- receipt emission
- truncation behavior

Does not prove:

- end-to-end promotion readiness

### `receipt-policy`

Purpose:

- prove content-light receipts stay content-light

Command bundle:

- receipt validator
- emission tests

Runtime tier:

- low

Use when:

- any receipt or event payload changes

Proves:

- no raw stdout/stderr
- hashes and counts are present

Does not prove:

- underlying tool correctness

### `governance`

Purpose:

- validate policy and doctrine constraints

Command bundle:

- governance docs checks
- policy scripts
- targeted tests for policy edges

Runtime tier:

- low to medium

Use when:

- governance surfaces or policy-driven tools change

Proves:

- policy conformance
- schema alignment

Does not prove:

- core runtime functionality

### `worktree-readiness`

Purpose:

- determine whether a lane/worktree is clean enough for handoff or aggregation

Command bundle:

- git state collection (automatic in run() method)
- dirty policy enforcement via expected_dirty_policy

Runtime tier:

- low (no lint/test/schema commands)

Use when:

- determining workspace readiness before deeper validation
- enforcing expected_dirty_policy constraints

Proves:

- lane cleanliness
- git state availability
- dirty policy compliance

Does not prove:

- full suite health
- schema compliance
- promotion readiness

Runtime tier:

- medium

Use when:

- deciding whether a patch lane is clean enough for promotion

Proves:

- lane eligibility
- blocker classification

Does not prove:

- fleet-wide health

### `promotion-readiness` (not implemented)

Purpose:

- final gate before promotion

Command bundle:

- quick
- python
- schemas
- governance
- targeted integration tests

Runtime tier:

- high

Use when:

- patch is candidate for promotion or merge

Proves:

- lane is promotable
- blockers are classified

Does not prove:

- future changes outside the lane


## Path Scoping Behavior

All profiles support deterministic path scoping via `ValidateArgs.paths`.

### Path Normalization Rules
- Paths are resolved relative to `workspace_root` (or cwd if None).
- Absolute paths are accepted only if they resolve inside the workspace root.
- `..` traversal outside the workspace root is refused with `unsafe_paths` error.
- Nonexistent paths are refused with a blocked result (`unknown_failure` kind).
- Duplicate paths are de-duplicated deterministically.
- Normalized paths are sorted for stable `command_fingerprint` values.

### Per-Profile Path Behavior

| Profile | Path Behavior |
|---------|--------------|
| `quick` | Adds scoped `ruff check` dynamically when Python paths are provided; non-Python paths do not trigger ruff |
| `python` | Scopes `ruff check` to provided Python-relevant paths; skips ruff when no Python paths provided; leaves `pyright` repo-wide (pyright path scoping is unreliable in this project) |
| `schemas` | Runs schema validation only when paths contain "schema" or are under `docs/schemas/`; skips otherwise |
| `receipt-policy` | Runs receipt policy validation only when paths contain "receipt" or are under receipt-related paths; skips otherwise |
| `tool-hardening` | Scopes `pytest` to provided test paths (under `tests/`); skips pytest when only source paths are provided (no fragile source-to-test inference) |

### Content-Light Receipts
- Path-scoped `affected_paths` in `ValidateCheckResult` and `ValidateCheckReceipt` contain only normalized relative paths.
- No raw file contents, stdout/stderr, or command transcripts in receipts.
- Receipts pass `tool_receipt_policy` validation.

### Pyright Scoping Decision
`pyright` is left repo-wide in all scoped modes. Pyright does not support efficient single-file scoping in this project's configuration, and scoping it would produce unreliable type-check results. This is documented as a known limitation.

### Pytest Scoping Decision
`pytest` is scoped only to paths under `tests/`. Source-only scoped validation does not run pytest unless an explicit test path is provided. No source-to-test inference is implemented (Stage 4+).

## Profile Taxonomy Notes

- `quick` should be the default entry profile.
- `python` should absorb the most common bash validation patterns.
- `schemas` should own schema and receipt checks.
- `tool-hardening` should be used for deterministic tool contract work.
- `promotion-readiness` should stay narrow and policy-heavy.

### `worktree-readiness`

| Attribute | Value |
|-----------|-------|
| **Runtime Tier** | 3 (local preflight) |
| **Command Bundle** | Git state collection only (no test/lint/schema commands) |
| **Timeout** | 30s |
| **Mutation** | Never |
| **Network** | Never |
| **Purpose** | Answer lane readiness purely through git workspace state + dirty policy. No tool invocations. |
| **Use Cases** | Preflight before mutation operations; lane occupancy checks; workspace dirtiness audits. |
| **Path Scoping** | No commands to scope; dirty policy applies to all paths. |
| **Blocker Types** | `dirty_workspace` when `expected_dirty_policy` rejects state. |
