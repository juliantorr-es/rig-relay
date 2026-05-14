# Validate Tool Contract

## Purpose

`validate` is a deterministic, read-only validation surface for repeated command families that currently run through bash.

It answers:

- did the lane pass?
- what failed?
- is the failure code, environment, or workspace state?
- is the patch or lane eligible for promotion?

It is not a general shell wrapper.

## Proposed Models

### ValidateArgs

| Field | Type | Notes |
|---|---|---|
| `profile` | `str` | Required named validation profile |
| `scope` | `str | None` | Optional mission scope label |
| `paths` | `list[str]` | Optional path scope |
| `workspace_root` | `str | None` | Working root for deterministic resolution |
| `timeout_seconds` | `int | None` | Per-profile override |
| `check_only` | `bool` | Default `true` |
| `allow_network` | `bool` | Default `false` |
| `allow_mutation` | `bool` | Default `false` |
| `env_profile` | `str | None` | Restricted env profile |
| `expected_dirty_policy` | `str | None` | `clean`, `allow_dirty`, `allow_listed_dirty` |
| `output_cap_bytes` | `int | None` | Output cap before truncation |

### ValidateCheckResult

| Field | Type | Notes |
|---|---|---|
| `check_id` | `str` | Stable check identifier |
| `command_kind` | `str` | `pytest`, `ruff`, `pyright`, `git`, `schema`, `policy`, `custom` |
| `command_display` | `str | None` | Human-readable command summary, not raw transcript |
| `command_fingerprint` | `str | None` | Hash of normalized command |
| `status` | `str` | `passed`, `failed`, `skipped`, `blocked`, `timed_out`, `refused` |
| `exit_code` | `int | None` | Tool exit code when present |
| `duration_ms` | `float | None` | Measured runtime |
| `stdout_sha256` | `str | None` | Content-light output hash |
| `stderr_sha256` | `str | None` | Content-light output hash |
| `stdout_bytes` | `int | None` | Byte count |
| `stderr_bytes` | `int | None` | Byte count |
| `stdout_truncated` | `bool` | Default `false` |
| `stderr_truncated` | `bool` | Default `false` |
| `parsed_summary` | `dict | None` | Optional structured summary |
| `failure_kind` | `str | None` | Blocker kind |
| `affected_paths` | `list[str]` | Optional hash-safe path list |

### ValidateResult

| Field | Type | Notes |
|---|---|---|
| `status` | `str` | `passed`, `failed`, `blocked`, `refused`, `timed_out` |
| `profile` | `str` | Echoed input profile |
| `scope` | `str | None` | Echoed input scope |
| `command_count` | `int` | Total commands run |
| `passed_count` | `int` | Count of passing checks |
| `failed_count` | `int` | Count of failing checks |
| `skipped_count` | `int` | Count of skipped checks |
| `duration_ms` | `float | None` | Total elapsed time |
| `checks` | `list[ValidateCheckResult]` | One row per check |
| `blocker_summary` | `dict[str, int]` | Blocker counts by type |
| `changed_files` | `list[str] | None` | Only when the profile explicitly allows it |
| `before_git_state` | `ValidateGitState | None` | Optional pre-state git snapshot |
| `after_git_state` | `ValidateGitState | None` | Optional post-state git snapshot |
| `error_kind` | `str | None` | Final error category |
| `refusal_reason` | `str | None` | Human-readable refusal summary |

### ValidateReceipt

Content-light only.

Required fields:

- profile
- status
- timestamp
- duration_ms
- blocker_summary
- check counts
- per-check hashes and byte counts
- validator schema version

Forbidden fields:

- raw stdout
- raw stderr
- raw prompts
- raw command transcripts
- raw args bodies
- raw file contents

## Path Representation Policy

`validate` uses workspace-relative POSIX paths for all long-lived evidence and
exposed outputs. Absolute paths are used only internally for containment safety
checks and are never leaked into argv, fingerprints, affected_paths, or receipts.

| Layer | Path form | Why |
|---|---|---|
| Input (`args.paths`) | User-provided (any form) | Natural interface |
| Containment check | Absolute resolved | Safety: detect traversal and outside-root |
| Exposed scoped paths | Workspace-relative POSIX | Stable fingerprints, portable receipts |
| Command argv | Relative (from workspace_root) | Valid because subprocess cwd = workspace_root |
| `command_fingerprint` | SHA256 of relative-path argv | Machine-independent |
| `affected_paths` | Workspace-relative | Receipt portability |
| ValidateReceipt | Workspace-relative | Cross-machine evidence compatibility |

Why this matters for future worktrees and lane validation:
- Worktrees have different absolute paths. Relative paths make fingerprints,
  receipts, and evidence comparable across worktrees without re-hashing.
- Lane validation compares validation evidence from multiple sessions. Absolute
  paths would break comparison.
- Cross-machine evidence (CI, remote agents) requires location-independent paths.

## Contract Rules

1. Deterministic by default.
2. Read-only by default.
3. Mutation disabled unless a profile explicitly opts in.
4. Network disabled unless a profile explicitly opts in.
5. Raw output forbidden from receipts.
6. Raw output in result objects must be capped, summarized, and hashable.
7. Profile must imply command bundle and success criteria.
8. Exit code alone is not enough; blocker taxonomy must be produced.

## Stage 2 Implementation Status ✅

Stage 2 (Content-Light ValidateReceipt) is implemented in
`vibe/core/tools/builtins/validate.py` with 11 new receipt tests in
`tests/tools/test_validate.py` and 5 validate index tests in
`tests/evidence/test_receipt_index.py`.

Receipt models:
- `ValidateCheckReceipt`: content-light per-check receipt (no raw stdout/stderr)
- `ValidateReceipt`: top-level receipt with profile, status, counts, blocker_summary, check_receipts
- `Validate.build_receipt(result)`: duck-typed method deriving receipt from result

New schema: `docs/schemas/rig.relay.validate_receipt.v1.schema.json` (78/78 validated)

Receipt index updated: `rig_relay/evidence/receipt_index.py` handles validate tool

Total: 48 validate tests + 37 receipt index tests, all passing


## Stage 3 Implementation Status ✅

Stage 3 (Path-Scoped Validation Profiles) is implemented in
`vibe/core/tools/builtins/validate.py` with 71 tests in
`tests/tools/test_validate.py`.

Key design decisions:
- argv-based subprocess execution (`asyncio.create_subprocess_exec`), no shell
- path normalization via `_normalize_validate_paths()`: de-duplicates, sorts, refuses nonexistent/outside-workspace paths
- path scoping via `_scope_check_argv()`: filters paths by domain (Python paths for ruff, test paths for pytest, schema/receipt paths for domain checks)
- `ruff` is scoped to Python-relevant paths only; non-Python paths skip ruff
- `pytest` is scoped to paths under `tests/` only; source-only paths skip pytest
- `pyright` is left repo-wide (unreliable single-file scoping in this project)
- `schemas` runs only when paths contain "schema" or `docs/schemas/`
- `receipt-policy` runs only when paths contain "receipt"
- `quick` profile adds scoped `ruff check` dynamically when Python paths provided
- `tool-hardening` scopes pytest to test paths only
- unsafe paths (outside workspace, nonexistent) are refused with structured result
- affected_paths populated on scoped checks; preserves content-light receipts
- output is capped (default 65KB, max 512KB), hashed (SHA256), and byte-counted
- raw output is included in check results for debugging but capped
- blocker taxonomy maps exit codes to structured kinds
- profile registry is a simple dict in the module, not a database
- content-light enforced via `extra="forbid"` on all result models
- `command_fingerprint` provides stable identity for normalized argv

Supported profiles: `quick` (scoped), `python` (scoped), `schemas` (domain-filtered), `receipt-policy` (domain-filtered), `tool-hardening` (scoped)


## Output Policy

- `stdout` and `stderr` may exist only in the immediate result path.
- receipts must contain only hashes, counts, and summaries.
- parsed summaries are allowed only when the parser is profile-specific and deterministic.

## Deterministic Result Envelope

`validate` should normalize every check into:

- what ran
- what kind of check it was
- how long it ran
- whether it passed
- what blocker kind, if any, it produced
- whether the check touched files or the workspace
- whether the output was truncated

## Stage 5 Implementation Status ✅

Stage 5 (Worktree/Lane Awareness and Dirty-State Policy) is implemented in
`vibe/core/tools/builtins/validate.py` with 27 new tests in
`tests/tools/test_validate_git_state.py`.

### ValidateGitState Fields

| Field | Type | Notes |
|---|---|---|
| `branch` | `str | None` | Current git branch |
| `head` | `str | None` | Full SHA of HEAD |
| `is_git_repo` | `bool` | Whether cwd is inside a git worktree |
| `is_worktree` | `bool` | Whether HEAD is detached (branch is None) |
| `upstream` | `str | None` | Upstream tracking branch |
| `ahead_count` | `int` | Commits ahead of upstream |
| `behind_count` | `int` | Commits behind upstream |
| `dirty_count` | `int` | Total dirtied paths |
| `modified_count` | `int` | Working tree modifications |
| `deleted_count` | `int` | Working tree deletions |
| `untracked_count` | `int` | Untracked files |
| `staged_count` | `int` | Staged changes |
| `conflicted_count` | `int` | Conflicted files |
| `dirty_paths` | `list[str]` | Workspace-relative POSIX paths |
| `untracked_paths` | `list[str]` | Workspace-relative POSIX paths |
| `changed_paths` | `list[str]` | All changed paths (dirty + untracked) |
| `status_porcelain_sha256` | `str | None` | SHA256 hash of raw git status output |
| `error_kind` | `str | None` | Error category if git state collection failed |
| `refusal_reason` | `str | None` | Human-readable failure reason |

### expected_dirty_policy Behavior

| Policy | Behavior |
|--------|----------|
| `None` or not set | No dirty-state enforcement |
| `allow_dirty` | Passes regardless of dirty files |
| `clean` | Blocks/fails if any dirty files exist (dirty_count > 0 or conflicted_count > 0) |
| `allow_listed_dirty` | Allows dirty paths listed in `ValidateArgs.paths`; blocks if unlisted dirty paths exist |

Dirty-policy enforcement runs after path normalization. `ValidateArgs.paths` are
normalized via `_normalize_validate_paths()` before being compared against
`before_git_state.dirty_paths` (workspace-relative POSIX paths from git porcelain
parsing). This means relative, absolute, and `./`-prefixed paths are all resolved
to their canonical workspace-relative form before the `allow_listed_dirty`
comparison.

`_check_dirty_policy()` from `validate_git.py` is the single policy authority.
`Validate.run()` no longer inlines dirty-policy logic that compares raw
`args.paths` against dirty paths.

When `expected_dirty_policy` is set and the policy fails, the validation yields a
`ValidateResult` with `status="failed"`, `error_kind="dirty_workspace"`, and a
`blocker_summary` containing `dirty_workspace: 1`.

### worktree-readiness Profile

A new profile with no lint/test/schema commands. Purely git state collection
and dirty policy enforcement. Suitable for answering "is this lane clean enough
for handoff or aggregation?"

Checks: none (git state is collected by the run() method, not profile checks)

### Receipt Content-Light Behavior

- Full `ValidateGitState` is available in `ValidateResult.before_git_state` and `after_git_state`
- Receipt contains only `before_git_summary` and `after_git_summary` with counts only (dirty_count, modified_count, deleted_count, untracked_count, staged_count, conflicted_count)
- No path data, no hashes, no raw status text in receipts

### Known Limitations

- `promotion-readiness` profile not implemented
- Fleet/delegate integration not implemented
- Aggregate patch planning not implemented
- Automatic promotion logic not implemented


## Current Repository Fit

The repository already has clear precedents:

- bash envelope and receipt policy
- schema validation script
- tool receipt validation script
- tool hardening audits
- promotion/readiness tests

`validate` should compose those patterns rather than invent a second ad hoc convention.
