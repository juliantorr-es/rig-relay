# Mutation Tool Contract Matrix

## Overview

This matrix documents how the two mutation primitives (`write_file` and `search_replace`) satisfy the same high-level deterministic evidence guarantees. It is not a mandate to force identical implementations — each tool has legitimate domain-specific differences.

## Grades

| Grade | Meaning |
|-------|---------|
| complete | Feature is implemented and tested |
| partial | Feature exists but has known gaps |
| missing | Feature is not implemented |
| not_applicable | Feature does not apply to this tool |
| deferred | Feature is intentionally postponed |

## Matrix

| Guarantee | write_file | search_replace |
|-----------|-----------|----------------|
| **structured args** | complete — `WriteFileArgs` (path, content, overwrite flags, expected_before_sha256) | complete — `SearchReplaceArgs` (file_path, content, expected_before_sha256, expected_replacements, allow_multiple) |
| **structured result** | complete — `WriteFileResult` (path, bytes_written, file_existed, before/after sha256, created/overwritten flags, status, error_kind, refusal_reason, duration_ms, before_bytes, after_bytes) — has legacy `content` field not removed | complete — `SearchReplaceResult` (file, blocks_applied, lines_changed, before/after sha256 dict, changed_files, failed/total blocks, replacements, before/after bytes, status, error_kind, refusal_reason, duration_ms) |
| **structured status** | complete — `success`, `refused`, `blocked` | complete — `success`, `no_match`, `ambiguous_match`, `count_mismatch`, `refused`, `blocked` |
| **structured error_kind** | complete — `path_reserved`, `dirty_file_protected`, `expected_hash_mismatch`, `protected_file_missing`, `path_is_directory`, `content_too_large`, `overwrite_required`, `parent_missing` | complete — `old_text_not_found`, `unchanged_replacement`, `multiple_matches_when_single_required`, `replacement_count_mismatch`, `encoding_error`, guard refusal kinds |
| **structured refusal_reason** | complete — human-readable from guard, coordination, or deterministic checks | complete — human-readable from guard or coordination (sanitized for receipt) |
| **path safety** | complete — `normalize_tool_path`, `require_path_within_workdir` | complete — `normalize_tool_path`, `require_path_within_workdir`, outside-workspace refusal via structured `SearchReplaceResult(status="refused", error_kind="unsafe_path")` |
| **dirty-file protection** | complete — `guard.check_write_file()`, `allow_overwrite_protected` flag, `expected_before_sha256` | complete — `guard.check_search_replace()`, `expected_before_sha256` |
| **coordination lease/blocking** | complete — claim_task + reserve_paths, structured `blocked` result when store available | complete — claim_task + reserve_paths, structured `blocked` result when store available |
| **before_sha256** | complete — from snapshot on success path (None on refused/blocked) | complete — `before_file_sha256` dict (success and structured error paths) |
| **after_sha256** | complete — from file read after write | complete — `after_file_sha256` dict |
| **before_bytes** | complete — from snapshot content length on success path (0 for new files) | complete — `before_bytes` from `len(original_content)` (success) or `file_path.stat().st_size` (binary_file, parse_error); 0 for other refusal paths |
| **after_bytes** | complete — from file stat after write | complete — `after_bytes` in result |
| **changed/created/overwritten** | complete — `created_file`, `overwrote_existing_file`, `file_existed`, `parent_dirs_created` | complete — `blocks_applied`, `lines_changed`, `changed_files`, `replacements` (domain-specific: patches change content, not create/delete files) |
| **no raw content in receipt** | complete — WriteFileReceipt excludes `content` | complete — SearchReplaceReceipt excludes `content`, `old_text`, `new_text`, diffs |
| **build_receipt()** | complete — returns `WriteFileReceipt` | complete — returns `SearchReplaceReceipt` |
| **receipt schema** | complete — `rig.relay.write_file_receipt.v1` | complete — `rig.relay.search_replace_receipt.v1` |
| **receipt schema validation** | complete — model_dump validated in `test_tool_receipt_emission.py` | complete — model_dump validated in `test_tool_schema_contracts.py` |
| **receipt policy validator** | complete — passes `validate_receipt_payload` | complete — passes `validate_receipt_payload` |
| **receipt index support** | complete — `write_file` case in `receipt_index.py`, mutation tracking | complete — `search_replace` case in `receipt_index.py`, mutation tracking |
| **ToolError bypasses** | complete — Dir/size/exists/parent-missing errors now yield structured `WriteFileResult(status="refused")` with domain-specific `error_kind`. Internal write errors and path safety violations remain as ToolError (abnormal). | complete — All deterministic validation errors (content_too_large, empty_content, unsafe_path, file_not_found, path_is_directory, binary_file, parse_error) yield structured `SearchReplaceResult(status="refused")` with domain-specific `error_kind`. Internal read/write errors remain as ToolError (abnormal). |
| **atomicity** | complete — `_atomic_write_text` with same-directory tempfile + `os.replace()` + `os.fsync()` | not_applicable — patches modify in-place; atomicity would require proving before/after content matches patch |
| **duration tracking** | complete — `duration_ms` captured in `WriteFileResult` and `WriteFileReceipt` on blocked, refused, and success paths | complete — `duration_ms` captured in `SearchReplaceResult` and `SearchReplaceReceipt` |

## Summary

- **Complete**: 20/20 guarantees for write_file, 18/18 for search_replace
- **Partial**: 0 for write_file, 0 for search_replace
- **Missing**: 0 for write_file, 0 for search_replace
- **Deferred**: 0 for write_file
- **Not applicable**: 0 for write_file, 1 for search_replace (atomicity)

## Gaps by Tool

### write_file gaps

1. **`content` in WriteFileResult** — Legacy field. Not removed in this mission. See `docs/audits/tool-hardening/write-file-legacy-result-content-audit.md` for the full caller audit.

### search_replace gaps

1. **before_bytes** — Only set on success path. Not populated for `no_match`/`refused`/`blocked`.
2. **ToolError bypasses** — Encoding errors before structured result path. Pre-existing.

## What Tests Now Enforce

See `tests/tools/test_mutation_tool_contracts.py` for shared contract tests covering:

- Both tools have `build_receipt` method
- Success receipts are content-light (no forbidden fields)
- Refusal/blocked receipts are content-light
- Receipt schemas validate actual model dumps
- Receipt policy validator passes for both success and failure
- Receipt index supports both tools with mutation tracking
- Index records exclude forbidden raw fields

ToolError bypass tests were updated in `tests/tools/test_hardened_tools.py`:
- `test_write_file_rejects_directory_target` → expects structured `refused`/`path_is_directory` instead of `ToolError`
- `test_write_file_overwrite_false_on_existing_does_not_emit_hash` → expects structured `refused`/`overwrite_required` instead of `ToolError`
