# Bash Deterministic Tool Envelope

## Why Bash is First

Local Relay tool usage audit (`/Users/user/.rig/relay`) evidence:

| Metric | Value |
|--------|-------|
| Total calls | 5,023 |
| Failures | 337 |
| Failure rate | ~6.71% |
| Risk tier | 3 (highest) |
| p95 latency | ~10,469 ms |
| p95 output | ~8,012 bytes |
| Observed exposure | subprocess, Git, network |

Bash dominates both usage and risk. SearchReplace has a higher failure rate
(~10.55%) but lower total calls (2,057) and lower authority. WriteFile has
lower failure rate (~4.1%) but higher authority. Bash is the right first
hardening target because it combines high call volume, high failure count,
p95 latency >10 s, and direct subprocess/network exposure.

## Current Implementation Findings

File: `vibe/core/tools/builtins/bash.py`

### What existed before hardening

- **`BashArgs`**: `command: str`, `timeout: int | None`
- **`BashResult`**: `command: str`, `stdout: str`, `stderr: str`, `returncode: int`
- **`BashToolConfig`**: permission allowlist/denylist, `max_output_bytes`, `default_timeout`
- **Permission system**: arity-based session patterns, outside-directory detection, find-exec predicates
- **Timeout**: Raised `ToolError` on timeout (counted as failure)
- **Output truncation**: Single `max_output_bytes` applied after decode, no truncation flags
- **Refusal**: `resolve_permission` returned `NEVER` for denylist matches
- **Git guard**: `get_guard().is_destructive_git_command()` raises `ToolError` on destructive commands

### What was missing

1. No structured result status — `success`/`failure`/`timed_out`/`refused`/`truncated`
2. No `duration_ms` in result — latency tracked only at the agent-loop level
3. No `stdout_truncated`/`stderr_truncated` flags — silent truncation
4. No `error_kind` — error classification was only in `ToolError` message text
5. No `refusal_reason` — refusal signaled only through permission context
6. No per-stream byte caps — single shared `max_output_bytes`
7. No content-light receipt — receipts contained raw stdout/stderr
8. No schema files — bash invocation/result/receipt schemas did not exist
9. Timeout raised `ToolError` instead of yielding structured result
10. No `cwd` field on args — working directory was always implicit

## Implemented Guardrails

| Guardrail | Mechanism |
|-----------|-----------|
| Structured status | `BashResult.status` ∈ {`success`, `failure`, `timed_out`, `refused`, `truncated`} |
| Duration tracking | `time.perf_counter()` before/after subprocess, yields `duration_ms` |
| Truncation flags | `stdout_truncated`, `stderr_truncated` booleans in result |
| Per-stream byte caps | `BashArgs.max_stdout_bytes`, `max_stderr_bytes` override config |
| Error classification | `error_kind` ∈ {`nonzero_exit`, `timeout`, `refused`, `internal_error`} |
| Refusal reason | `refusal_reason` string on refused/timed-out results |
| Content-light receipts | `BashReceipt` model — SHA256 hashes, byte counts, no raw output |
| Explicit cwd | `BashArgs.cwd` for deterministic working directory |
| Structured timeout | `yield BashResult(status="timed_out")` instead of `raise ToolError` |
| Schema validation | 3 new JSON schemas for invocation, result, and receipt |

### Backward Compatibility

- All new `BashResult` fields are optional with defaults
- Old constructor `BashResult(command=..., stdout=..., stderr=..., returncode=...)` still works
- Non-zero exit still raises `ToolError` via `_build_result` (preserves existing behavior)
- `BashArgs` new fields (`cwd`, `max_stdout_bytes`, `max_stderr_bytes`) are optional
- `run()` signature unchanged — still yields `BashResult`
- `BashReceipt` is a new additive model, not required

## Remaining Gaps

1. **No-shell/argv mode**: The tool always uses `create_subprocess_shell`. A future hardening pass should add an `argv` mode for commands that don't need shell features.
2. **No explicit command classification**: The `BashArgs` model has no `intent` or `category` field. This would require cross-cutting changes to how tools declare their intent.
3. **Guard channel**: The `get_guard().is_destructive_git_command()` gate exists but the guard behavior is context-dependent (no-op outside git repos). This should become more deterministic.
4. **Environment filtering**: The current approach inherits the full `os.environ` with a few overrides. A future pass should explicitly enumerate permitted env vars.
5. **Receipt integration**: `BashReceipt` is constructed via `build_receipt()` and emitted as a `rig.relay.tool_receipt.captured` event via `capture_tool_receipt()` in the agent loop's `_execute_tool()` method. See `tests/tools/test_tool_receipt_emission.py` for emission tests.

## Follow-Up Migration Plan

1. **Short term** (this mission): Deterministic envelope in place. Tests passing. Schemas defined.
2. **Completed**: `BashReceipt` emission wired into agent loop via `capture_tool_receipt()` helper. Content-light receipt policy validator (`rig_relay/evidence/tool_receipt_policy.py`) with 21 tests and CLI validation script. Event `rig.relay.tool_receipt.captured` added to `EventName`. Tests in `tests/tools/test_tool_receipt_emission.py`.
3. **Medium term**: Add `argv` execution mode for commands that don't need shell expansion.
4. **Long term**: Replace raw agent `bash` calls with determinism-managed envelope for all subprocess tools (grep, git, checkpoint). Add `command_classification` to args for finer-grained permission control.
5. **Continuous**: Monitor the audit aggregates. As new tool-usage data accumulates, re-run `scripts/analyze_relay_tool_usage.py` and compare failure rates against this baseline.

## Schema Files

- `docs/schemas/rig.relay.bash_invocation.v1.schema.json` — request envelope
- `docs/schemas/rig.relay.bash_result.v1.schema.json` — result with output
- `docs/schemas/rig.relay.bash_receipt.v1.schema.json` — content-light receipt

## Test Coverage

Tests in `tests/tools/test_bash_hardening.py` (23 new tests):

| Category | Tests |
|----------|-------|
| Structured result model | 2 (fields on success, failure raises ToolError) |
| Timeout behavior | 1 (structured timed_out result) |
| Output bounding | 4 (stdout truncation, stderr truncation, per-stream override, no truncation) |
| Content-light receipt | 3 (no raw output, timed-out receipt, SHA256 diffs) |
| cwd handling | 2 (explicit cwd, default cwd) |
| Environment safety | 2 (noninteractive flags, no env leak to receipt) |
| Refusal behavior | 1 (denylist refusal) |
| Duration tracking | 1 (milliseconds) |
| Status field values | 2 (success, failure) |
| Backward compatibility | 1 (BashResult defaults) |
| BashReceipt construction | 2 (minimal, truncation) |

Plus updated `test_handles_timeout_structured_result` in existing `tests/tools/test_bash.py`.

### Tool Receipt Content-Light Policy Validator (`rig_relay/evidence/tool_receipt_policy.py`)

Reusable validator module that checks emitted tool receipt events against content-light policy:

| Category | Mechanism |
|----------|-----------|
| Forbidden key detection | Recursive walk of receipt dict, exact field-name match against `_FORBIDDEN_RECEIPT_FIELDS` |
| Allowed metadata passthrough | Skips `_ALLOWED_METADATA_FIELDS` (e.g. `stdout_sha256`, `stdout_bytes`) |
| Value-shape heuristics | Flags strings >256 bytes, unified diff markers (`--- `, `+++ `, `@@ `), >10 newlines |
| Event-level validation | `validate_event()` — ignores non-receipt events |
| File-level validation | `validate_file()` — parses JSONL, validates each receipt event |

Tests in `tests/evidence/test_tool_receipt_policy.py` (21 tests):

| Category | Tests |
|----------|-------|
| Valid receipt passes | 1 (BashReceipt with hashes, no raw output) |
| Allowed metadata | 1 (stdout_sha256, stderr_bytes, etc. not rejected) |
| Forbidden fields | 7 (stdout, stderr, old, new, diff, snippet, replacement, patch, context, command_output) |
| Nested fields | 1 (forbidden fields in nested dicts) |
| Unrelated events | 2 (ignored, malformed but unrelated tolerated) |
| Malformed receipts | 2 (missing payload, non-dict receipt) |
| Value-shape heuristics | 2 (large strings, diff markers) |
| File-level validation | 4 (clean, violations, malformed unrelated, multiple violations) |
| Edge cases | 2 (empty receipt, non-dict receipt value) |

Read-only CLI script at `scripts/rig_relay_validate_tool_receipts.py`:
- Accepts a JSONL file path or session directory
- Exits 0 (pass), 1 (violations), or 2 (file not found)
- Usage: `uv run python scripts/rig_relay_validate_tool_receipts.py <path>`

### Tool Receipt Emission Tests (`tests/tools/test_tool_receipt_emission.py`)

| Category | Tests |
|----------|-------|
| Helper emits event | 1 (capture_tool_receipt writes to JSONL) |
| Content-light receipt | 1 (no raw stdout/stderr in payload) |
| Failure-safe | 1 (helper does not raise on invalid input) |
| Bash has build_receipt | 1 (duck-type check) |
| Success receipt | 1 (content-light fields, hashes, no raw output) |
| Timeout receipt | 1 (content-light timeout receipt) |
| Refusal receipt | 1 (content-light refusal receipt) |
| Full integration | 1 (build → emit → verify event) |
| No-raise guarantee | 1 (emission does not break tool execution) |
