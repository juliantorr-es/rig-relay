# WriteFile Receipt Gap Closure

## Current State

WriteFile has partial hardening: structured args, structured result, coordination blocking, dirty guard, before/after hashes, path safety. But before this closure, it was missing:

- WriteFileReceipt model
- `build_receipt()` method
- receipt schema
- receipt emission path
- receipt index support

## Gaps Closed

| Gap | Previous | Current |
|-----|----------|---------|
| WriteFileReceipt model | missing | **implemented** — 16 fields, extra="forbid" |
| `build_receipt()` | missing | **implemented** — content-light, sanitized refusal_reason |
| Receipt schema | missing | **added** — `docs/schemas/rig.relay.write_file_receipt.v1.schema.json` |
| Receipt emission path | missing | **enabled** — `build_receipt()` duck-typing integrated with agent loop |
| Receipt emission tests | missing | **added** — 7 tests in test_tool_receipt_emission.py |
| Receipt policy coverage | missing | **added** — `test_write_file_receipt_passes_policy_validator` |
| Receipt index support | missing | **added** — "write_file" case in `_build_record_from_event` + mutation summary |
| Schema validation tests | missing | **added** — `test_write_file_receipt_schema_validates` |

## WriteFileReceipt Fields

| Field | Type | Content-light? | Notes |
|-------|------|----------------|-------|
| schema_version | str | yes | `rig.relay.write_file_receipt.v1` |
| path | str | yes | File path |
| status | str | yes | success/refused/blocked |
| error_kind | str \| None | yes | Structured classification |
| refusal_reason | str \| None | yes | Sanitized (no content) |
| bytes_written | int | yes | Byte count of written content |
| before_sha256 | str \| None | yes | Hash before write |
| after_sha256 | str \| None | yes | Hash after write |
| before_bytes | int \| None | yes | File size before write (available on success path via snapshot) |
| after_bytes | int \| None | yes | Same as bytes_written |
| file_existed | bool | yes | |
| created_file | bool | yes | |
| overwrote_existing_file | bool | yes | |
| parent_dirs_created | bool | yes | |
| duration_ms | float \| None | yes | Measured in run(). Populated on blocked, refused, and success paths. |

## `build_receipt()` Behavior

- Accepts `WriteFileResult` → returns `WriteFileReceipt`
- Explicitly excludes `content` field from receipt
- Uses `result.after_bytes` directly (file stat after write)
- Uses `result.before_bytes` directly (snapshot content length)
- Uses `result.duration_ms` directly (wall-clock timing from run())
- Sanitizes `refusal_reason` via `_sanitize_refusal_for_receipt()` (currently pass-through, guard does not embed content)

## Remaining Gaps

1. **ToolError bypass paths** — **COMPLETED**: Directory, size, exists, and missing-parent errors now yield structured `WriteFileResult(status="refused")` results instead of raising `ToolError`. See `docs/audits/tool-hardening/write-file-legacy-result-content-audit.md` for the full audit.
2. **`content` still in WriteFileResult** — Legacy callers may depend on it. Safe to remove only after auditing all callers.
3. **`before_sha256` only for success path** — Blocked/refused paths set it to None. This is correct behavior since the guard/snapshot runs before write.
4. **Permission preservation** — Only mode bits (via chmod) are preserved after atomic replace. ACLs/xattrs are dropped.

## Schema Validation

- 79/79 schemas passed (added `rig.relay.write_file_receipt.v1`)
- Receipt schema has `additionalProperties: false` (implicit via draft-07 default)

## Test Coverage

| Test | File |
|------|------|
| `test_write_file_tool_has_build_receipt` | test_tool_receipt_emission.py |
| `test_write_file_success_receipt_content_light` | test_tool_receipt_emission.py |
| `test_write_file_refused_receipt_content_light` | test_tool_receipt_emission.py |
| `test_write_file_blocked_receipt_content_light` | test_tool_receipt_emission.py |
| `test_write_file_receipt_includes_overwrite_fields` | test_tool_receipt_emission.py |
| `test_capture_write_file_receipt_integration` | test_tool_receipt_emission.py |
| `test_write_file_receipt_schema_validates` | test_tool_receipt_emission.py |
| `test_write_file_receipt_passes_policy_validator` | test_tool_receipt_emission.py |

All tests pass: 32 hardened tool tests (3 atomicity + 29 existing) + 42 receipt emission tests (8 write_file + 34 other).

## Atomic Write Implementation

WriteFile now uses an atomic temp-file + replace pattern instead of direct write:

- `_atomic_write_text()` static method on `WriteFile` class
- Uses `tempfile.mkstemp()` for same-directory temp file (ensuring cross-device safety)
- Writes content via `os.write()`, then `os.fsync()` before close
- Preserves existing file mode via `chmod()` if overwriting
- Atomic replace via `os.replace()` (POSIX atomic rename semantics)
- Best-effort parent directory `os.fsync()` for durable persistence
- On failure: cleans up temp file and re-raises
- Called from `_write_file()` via `asyncio.to_thread()` for async compatibility
- Bounded by `max_write_bytes` (64 KB), so synchronous I/O is acceptable

### Atomicity Tests

| Test | What It Verifies |
|------|-----------------|
| `test_write_file_atomicity_failure_preserves_original` | Monkeypatches `os.replace` to fail; verifies original content preserved and temp file cleaned up |
| `test_write_file_atomicity_new_file_timing_and_bytes` | Verifies `duration_ms > 0`, `before_bytes == 0` (new file), `after_bytes == len(content)` |
| `test_write_file_atomicity_overwrite_timing_and_bytes` | Verifies `duration_ms > 0`, `before_bytes == len(original)`, `after_bytes == len(new content)`, hashes match |

## Recommended Next Slice

1. **Stage 4 — Shared Mutation Tool Test Matrix**: **COMPLETED** — see `docs/audits/tool-hardening/mutation-tool-contract-matrix.md` and `tests/tools/test_mutation_tool_contracts.py`.
2. **Duration tracking**: **COMPLETED** — `before_bytes`, `after_bytes`, and `duration_ms` fields added to `WriteFileResult` and `WriteFileReceipt`.
3. **ToolError closure**: **COMPLETED** — 4 deterministic ToolError bypass paths (dir, size, exists, parent-missing) now yield structured `WriteFileResult(status="refused")`. Internal write errors and path safety violations remain as ToolError (abnormal). See `docs/audits/tool-hardening/write-file-legacy-result-content-audit.md` for the caller audit.
