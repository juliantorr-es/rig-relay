# Validate Implementation Roadmap

## Stage 0 - Audit and Contract Only

Goal:

- document observed bash families and the desired contract

Files likely affected:

- audit docs only

Tests needed:

- JSONL parseability for any classification data

Risks:

- overfitting to current repo habits

Exit criteria:

- design approved

## Stage 1 - Read-Only Validate Profiles ✅ COMPLETED

Goal:

- wrap known read-only validation commands

Files:

- `vibe/core/tools/builtins/validate.py` — tool module
- `tests/tools/test_validate.py` — 37 tests

Implementation:

- Profile registry (`Profile`/`ProfileCheck`) with 5 read-only profiles
- `ValidateArgs`, `ValidateCheckResult`, `ValidateResult` (Pydantic, `extra="forbid"`)
- Subprocess execution via `asyncio.create_subprocess_exec` (argv-based, no shell)
- Blocker taxonomy mapping (`classify_failure`)
- Dependency checking (`check_missing_dependency`)
- Output capping and truncation flags
- SHA256 hashing for stdout/stderr
- `command_fingerprint` for normalized argv
- Read-only enforcement (`allow_mutation=false` by default, network blocked)
- Schemas: `rig.relay.validate_invocation.v1`, `rig.relay.validate_result.v1`

Supported profiles:

| Profile | Checks |
|---------|--------|
| `quick` | git status |
| `python` | ruff check, pyright |
| `schemas` | schema validation script |
| `receipt-policy` | receipt policy validation script |
| `tool-hardening` | bash hardening tests, receipt emission tests |

Not implemented (Stage 2+):

- `ValidateReceipt` emission
- parsed validator output summaries
- worktree/lane promotion logic
- aggregate patching
- fleet/delegate integration
- `governance`, `worktree-readiness`, `promotion-readiness` profiles

Exit criteria met:

- `quick`, `python`, `schemas` work
- all profiles are read-only by default
- blocker taxonomy maps exit codes to structured kinds
- content-light result model (no raw stdout/stderr in long-lived fields)

## Stage 2 - Content-Light ValidateReceipt ✅ COMPLETED

Goal:

- emit receipts with hashes, counts, and blocker summaries

Files:

- `vibe/core/tools/builtins/validate.py` — added `ValidateCheckReceipt`, `ValidateReceipt`, `build_receipt()`
- `docs/schemas/rig.relay.validate_receipt.v1.schema.json` — new schema
- `rig_relay/evidence/receipt_index.py` — updated `_build_record_from_event()` for validate tool
- `tests/tools/test_validate.py` — 11 new receipt/builder tests
- `tests/evidence/test_receipt_index.py` — 5 new validate receipt index tests

Implementation:

- `ValidateCheckReceipt` model (content-light, `extra="forbid"`, no raw stdout/stderr)
- `ValidateReceipt` model with `check_receipts: list[ValidateCheckReceipt]`
- `Validate.build_receipt(result) -> ValidateReceipt` duck-typed method
- Receipt index handles validate tool (no file mutation, no top-level stdout/stderr)
- Receipt schema `rig.relay.validate_receipt.v1` with per-check `$defs`

Tests:

- 48 validate tool tests total (37 Stage 1 + 11 Stage 2)
- 37 receipt index tests total (32 original + 5 validate)
- All pass: 78/78 schemas, 0 ruff errors, 0 pyright errors

Not implemented (Stage 3):
- path scoping for validate profiles
- parsed validator output summaries

Exit criteria met:

- receipts are content-light by default
- no raw stdout/stderr in receipt models
- receipt schema validated
- receipt index supports validate tool

## Stage 3 - Path-Scoped Validation Profiles ✅ COMPLETED

Goal:

- add deterministic path scoping to validate profiles so agents can run focused validation against changed files

Files:

- `vibe/core/tools/builtins/validate.py` — added `_normalize_validate_paths()`, `_scope_check_argv()`, `_resolve_paths()`, `_build_checks()`, `_skipped_result()`, `_build_run_result()`
- `tests/tools/test_validate.py` — 14 new path scoping tests
- `docs/audits/validate-tool/validate-tool-contract.md` — updated

Implementation:

- `_normalize_validate_paths(paths, workspace_root)` — resolves relative paths, refuses paths outside workspace
- `_scope_check_argv(check, paths)` — scopes ruff/pytest argv to paths; skips schema/policy checks when paths don't match domain
- `_resolve_paths(args, cwd)` — runtime path resolution helper
- `_build_checks(profile, normalized_paths)` — adds scoped ruff check to `quick` profile when paths provided
- `_skipped_result(check)` — compact skipped check result factory
- `_build_run_result(results, profile, start)` — extracted result builder (reduces run() complexity)
- Refactored `run()` to stay under ruff PLR0915 (50 stmts) and PLR0912 (15 branches) limits
- `quick` profile: adds scoped `ruff check` dynamically when paths provided
- `python` profile: scopes `ruff check` argv, leaves `pyright` repo-wide
- `tool-hardening` profile: scopes `pytest` argv to paths
- `schemas` profile: skipped when no schema paths provided
- `receipt-policy` profile: skipped when no receipt-related paths provided
- All content-light receipts unaffected (no raw paths in receipt payloads)

Tests:

- 62 validate tool tests total (48 Stage 1+2 + 14 Stage 3)
- Path normalization: empty, inside workspace, outside workspace (refused), no workspace root (uses cwd)
- Check scoping: ruff appends paths, pytest appends paths, schema skips/runs based on path domain, policy skips/runs based on path domain, git/pyright unchanged, no paths returns original
- Quick profile gets scoped ruff dynamically at runtime

Risks:

- path scoping for `schemas` and `receipt-policy` uses simple substring matching ("schema", "receipt") — could produce false negatives for unusual path patterns
- `quick` profile dynamic ruff check is added at runtime, not in the profile definition — the checks don't persist between invocations

Follow-up fix (Stage 3 follow-up, applied immediately after initial Stage 3):

- `_normalize_validate_paths` was changed to return **workspace-relative POSIX paths** instead of absolute paths
- Absolute paths are used only for internal containment checking (`resolved.relative_to(root)`)
- Absolute input paths (e.g., `/workspace/sub/file.py`) are converted to relative (`sub/file.py`)
- Handles absolute input paths by resolving them directly (not via `root / p`)
- All path deduplication, sorting, and nonexistent-check behavior preserved
- All downstream consumers (argv, `command_fingerprint`, `affected_paths`, `ValidateReceipt`) automatically receive relative paths
- 9 new regression tests added for stable relative path behavior
- `command_fingerprint` is now stable across machines, worktrees, and input path forms

Path representation policy:
- **Internal containment**: absolute resolved paths (not exposed)
- **Exposed paths**: workspace-relative, POSIX forward-slash, sorted
- **argv**: relative paths in subprocess commands (valid because cwd = workspace_root)
- **fingerprints**: computed from relative-path argv → machine-independent
- **receipts**: content-light with relative `affected_paths`

Exit criteria met:

- paths are normalized and validated for safety
- unsafe paths (outside workspace) are refused with structured result
- relevant profile checks are scoped to provided paths
- irrelevant checks are skipped
- `quick` profile gets scoped ruff when paths provided
- **absolute input paths are converted to relative** (stable fingerprints)
- **absolute paths never leak into argv, fingerprints, or receipts**
- **outside-workspace absolute paths are still refused**
- **traversal paths are still refused**
- **fingerprints are identical for absolute and equivalent relative input**
- **fingerprints are independent of path input order**
- **POSIX separators used for all exposed paths**
- all existing tests pass
- ruff: 0 errors, pyright: 0 errors, schemas: 78/78 valid


## Stage 4 - Parsed Summaries ✅ COMPLETED

Goal:

- add conservative, deterministic parsed summaries to `ValidateCheckResult.parsed_summary` for common validator outputs

Files:

- `vibe/core/tools/builtins/validate.py` — added `_parse_ruff_summary()`, `_parse_pyright_summary()`, `_parse_pytest_summary()`, `_parse_schema_summary()`, `_parse_policy_summary()`, `_parse_check_summary()` dispatcher
- `tests/tools/test_validate.py` — 28 new parser tests

Implementation:

- **Ruff parser** (`_parse_ruff_summary`): parses `path:line:col: CODE message` format. Extracts `violation_count`, `rule_counts` (per-rule-code frequency), and `files` (sorted unique affected files). All content-light: no full messages, no raw diffs.
- **Pyright parser** (`_parse_pyright_summary`): parses terminal summary line (`N errors, M warnings, K informations`). Uses last line containing both "error" and "warning". Returns `error_count`, `warning_count`, `information_count`.
- **Pytest parser** (`_parse_pytest_summary`): parses terminal summary for `passed`, `failed`, `skipped`, `xfailed`, `xpassed`, `error` counts. Uses last line containing any of these keywords.
- **Schema parser** (`_parse_schema_summary`): handles `N/N schemas valid` and `Passed: N / Failed: M` formats. Returns `valid_count`, `total_count`, `failed_count`.
- **Policy parser** (`_parse_policy_summary`): tries JSON extraction (findings/violations arrays) first; falls back to text line counting for "finding"/"violation" mentions.
- **Dispatcher** (`_parse_check_summary`): routes by `command_kind`. Unknown kinds return None.
- **Integration** (`_run_check`): `parsed_summary` field populated in returned `ValidateCheckResult` before building receipt.
- **Parsing does not affect pass/fail**: status determined by exit code, timeout, and blocker mapping only. Parsed summaries are diagnostic metadata.
- **Parser failure is safe**: returns None for unparseable output; never raises exceptions.
- **Receipts remain content-light**: `parsed_summary` is **not** included in `ValidateCheckReceipt` or `ValidateReceipt` (extra=forbid on receipt models enforces this).
- **No raw output in summaries**: parser output dicts never contain stdout/stderr/raw keys.

Tests (28 new):

| Test | What it validates |
|------|-------------------|
| `test_parse_ruff_summary_counts` | violation_count, rule_counts, files from sample stdout |
| `test_parse_ruff_summary_empty` | empty/malformed returns None |
| `test_parse_pyright_summary_plural` | "1 error, 2 warnings, 0 informations" |
| `test_parse_pyright_summary_singular` | "0 errors, 0 warnings, 0 informations" |
| `test_parse_pyright_summary_malformed` | garbage text returns None |
| `test_parse_pytest_summary_counts` | "1 failed, 2 passed" → passed_count=2, failed_count=1 |
| `test_parse_pytest_summary_skipped` | "2 skipped, 1 xfailed" → skipped_count=2, xfailed_count=1 |
| `test_parse_pytest_summary_passed_only` | "3 passed" → passed_count=3 |
| `test_parse_pytest_summary_malformed` | returns None |
| `test_parse_schema_summary_slash_format` | "78/78 schemas valid" → valid_count=78 |
| `test_parse_schema_summary_passed_failed_format` | "Passed: 75 / Failed: 3" → valid_count=75, failed_count=3 |
| `test_parse_schema_summary_empty` | empty returns None |
| `test_parse_policy_summary_json` | JSON with findings array → finding_count=3 |
| `test_parse_policy_summary_json_violations` | JSON with violations array → finding_count=2 |
| `test_parse_policy_summary_text_fallback` | text with "finding" lines → parsed with counts |
| `test_parse_policy_summary_empty` | empty returns None |
| Dispatch tests (5) | each command_kind routes to correct parser |
| `test_parse_check_summary_unknown_kind` | unknown/git/empty returns None |
| `test_parsed_summary_in_model` | ValidateCheckResult stores parsed_summary correctly |
| `test_parsed_summary_none_default` | parsed_summary defaults to None |
| `test_parsed_summary_no_raw_fields` | parsed_summary dict has no stdout/stderr/raw keys |
| `test_parsed_summary_not_in_check_receipt` | ValidateCheckReceipt rejects extra `parsed_summary` field |
| `test_parsed_summary_not_in_validate_receipt` | ValidateReceipt has no parsed_summary leakage |
| `test_run_check_parsed_summary_field_present` | _run_check result has parsed_summary attribute |

Exit criteria met:

- ruff, pyright, pytest, schema, and policy outputs expose consistent structured summaries
- parser failure never propagates (returns None)
- receipts remain content-light (no parsed_summary in receipt models)
- parsed_summary contains no raw stdout/stderr
- all 108 tests pass (80 existing + 28 new)
- ruff: 0 errors in new/modified files
- pyright: 0 errors in new/modified code
- schemas: 78/78 valid


Goal:

- make validate understand workspace state and lane scope

Files likely affected:

- git-read helpers
- lane metadata
- dirty policy handling

Tests needed:

- dirty workspace classification
- path scope handling

Risks:

- confusing lane policy with tool semantics

Exit criteria:

- validate can explain lane eligibility

## Stage 5 - Worktree/Lane Awareness and Dirty-State Policy ✅ COMPLETED

Goal:

- teach validate to understand explicit workspace roots, dirty-state policy, and lane readiness

Files:

- `vibe/core/tools/builtins/validate.py` — added `ValidateGitState`, `_collect_git_state()`, `_parse_git_status_porcelain()`, `_check_dirty_policy()`, `worktree-readiness` profile, `_git_summary()` in `build_receipt()`
- `tests/tools/test_validate_git_state.py` — 27 new tests
- `docs/schemas/rig.relay.validate_receipt.v1.schema.json` — added `GitSummary` schema, `before_git_summary`/`after_git_summary` fields

Implementation:

- `ValidateGitState` model (content-light, `extra="forbid"`, counts and workspace-relative POSIX paths only)
- `_run_git()` — read-only argv subprocess for safe git introspection
- `_parse_git_status_branch()` — parses `## branch...upstream [ahead N behind M]`
- `_parse_git_status_porcelain_line()` — per-line porcelain status parser
- `_parse_git_status_porcelain()` — full `git status --short --branch` parser
- `_collect_git_state()` — async git state collection with timeout, missing-dep handling, non-repo tolerance
- `_check_dirty_policy()` — enforces `allow_dirty`, `clean`, and `allow_listed_dirty` policies
- `build_receipt()` — `_git_summary()` helper extracts compact content-light counts (no paths/hashes)
- `ValidateReceipt` — `before_git_summary`/`after_git_summary` fields (counts only, no raw paths/hashes)
- `ValidateResult.before_git_state`/`after_git_state` — full `ValidateGitState` for diagnostic use
- `run()` method — collects git state at start and end, enforces dirty policy before running checks
- `worktree-readiness` profile — no lint/test/schema checks, purely git state + dirty policy enforcement

Not implemented:
- `promotion-readiness` profile
- fleet/delegate integration
- aggregate patch planning
- automatic promotion logic

Exit criteria met:

- git state collection works in real repos (temp git repo tested)
- dirty policy blocks/refuses based on expected_dirty_policy
- `allow_dirty` passes dirty workspace
- `clean` blocks dirty workspace
- `allow_listed_dirty` allows listed dirty paths, blocks unlisted
- non-git-repo behavior is structured, not crashing
- receipts remain content-light (counts only in `before_git_summary`/`after_git_summary`)
- receipt schema updated and validated
- 253 total tests across all stages


## Stage 6 - Dirty-Policy Normalization Fix ✅ COMPLETED

Goal:

- fix dirty-policy enforcement in `Validate.run()` so `allow_listed_dirty` compares
  git dirty paths against normalized workspace-relative paths, not raw `args.paths`

Bug:

- `_collect_git_state()` was called before path normalization
- dirty-policy `allow_listed_dirty` compared `set(args.paths)` (raw user input —
  absolute, `./`-prefixed, or duplicated) against `before_git_state.dirty_paths`
  (workspace-relative POSIX paths from porcelain parsing)
- absolute paths like `/absolute/path/to/file.py` never matched `"file.py"`
- `./`-prefixed paths like `"./file.py"` never matched `"file.py"`
- two inlined dirty-policy branches duplicated `_check_dirty_policy()` but used raw
  args.paths instead of normalized paths

Fix:

- moved path normalization (`_resolve_paths` → `_normalize_validate_paths`) before
  git state collection
- unsafe-path refusal now happens before dirty-policy enforcement
- git state collection (`_collect_git_state`) runs after normalization
- both inlined dirty-policy branches replaced with a single
  `_check_dirty_policy(before_git_state, args.expected_dirty_policy, normalized_paths)`
  call — `_check_dirty_policy` is now the single policy authority

New execution order in `Validate.run()`:

1. resolve profile
2. check mutation/network policy
3. compute output cap
4. resolve cwd/workspace_root
5. normalize paths with `_normalize_validate_paths(args.paths, cwd)`
6. if unsafe paths, return structured refused `ValidateResult`
7. collect `before_git_state`
8. enforce `expected_dirty_policy` via `_check_dirty_policy` with normalized paths
9. build checks
10. run checks
11. collect `after_git_state`
12. return `ValidateResult`

Files changed:

- `vibe/core/tools/builtins/validate.py` — reordered `run()` method
- `tests/tools/test_validate_git_state.py` — 9 new regression tests

Tests added:

- `test_allow_listed_dirty_relative_path_passes` — relative path matches dirty path
- `test_allow_listed_dirty_absolute_path_passes` — absolute path normalized to relative
- `test_allow_listed_dirty_dot_slash_path_passes` — `./` prefix normalized away
- `test_allow_listed_dirty_fails_with_unlisted_path` — unlisted dirty path detected
- `test_allow_listed_dirty_empty_paths_fails_when_dirty` — empty paths + dirty workspace
- `test_outside_workspace_path_refused_before_dirty_policy` — unsafe refusal precedes dirty check
- `test_allow_listed_dirty_duplicate_paths_passes` — dupes deduplicated
- `test_clean_policy_fails_on_any_dirty_file` — clean policy still works
- `test_allow_dirty_passes_with_dirty_files` — allow_dirty still works

Total validate tests: 145 (136 Stage 1-5 + 9 Stage 6)

Not implemented:
- `promotion-readiness` profile
- fleet/delegate integration
- aggregate patching
- parsed summary changes

Exit criteria met:

- `allow_listed_dirty` accepts relative, absolute, `./`-prefixed, and duplicated paths
- `allow_listed_dirty` blocks unlisted dirty paths and empty paths with dirty workspace
- unsafe paths are refused as `"refused"/"unsafe_paths"` before dirty-policy check
- `clean` and `allow_dirty` policies preserved
- `before_git_state` and `blocker_summary` present in dirty-policy failure results
- `_check_dirty_policy` is the single policy authority
- no duplicate inline dirty-policy logic in `validate.py`
- receipts remain content-light (no changes to receipt model)

## Stage 7 - Aggregate Patch Eligibility

Goal:

- determine whether a patch lane can be aggregated or promoted

Files likely affected:

- promotion gate logic
- blocker summarization

Tests needed:

- blocker aggregation
- readiness classification

Risks:

- false promotion positives

Exit criteria:

- validate can answer promotion readiness

## Stage 8 - Promotion Gate Integration

Goal:

- connect validate to promotion workflows

Files likely affected:

- lane promotion code
- CI / local gate hooks

Tests needed:

- end-to-end promotion gate

Risks:

- gate drift between local and CI

Exit criteria:

- promotion uses validate as a source of truth

## Stage 9 - Fleet / Delegate Policy Integration

Goal:

- make validate part of fleet and delegated execution policy

Files likely affected:

- policy registry
- delegation lane controls
- fleet orchestration

Tests needed:

- delegated lane readiness
- policy enforcement

Risks:

- overgeneralizing one repo's validation needs

Exit criteria:

- validate is policy-aware across lane types
