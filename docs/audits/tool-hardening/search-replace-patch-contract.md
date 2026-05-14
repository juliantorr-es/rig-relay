# SearchReplace Patch Contract

## Overview

This document audits the hardening of the `search_replace` tool into a
deterministic, schema-validated, content-light patch contract.

## Motivation

Local Relay tool-usage audit evidence:

| Metric | Value |
|--------|-------|
| Total calls | 2,057 |
| Failures | 217 |
| Failure rate | ~10.55% |
| Risk tier | 2 (high) |
| p95 latency | ~3,200 ms |
| p95 output | ~2,400 bytes |

SearchReplace has the highest **failure rate** of any tool at ~10.55%. While
total call volume is lower than bash (5,023), the friction cost of failed
patches is high — each failure requires a human to re-read the file, adjust
the patch, and retry.

## What Changed

### Result Model Extensions (`SearchReplaceResult`)

Added structured status, error classification, and timing:

| Field | Type | Default |
|-------|------|---------|
| `status` | `str` | `"success"` |
| `error_kind` | `str \| None` | `None` |
| `refusal_reason` | `str \| None` | `None` |
| `duration_ms` | `float \| None` | `None` |
| `replacements` | `int` | `0` |
| `before_bytes` | `int` | `0` |
| `after_bytes` | `int` | `0` |

Status values: `success`, `no_match`, `ambiguous_match`, `count_mismatch`, `refused`.

### Error Classification

The `_classify_block_errors()` function maps block parser error messages to
structured `error_kind` values:

| Mismatch Pattern | `error_kind` |
|-----------------|--------------|
| `"Search text not found"` | `old_text_not_found` |
| `"search text hasn't been modified"` | `unchanged_replacement` |
| Fallback | `old_text_not_found` |

The `_classify_status_from_error_kind()` function maps `error_kind` to status:

| `error_kind` | `status` |
|-------------|----------|
| `old_text_not_found`, `unchanged_replacement`, `encoding_error` | `no_match` |
| `multiple_matches_when_single_required` | `ambiguous_match` |
| `replacement_count_mismatch` | `count_mismatch` |
| Unknown | `mismatch` |

### Refusal Classification

The `_classify_refusal()` function inspects `GuardCheck` attributes to
classify refusals. Currently heuristic-based; covers hash mismatch,
destructive path patterns, and guard policy violations.

### Structured Block Mismatch

Previously, block errors raised `ToolError`. Now they return a
`SearchReplaceResult(status="no_match", ...)` with block-level details.

### Structured Guard Refusal

Previously, guard refusal raised `ToolError`. Now the `run()` method yields
`SearchReplaceResult(status="refused", ...)` with the guard check detail.

### Content-Light Receipt

New `SearchReplaceReceipt` model — identical to `SearchReplaceResult` minus
the `content` field. Used for telemetry and audit trails without exposing
file contents.

### Schema Files

Three new JSON schemas:

- `docs/schemas/rig.relay.search_replace_invocation.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_result.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_receipt.v1.schema.json`

## Backward Compatibility

- All new `SearchReplaceResult` fields are optional with defaults
- `content` field preserved in result for legacy consumers
- `run()` signature unchanged — still yields `SearchReplaceResult`
- `SearchReplaceReceipt` is an additive model, not required
- File-not-found, outside-workdir, and parse failures still raise `ToolError`

## Bugs Fixed Incidentally

1. **CoordinationStore release_paths key mismatch** (`rig_relay/coordination/store.py`):
   `reserve_paths()` wrote lease files using `_path_key(session_id+task_id+paths)`
   while `release_paths()` looked for them using `_lease_path(sha256(path))` —
   completely different filenames. Fixed `release_paths()` to use the same
   key construction as `reserve_paths()`.

2. **SearchReplace class structure corruption**: A previous edit accidentally
   placed `_classify_status_from_error_kind()` at module level (indent 0),
   which closed the `SearchReplace` class and made all subsequent methods
   (`run`, `_apply_blocks`, etc.) nested functions inside it. Restored
   proper class membership with `@staticmethod`.

## Receipt Emission Verification

### Automatic Integration (verified)

SearchReplace receipts are **automatically emitted** through the generic
duck-typed receipt path in the agent loop (`vibe/core/agent_loop.py`
lines 1114–1130):

1. Agent loop calls `getattr(tool_instance, "build_receipt", None)` — finds
   `SearchReplace.build_receipt` via duck typing
2. Calls `build_receipt(result_model)` with the `SearchReplaceResult` yielded
   from `run()`
3. Calls `capture_tool_receipt()` to write `rig.relay.tool_receipt.captured`
   event to local observability JSONL

**No code change was required for SearchReplace receipt emission.** The
Phase 5 addition of `build_receipt()` to the `SearchReplace` class was
sufficient for automatic integration.

### Statuses That Emit Receipts

| Status | Source | Emits Receipt? |
|--------|--------|----------------|
| `success` | `_build_search_replace_result()` | Yes |
| `no_match` | `_apply_search_replace()` when `block_result.errors` | Yes |
| `ambiguous_match` | `_apply_search_replace()` when `allow_multiple=False` | Yes |
| `count_mismatch` | `_apply_search_replace()` when `expected_replacements` mismatches | Yes |
| `refused` | `run()` guard check failure | Yes |
| `ToolError` (file not found, outside workdir, parse failure) | `_prepare_and_validate_args()` | No — exception path, not a result |

### Receipt Fields (Content-Light Proof)

`SearchReplaceReceipt` model fields:

| Field | Content-Light? | Notes |
|-------|----------------|-------|
| `file` | Yes | Path string (repo-relative) |
| `status` | Yes | Structured enum value |
| `blocks_applied` | Yes | Integer count |
| `lines_changed` | Yes | Integer count |
| `replacements` | Yes | Integer count |
| `warnings` | ⚠️ | May contain file context snippets from fuzzy match |
| `before_file_sha256` | Yes | SHA256 hash only |
| `after_file_sha256` | Yes | SHA256 hash only |
| `changed_files` | Yes | Filenames only |
| `failed_block_count` | Yes | Integer count |
| `total_block_count` | Yes | Integer count |
| `before_bytes` | Yes | Integer count |
| `after_bytes` | Yes | Integer count |
| `error_kind` | Yes | Structured string |
| `refusal_reason` | ⚠️ | May contain file context from `_find_search_context()` |
| `duration_ms` | Yes | Float |

Explicitly excluded: `content`, `old_text`, `new_text`, `diff`, `patch`, `snippet`.

### Remaining Risks

1. **Warnings and refusal_reason may contain file content**: The
   `_find_search_context()` helper includes file context lines in error
   messages, which propagate to `refusal_reason` and `warnings`. A
   follow-up pass should strip or hash these context snippets before
   they enter the receipt.
2. **Legacy ToolError paths bypass receipt emission**: File-not-found,
   outside-workdir, and parse-failure errors raise `ToolError`, which the
   agent loop catches before reaching the receipt seam. This is acceptable
   — these are caller errors, not tool outcomes.
3. **No end-to-end agent-loop integration test**: The existing tests verify
   the `build_receipt` + `capture_tool_receipt` pipeline in isolation but
   do not exercise the full agent-loop code path. A synthetic agent-loop
   test would improve confidence.
4. **Schema `schema_version` field**: The receipt schema requires
   `schema_version` but the model does not emit it. The schema is
   descriptive/documentation rather than prescriptive for model_dump().
   This is consistent with bash's pattern.
5. **Refusal classification heuristic**: `_classify_refusal()` inspects
   `GuardCheck` attributes rather than using explicit refusal codes.
6. **No ToolReceipt content-light policy validator**: Should follow as
   the next slice — a validator over the full receipt stream.


### Receipt Sanitization

The `build_receipt()` method sanitizes `refusal_reason` via
``_sanitize_refusal_for_receipt()`` before it enters the receipt model.

| Rule | Applied? |
|------|----------|
| Strip search text (``old``/``new``) from ``refusal_reason`` | ✅ |
| Strip context analysis lines (file content) | ✅ |
| Strip fuzzy match diffs | ✅ |
| Keep summary lines (``SEARCH/REPLACE block …``) | ✅ |
| Keep ``Expected …`` lines (count mismatch) | ✅ |
| Keep debugging tips | ✅ |
| Return ``None`` for ``None`` or empty input | ✅ |
| Pass through safe strings unchanged | ✅ |

**Before sanitization** (rich error sent to user):
```
SEARCH/REPLACE block 1 failed: Search text not found in test.py
Search text was:
'NonExistent'
Context analysis:
Potential match area around line 1:
>>>   1: x = 1
      2: y = 2
Debugging tips:
1. Check for exact whitespace/indentation match
```

**After sanitization** (content-light receipt):
```
SEARCH/REPLACE block 1 failed: Search text not found in test.py
Debugging tips:
1. Check for exact whitespace/indentation match
```

### Policy Validator Integration

SearchReplace receipts in all statuses (`success`, `no_match`, `refused`) pass
the content-light policy validator (``validate_receipt_payload`` and
``validate_event``). No forbidden fields or value-shape violations are
produced.

### Instantiation

The abstract-class instantiation bug reported earlier was fixed in Phase 5
by restoring proper class indentation for ``_classify_status_from_error_kind``.
SearchReplace now instantiates cleanly and exposes ``run()`` and
``build_receipt()`` as expected.

### Remaining Risks

1. **Legacy ToolError paths** (file not found, outside workdir, parse
   failure) still bypass receipt emission. Acceptable — these are caller
   errors, not tool outcomes.
2. **No end-to-end agent-loop integration test**. ``build_receipt`` +
   ``capture_tool_receipt`` pipeline tested in isolation; full
   ``_execute_tool()`` path not exercised.
3. **``warnings`` field** is currently safe (counts and tips only) but
   could theoretically contain contextual strings in future.
4. **``refusal_reason`` for ``count_mismatch``** passes through
   unsanitized because count-mismatch errors contain only counts and
   expectations — no file content. This is safe by construction but
   worth noting.

### Existing Tests (in `tests/tools/test_hardened_tools.py`)

| Test | What It Verifies |
|------|------------------|
| `test_search_replace_rejects_outside_workdir_path` | Workdir boundary |
| `test_search_replace_does_not_write_when_block_fails` | Structured mismatch status |
| `test_search_replace_successful_records_hashes` | Before/after hashes |
| `test_search_replace_noop_records_block_counts` | No-op block counts |
| `test_search_replace_failed_does_not_emit_success_hash` | Failed block hashes |
| `test_search_replace_block_counts_on_partial` | Partial apply counts |
| `test_search_replace_dict_keys_relative` | Repo file key format |
| `test_search_replace_result_serializes` | Pydantic serialization |
| `test_search_replace_emits_coordination_events` | Coordination event ordering |

## Files Changed

- `vibe/core/tools/builtins/search_replace.py` — hardened result model,
  structured mismatch/refusal, receipt, error classification
- `rig_relay/coordination/store.py` — fixed `release_paths` key mismatch
- `tests/tools/test_hardened_tools.py` — updated tests for new status values

## Files Created

- `docs/schemas/rig.relay.search_replace_invocation.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_result.v1.schema.json`
- `docs/schemas/rig.relay.search_replace_receipt.v1.schema.json`
- `docs/audits/tool-hardening/search-replace-patch-contract.md` (this file)
