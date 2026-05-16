# Phase 3 Readiness Reconciliation — Lane A Report

**Date**: 2026-05-17
**Lane**: A — SubagentRuntime Strict ToolRuntime Default and Trace Wiring

## Changes Made

### 1. SubagentRuntime — strict default

**File**: `rig_relay/core/subagents/runtime.py`

| Change | Detail |
|---|---|
| Added `allow_legacy_direct: bool = False` parameter | Legacy direct is explicit opt-in, never silent default |
| Added `tool_runtime_required` execution mode | When ToolRuntime is missing and allow_legacy_direct=False |
| Legacy path guarded by `self._allow_legacy_direct` | No execution without explicit opt-in |
| Structured refusal when ToolRuntime missing | `ToolRuntime required for 'X' — subagent constructed without tool_runtime= and allow_legacy_direct=False` |
| `legacy_direct_allowed` in result metadata | Boolean in metadata dict |

### 2. Task.py — pass trace_recorder

**File**: `rig_relay/core/tools/builtins/task.py`

```python
runtime = SubagentRuntime(
    mission,
    tool_runtime=getattr(ctx, "tool_runtime", None) if ctx else None,
    trace_recorder=getattr(ctx, "trace_recorder", None) if ctx else None,
    allow_legacy_direct=False,
)
```

### 3. Updated pre-existing tests

| File | Change |
|---|---|
| `tests/core/test_subagent_runtime_guards.py` | `test_legacy_path_is_marked_not_default` — accepts both old and new comment text |
| `tests/core/test_subagent_runtime_tracing.py` | `test_legacy_direct_mode_is_default` → `test_tool_runtime_required_when_no_tool_runtime_no_legacy` |
| `tests/core/test_subagent_runtime_tracing.py` | `test_mode_appears_in_result_metadata` — now checks `tool_runtime_required` + `legacy_direct_allowed=False` |
| `tests/core/test_subagent_runtime_tool_runtime_readiness.py` | `test_no_legacy_direct_as_default` — accepts both old and new text |

### 4. New test file

`tests/core/test_subagent_runtime_pre_phase3_wiring.py` — 16 tests covering:
- Strict default mode (7 AST proofs)
- Task production wiring (3 AST proofs)
- Lifecycle evidence (3 behavioral)
- Guards (3 AST proofs)

## Fallback Policy

| Condition | `tool_execution_mode` | Tool execution |
|---|---|---|
| `tool_runtime` provided | `tool_runtime` | Governed via `execute_and_format` → `ToolRuntime.execute_one()` |
| `tool_runtime=None`, `allow_legacy_direct=False` | `tool_runtime_required` | **Refused** — structured error message, no tool execution |
| `tool_runtime=None`, `allow_legacy_direct=True` | `legacy_direct` | Legacy `ToolManager.get().run()` (test-only safe hatch) |

## Remaining Phase 3 Blockers

| Blocker | Lane | Status |
|---|---|---|
| SubagentRuntime fallback default | Lane A | ✅ Resolved |
| SubagentRuntime trace_recorder wiring | Lane A | ✅ Resolved |
| ConversationRuntime loop ownership | Phase 3 | Not yet started |
| Desktop WebSocket correlation | Lane B | Separate lane |

## Validation

| Command | Result |
|---|---|
| `pytest tests/core/test_subagent_runtime_*.py -q` | 51 passed |
| `ruff check` touched files | All checks passed |
| `pyright` touched files | 1 pre-existing error (task.py:714, unrelated) |
| `collect-only` | 6345 tests, 0 errors |
| `demo-doctor` | 22/22 |

## Follow-up

**Phase 3 — ConversationRuntime.execute_turn()** — The subagent execution spine is now governed end-to-end with strict ToolRuntime default, trace recording, and no silent legacy fallback. Phase 3 loop ownership transfer is unblocked.
