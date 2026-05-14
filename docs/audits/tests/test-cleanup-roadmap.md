# Test Cleanup Roadmap

Staged plan to reduce duplication, consolidate test files, and fill coverage gaps.

## Stage 0 — Audit (Complete)

**Goal:** Identify all duplicate, near-duplicate, brittle, and missing tests.

**Already done:**
- `docs/audits/tests/test-suite-quality-audit.md`
- `docs/audits/tests/test-quality-taxonomy.md`
- `docs/audits/tests/data/test_file_inventory.jsonl` (16 files)
- `docs/audits/tests/data/test_duplicate_candidates.jsonl` (11 groups)
- `docs/audits/tests/data/test_coverage_gap_inventory.jsonl` (11 gaps)

**Validation:** All 3 JSONL files validated as parseable JSONL.

---

## Stage 1 — Test Taxonomy and Ownership

**Goal:** Document test-tier conventions and assign explicit ownership/labels.

**Files affected:**
- `pyproject.toml` (add pytest markers: `tier0`, `tier1`, `tier2`, `slow`)
- `tests/conftest.py` (register markers)
- `docs/audits/tests/test-quality-taxonomy.md` (already exists)

**Actions:**
1. Add pytest markers to `pyproject.toml`:
   ```
   [tool.pytest.ini_options]
   markers = [
       "tier0: runs on every file change (unit + contract)",
       "tier1: runs on every PR (unit + contract + fast integration)",
       "tier2: runs nightly or on demand (slow integration + git)",
       "slow: exceeds 200ms runtime",
   ]
   ```
2. Document tier conventions in taxonomy doc.
3. Add test ownership comments (module-level) to each major test file.

**Tests to preserve:** All
**Tests to delete:** None
**Risks:** Low — metadata only
**Exit criteria:** `uv run pytest --markers` shows the 4 new markers

---

## Stage 2 — Validate Test Consolidation ✅ (Complete)

**Goal:** Remove exact and near-duplicate git-state tests from `test_validate.py` and clean up the file split.

**Status:** ✅ Done — 18 duplicate tests removed, 1 unique test preserved.

**Files affected:**
- `tests/tools/test_validate.py` — 18 git-state tests removed (preserved `test_collect_git_state_porcelain_sha256` which has no equivalent in dedicated file)
- `tests/tools/test_validate_git_state.py` — no changes

**Tests removed (18):**
```
test_parse_git_status_branch_sets_branch
test_parse_git_status_branch_with_ahead_behind
test_parse_git_status_branch_detached_head
test_parse_git_status_porcelain_line_untracked
test_parse_git_status_porcelain_line_modified
test_parse_git_status_porcelain_parses_full_output
test_collect_git_state_non_repo                     [EXACT DUPLICATE]
test_collect_git_state_empty_repo
test_collect_git_state_detects_dirty
test_check_dirty_policy_none_passes
test_check_dirty_policy_allow_dirty_passes
test_check_dirty_policy_clean_fails_when_dirty
test_check_dirty_policy_clean_passes_when_clean
test_check_dirty_policy_allow_listed_dirty_passes
test_check_dirty_policy_allow_listed_dirty_fails
test_worktree_readiness_profile_registered
test_validate_receipt_git_summary_content_light
test_validate_git_state_extra_forbidden
```

**Coverage preserved:** All 18 removals fully covered by `test_validate_git_state.py` (27 tests)
**Net reduction:** 308 lines, 18 tests; `test_validate.py` now 1,489 lines / 109 tests
**Validation:** `uv run pytest tests/tools/test_validate_git_state.py -x` → 27 passed; `uv run pytest tests/tools/test_validate.py -x` → 109 passed

---

## Stage 3 — Schema/Model Contract Tests ✅ (Complete)

**Goal:** Add model-dump-against-schema validation for all untested schemas.

**Status:** ✅ Done — 13 tests added covering 9 schemas across 3 tool families.

**Files affected (create):**
- `tests/tools/test_tool_schema_contracts.py` — 13 tests for bash, search_replace, validate models

**Coverage added (closed gaps gap-003, gap-008, gap-009, gap-010, gap-011):**
| Tool | Result | Receipt | Invocation |
|------|--------|---------|------------|
| Bash | ✓ `BashResult` → schema | ✓ `BashReceipt` → schema | ✓ `BashArgs` → schema |
| SearchReplace | ✓ `SRResult` → schema | ✓ `SRReceipt` → schema | ✓ `SRArgs` → schema |
| Validate | ✓ `ValResult` → schema | ✓ `ValReceipt` → schema | ✓ `ValArgs` → schema |

**Schema fixes (2 stale bash schemas):**
- `bash_result.v1`: renamed `exit_code`→`returncode`, added `stdout`/`stderr`, fixed nullable fields
- `bash_invocation.v1`: renamed `timeout_ms`→`timeout`, removed `allow_shell`/`schema_version`, fixed nullable fields
- Fixed nullable `error_kind`, `refusal_reason`, `duration_ms` across all search_replace and validate schemas

**Not yet covered:** WriteFile and Contribution schemas (need schema files)
**Validation:** `uv run pytest tests/tools/test_tool_schema_contracts.py -x` → 13 passed; `uv run python scripts/rig_relay_validate_schemas.py` → 78/78 valid

---

## Stage 4 — Mutation Tool Test Matrix

**Goal:** Create a shared contract matrix for search_replace and write_file tests to reduce per-tool redundancy in `test_tool_receipt_emission.py`.

**Files affected:**
- `tests/tools/test_tool_receipt_emission.py` — refactor to use shared parametrized tests
- `tests/tools/test_hardened_tools.py` — no changes

**Actions:**
1. Create shared fixture factory that produces receipt-test matrix entries (tool class, success result, failure result, refusal result)
2. Parametrize receipt content-light tests across bash, search_replace, write_file, validate
3. Keep tool-specific tests (hashes, status fields) in dedicated files

**Tests to preserve:** All current behavior coverage
**Tests to merge:** bash_receipt_content_light, sr_receipt_content_light, validate_receipt_content_light into single parametrized test
**Net reduction:** ~100-150 lines by removing near-identical receipt assertion patterns

**Risks:** Low — structural refactor only; behavior assertions unchanged
**Validation:** `uv run pytest tests/tools/test_tool_receipt_emission.py -x`
**Exit criteria:** Receipt content-light tests are parametrized; no 3-copies-of-the-same-pattern exist

---

## Stage 5 — Receipt Pipeline Integration Tests

**Goal:** Add end-to-end receipt pipeline tests (filling gaps gap-001, gap-002, gap-005).

**Files affected (create):**
- `tests/evidence/test_receipt_pipeline_integration.py`

**Coverage to add:**
- `test_receipt_pipeline_bash`: bash run() → build_receipt → capture → policy validate → index → verify
- `test_receipt_pipeline_search_replace`: same for search_replace
- `test_receipt_pipeline_validate`: same for validate
- `test_receipt_pipeline_write_file`: same for write_file
- `test_receipt_pipeline_rejects_raw_output`: policy rejection through full pipeline
- `test_validate_pipeline_e2e`: run validate profile → build_receipt → capture → verify index contents match

Each test should:
1. Create a temp directory and observability JSONL
2. Run the tool with controlled inputs
3. Call `build_receipt()` on the result
4. Call `capture_tool_receipt()` to write to JSONL
5. Read back the JSONL event
6. Call `validate_receipt_payload()` on the event
7. Call `build_receipt_index()` on the JSONL
8. Index contains expected tool_name, status, count fields

**Tests to preserve:** All existing
**Tests to delete:** None
**Risks:** Low — new tests only; medium complexity due to patching telemetry paths
**Validation:** `uv run pytest tests/evidence/test_receipt_pipeline_integration.py -x`
**Exit criteria:** All 4 core tools have a full pipeline E2E test

---

## Stage 6 — Slow/Integration Tiering

**Goal:** Mark slow tests with `@pytest.mark.slow` and configure CI to split Tier 0/1/2.

**Files affected:**
- `tests/tools/test_validate.py` — add `@pytest.mark.slow` where absent (already has some `@pytest.mark.asyncio`)
- `tests/tools/test_validate_git_state.py` — add `@pytest.mark.slow` and `@pytest.mark.integration`
- `tests/tools/test_checkpoint.py` — add `@pytest.mark.slow`
- `tests/tools/test_hardened_tools.py` — add `@pytest.mark.integration`
- `tests/tools/test_bash_hardening.py` — add `@pytest.mark.integration`
- `tests/tools/test_validation_suite.py` — add `@pytest.mark.integration`
- `pyproject.toml` — register markers
- CI workflow — split test run: `uv run pytest -m "not slow and not integration"` for fast CI, `uv run pytest -m "slow or integration"` for nightly

**Tests to preserve:** All
**Tests to delete:** None
**Risks:** Low — metadata only. Risk of incorrectly marking a fast test as slow
**Validation:** `uv run pytest --co -q` shows correct test counts per marker
**Exit criteria:** CI fast path runs without `@pytest.mark.slow` or `@pytest.mark.integration` tests; ~100-150 tests defer to nightly

---

## Stage 7 — CI Test Tier Alignment

**Goal:** Map all tests to Tier 0/1/2/3/4 and validate profiles.

| Tier | Scope | Command | Target time |
|------|-------|---------|-------------|
| Tier 0 | Immediate (file change) | `uv run pytest -m tier0 -x` | <10s |
| Tier 1 | PR gate | `uv run pytest -m "tier0 or tier1"` | <60s |
| Tier 2 | Nightly | `uv run pytest -m "tier2 or slow or integration"` | <300s |
| Tier 3 | Validate profile | `uv run rig-relay validate --profile quick` | — |
| Tier 4 | Full validation | `uv run rig-relay validate --profile tool-hardening` | — |

**Actions:**
1. Assign every test file a tier marker
2. Add CI workflow steps for each tier
3. Update `rig-relay validate` profiles to reference tier coverage
4. Add test to verify tier assignments are explicit for all test files

**Tests to preserve:** All
**Tests to delete:** None
**Risks:** Medium — tier mapping requires manual review of every test file for speed and dependency
**Validation:** `uv run pytest -m tier0 -x` completes <10s; `uv run pytest -m "tier0 or tier1"` completes <60s
**Exit criteria:** CI has separate fast/slow test paths; validate profiles reference tier coverage

---

## Summary of Effort

| Stage | Goal | Files Changed | Tests Removed | Lines Delta | Prio |
|-------|------|--------------|---------------|-------------|------|
| 0 | Audit (done) | 5 new | 0 | +2,500 | — |
| 1 | Taxonomy/tiers | 3 | 0 | +50 | Medium |
| 2 | Validate dedup ✅ | 1 | 18 | -308 | **High** |
| 3 | Schema contracts ✅ | 1 new | 0 | +350 | **High** |
| 4 | Mutation matrix | 1 | 0 | -150 | Medium |
| 5 | Pipeline E2E | 1 new | 0 | +300 | **High** |
| 6 | Slow tiering | 6 | 0 | +30 | Low |
| 7 | CI alignment | 2 | 0 | +50 | Medium |

**Recommended next slice:** Stage 4 (Mutation tool test matrix) + Stage 5 (Receipt pipeline E2E tests). Stage 2 and 3 are complete.
