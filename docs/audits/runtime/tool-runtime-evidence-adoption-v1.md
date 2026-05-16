# ToolRuntime Direct Path Envelope Population v1 — Audit

**Date**: 2026-05-17

## Current State

| Area | Before | After |
|---|---|---|
| Desktop correlation privacy | Fixed (prior slice) | Fixed |
| ToolRuntime success path envelope population | Already working (lines 449-464) | Working |
| Span closure on early returns | 6 of 8 paths missing `end_span()` | All 8 paths covered |
| ToolRuntimeResult model fields | Present | Present |
| Runtime intent path | Already working | Working |

## Direct Path Envelope Population

The success path in `ToolRuntime._execute_governed()` already extracts and propagates supervisor envelope metadata (lines 449-464):

```python
supervisor_result_envelope_id=(
    supervisor_result.get("result_id") if supervisor_result else None
),
supervisor_result_envelope_sha256=supervisor_result_sha256,
supervisor_result_classification=supervisor_result_classification,
```

Extraction logic (lines 449-459):
- `supervisor_result` from `result_model.supervisor_result_envelope`
- `supervisor_result_sha256` from `result_model.supervisor_result_envelope_sha256`
- `supervisor_result_classification` from `result_model.supervisor_result_classification`
- Falls back to envelope dict fields if top-level attrs are None

## Span Finalization Fix

**Before**: 6 early-return paths left trace spans open (dangling spans).

| Return Path | Span Closed Before | Span Closed After |
|---|---|---|
| Cache hit | ✅ | ✅ |
| Permission refused | ❌ | ✅ (`status_str="refused"`) |
| Approval refused | ❌ | ✅ (`status_str="refused"`) |
| Patch gate refused | ❌ | ✅ (`status_str="refused"`) |
| ToolPermissionError | ❌ | ✅ (`status_str="refused"`) |
| Invocation exception | ❌ | ✅ (`status_str="error"`) |
| No result | ❌ | ✅ (`status_str="error"`) |
| Success | ✅ | ✅ |

**Fix**: Added `_finalize_span()` helper (lazy evaluating, handles None trace_status cleanly). All 7 terminal return paths now call it.

## Classification Mapping

| Supervisor Classification | Trace Status | ToolRuntime Status |
|---|---|---|
| `completed` | `ok` | `COMPLETED` (or `DEGRADED` if cache/context failures) |
| `cancelled` | `cancelled` | `COMPLETED` (or `FAILED` if subprocess had errors) |
| `timed_out` | `timed_out` | `TIMED_OUT` |
| `refused` | `refused` | `REFUSED` |
| `killed` | `error` | `FAILED` |
| `spawn_failed` | `error` | `FAILED` |
| `cleanup_failed` | `error` | `FAILED` or `DEGRADED` |
| `errored` | `error` | `FAILED` |
| (no supervisor) | `degraded` or `error` | `DEGRADED` or `COMPLETED` |

Original classification preserved in `supervisor_result_classification` field regardless of mapping coarseness.

## Privacy Model

The following fields are **never** emitted into ToolRuntime trace spans, result dicts, or receipt envelope:
- Raw stdout, stderr, argv, cwd, env, shell command
- Frontend paths, URLs
- Auth tokens, API keys
- Raw exception repr strings (truncated to 500 chars for error_message)

Allowed in trace/receipt: envelope id, envelope sha, classification, byte counts, hashes, safe refusal/error kind, duration, tool name, tool call id.

## Files Changed

| File | Change |
|---|---|
| `rig_relay/core/tool_runtime.py` | Added `_finalize_span()` helper; wired to all 7 early-return paths |

## Validation

| Command | Result |
|---|---|
| `pytest tests/core/test_tool_runtime.py -q` | 13 passed |
| `ruff check rig_relay/core/tool_runtime.py` | All checks passed |
| `pyright rig_relay/core/tool_runtime.py` | 0 errors, 0 warnings |
| `demo-doctor` | 22/22 |
| `collect-only` | 6274 tests, 0 errors |

## Deferred

- **SubagentRuntime envelope consumption** — can now proceed since ToolRuntime direct path populates envelope fields. SubagentRuntime routes tool calls through ToolRuntime and will find the fields populated.
- **Validate envelope consumption** — deferred.
- **Frontend JS trace display** — deferred.

## Follow-up

**SubagentRuntime ToolRuntime Adoption v2** — route SubagentRuntime tool calls through ToolRuntime and consume envelope evidence.
