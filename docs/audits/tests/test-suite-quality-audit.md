# Test Suite Quality Audit

**Date:** 2025-06-13
**Branch:** main (HEAD `384e4860b14959769a14fbcb5b4ca27618dad861`)
**Scope:** Focus on validate, receipt, mutation-tool, schema, and governance tests.

## Repository State

| Metric | Value |
|--------|-------|
| Branch | `main` (ahead of `origin/main` by 2 commits — from prior sessions) |
| HEAD | `384e4860` |
| Dirty files at start | 25 modified, 51 untracked |
| Dirty files at end | Unchanged (no files modified by this audit) |
| Total test files | 352 (excluding stubs and `__pycache__`) |
| Total test functions | ~1,772 |
| Total test lines | ~91,434 |
| Top 3 largest test files | `test_validate.py` (1,797), `test_openai_responses_adapter.py` (1,322), `test_config_resolution.py` (1,250) |

## Test File Summary (Focus Area)

| File | Lines | Tests | Domain | Type | Speed | Dup Risk |
|------|-------|-------|--------|------|-------|----------|
| `test_validate.py` | 1,797 | 127 | validate | integration | slow | **high** |
| `test_validate_git_state.py` | 390 | 27 | validate_git_state | integration | slow | **high** |
| `test_tool_receipt_emission.py` | 1,208 | 34 | receipt_emission | unit | fast | medium |
| `test_tool_receipt_policy.py` | 359 | 25 | receipt_policy | contract | fast | medium |
| `test_receipt_index.py` | 881 | 40 | receipt_index | unit | fast | medium |
| `test_bash_hardening.py` | 278 | 21 | bash_hardening | unit | fast | medium |
| `test_bash.py` | 317 | 10 | bash | unit | fast | low |
| `test_hardened_tools.py` | 755 | 29 | hardened_tools | integration | slow | low |
| `test_schema_validation.py` | 145 | 12 | schema_validation | contract | fast | low |
| `test_validation_suite.py` | 290 | 8 | validation_suite | integration | medium | low |
| `test_tool_contract_coverage.py` | 77 | 2 | tool_contract | unit | fast | low |
| `test_checkpoint.py` | 518 | 11 | checkpoint | integration | slow | low |

## Duplicate/Near-Duplicate Summary

**11 duplicate groups identified** (see `data/test_duplicate_candidates.jsonl`):

| Group | Type | Files | Tests |
|-------|------|-------|-------|
| dup-001 | **Exact** | test_validate.py, test_validate_git_state.py | test_collect_git_state_non_repo |
| dup-002 | Near | test_validate.py, test_validate_git_state.py | test_validate_receipt_git_summary_content_light |
| dup-003 | Near | test_validate.py, test_validate_git_state.py | validate_git_state extra_forbidden |
| dup-004 | **Near (6 pairs)** | test_validate.py, test_validate_git_state.py | All dirty_policy tests |
| dup-005 | Near | test_validate.py, test_validate_git_state.py | worktree_readiness profile tests |
| dup-006 | Near | test_validate.py, test_validate_git_state.py | porcelain parsing full output |
| dup-007 | **Exact (3)** | test_delegate_fleet.py, test_queue_plan.py | schema validation tests |
| dup-008 | Near | test_bash.py, test_bash_hardening.py | test_uses_effective_workdir |
| dup-009 | Near | test_bash.py, test_grep.py | test_uses_effective_workdir |
| dup-010 | **Exact** | test_rig_intake_cannibalization_plan.py, test_textual_retirement_policy.py | test_textual_retirement_policy_exists |
| dup-011 | Near (justified) | test_github_update_gateway.py, test_pypi_update_gateway.py | Adapter interface conformance |

**Total candidates for removal:** ~15-18 test functions
**Net reduction if merged:** ~300-400 lines

## Primary Risk: Validate Test Overlap

**`test_validate.py` (1,797 lines, 127 tests)** and **`test_validate_git_state.py` (390 lines, 27 tests)** contain:

- **1 exact duplicate** (test_collect_git_state_non_repo)
- **~15 near-duplicates** across dirty policy, git state model, porcelain parsing, and worktree readiness
- **Same Stage 5 git-state tests** were added to test_validate.py first, then test_validate_git_state.py was created as a cleaner dedicated file — but the originals were never removed
- **`test_validate.py` does NOT need to keep any git-state tests** — they were added as part of Stage 5 and are fully covered in `test_validate_git_state.py`

**Recommended:** remove 19 tests from test_validate.py (all git-state tests starting at line 1469), reducing it by ~310 lines. No coverage loss.

## Brittle/Low-Value Test Patterns

1. **Private helper assertion tests** — `test_validate.py` has many tests that import and assert against private functions (`_parse_git_status_branch`, `_parse_git_status_porcelain_line`, `_check_dirty_policy`, etc.). These are implementation-detail tests. While they provide fast feedback during development, they are brittle to refactoring and should be supplemented (not replaced) by public-behavior tests that exercise these helpers through `tool.run()`.

2. **`# type: ignore[call-arg]` on line 1773** of `test_validate.py` — Violates AGENTS.md rule against inline `# type: ignore`. Pre-existing from Stage 4.

3. **Exact string matching on refusal messages** — Several receipt emission tests match exact strings like `"Command timed out after 30s"`. Brittle if wording changes.

4. **Test files with 0 test functions** — `tests/governance/test_local_action_envelope.py` (434 lines) contains no `test_` functions. May be a conftest or fixture file with misleading name.

## High-Value Tests to Preserve

| File | Tests to Protect | Reason |
|------|-----------------|--------|
| `test_schema_validation.py` | All 12 | Schema integrity is critical; low brittleness |
| `test_tool_receipt_policy.py` | All 25 | Content-light enforcement is a privacy contract |
| `test_tool_contract_coverage.py` | Both | Ensures all builtins have determinism/mutation metadata |
| `test_hardened_tools.py` | All 29 | write_file hash, dirty guard, lease — critical mutation safety |
| `test_bash_hardening.py` | All 21 | Deterministic envelope — core bash contract |
| `test_validate_git_state.py` | All 27 (except exact duplicate) | Complete git state coverage |
| `test_tool_receipt_emission.py` | Receipt schema validation tests + receipt_policy integration tests | Schema contract validation is rare and high-value |

## High-Value Tests to Remove (after equivalent coverage confirmed)

| File | Tests | Reason |
|------|-------|--------|
| `test_validate.py` | 19 git-state tests (lines 1469-1797) | Fully covered by test_validate_git_state.py |
| `test_bash.py` | test_uses_effective_workdir | Covered by test_bash_hardening.py |
| `test_rig_intake_cannibalization_plan.py` | test_textual_retirement_policy_exists | Exact duplicate of dedicated file |
| `test_delegate_fleet.py` / `test_queue_plan.py` | 3 schema validation tests | Covered by test_schema_validation.py |

## Key Missing Coverage (see `data/test_coverage_gap_inventory.jsonl`)

**High priority (11 gaps identified):**

1. **Receipt pipeline E2E** — No test chains build_receipt → capture → policy validate → index for any tool
2. **Validate pipeline E2E** — No test chains run → build_receipt → capture → index
3. **Model dump vs schema validation** — 6 of 8 schema test files exist but only 2 have model-dump validation
4. **Bash/search_replace/validate result + invocation schema validation** — 9 untested schemas
5. **Dirty policy E2E (allow_dirty, allow_listed_dirty)** — Only clean policy has E2E test
6. **write_file receipt policy validation** — write_file has no receipt pipeline tests

## Subprocess and Git Test Profile

| File | Subprocess | Git | Speed | Recommended Tier |
|------|-----------|-----|-------|-----------------|
| test_validate.py | Yes | Yes | Slow | Tier 2 (integration) |
| test_validate_git_state.py | Yes | Yes | Slow | Tier 2 (integration) |
| test_checkpoint.py | Yes | Yes | Slow | Tier 2 (integration) |
| test_hardened_tools.py | Yes | No | Medium | Tier 1 (standard) |
| test_bash_hardening.py | Yes | No | Medium | Tier 1 (standard) |
| test_bash.py | Yes | No | Medium | Tier 1 (standard) |
| test_validation_suite.py | Yes | No | Medium | Tier 1 (standard) |
| test_tool_receipt_emission.py | No | No | Fast | Tier 0 (immediate) |
| test_schema_validation.py | No | No | Fast | Tier 0 (immediate) |
| test_tool_receipt_policy.py | No | No | Fast | Tier 0 (immediate) |

## Compute Pattern: `pytest from inside pytest`

Only `tests/tools/test_validation_suite.py` uses subprocess-based pytest invocation. This is intentional (tests the validation suite orchestration). All other subprocess tests run git, uv, or shell commands.

See `data/test_file_inventory.jsonl`, `data/test_duplicate_candidates.jsonl`, `data/test_coverage_gap_inventory.jsonl` for detailed records.

See `test-cleanup-roadmap.md` for staged cleanup plan.
