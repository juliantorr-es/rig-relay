# SubagentRuntime Governed Tool Path — Verification

**Date**: 2026-05-17
**Status**: ✅ Already implemented. Verified, confirmed, readiness tests added.

## Repo Truth

The current repo **already has** SubagentRuntime routed through ToolRuntime. No implementation was needed. This slice adds readiness proof tests and confirms the existing implementation is complete.

## Implementation Status

| Requirement | Status | Evidence |
|---|---|---|
| SubagentRuntime accepts `tool_runtime=` | ✅ | Constructor has `tool_runtime: Any \| None = None` |
| Governed path routes through ToolRuntime | ✅ | `_execute_tool_call_governed()` calls `execute_and_format(self._tool_runtime, ...)` |
| Legacy path is explicit fallback | ✅ | Comment: "fallback only when no ToolRuntime" |
| `tool_execution_mode` set correctly | ✅ | `"tool_runtime"` when provided, `"legacy_direct"` otherwise |
| task.py passes `tool_runtime=` | ✅ | `tool_runtime=getattr(ctx, "tool_runtime", None)` |
| Envelope evidence preserved | ✅ | `SubagentToolResult` carries `supervisor_envelope_id`, `supervisor_envelope_sha256`, `supervisor_classification` |
| SubagentToolResult extracts from ToolRuntimeResult | ✅ | `result.supervisor_result_envelope_id` → `SubagentToolResult.supervisor_envelope_id` |
| No AgentLoop in subagent | ✅ | Guard test `test_subagent_runtime_never_constructs_agent_loop` |
| No direct tool run in subagent | ✅ | Guard test `test_subagent_runtime_has_no_direct_tool_run` |
| ToolRuntime span finalization | ✅ | All 8 terminal paths covered (prior slice) |
| Envelope SHA is real content hash | ✅ | `sha256:<64 hex>` (prior slice) |

## Readiness Tests Added

`tests/core/test_subagent_runtime_tool_runtime_readiness.py` (7 tests):

| Test | Proves |
|---|---|
| `test_task_py_passes_tool_runtime_to_subagent_runtime` | Production wiring exists |
| `test_subagent_runtime_constructor_accepts_tool_runtime` | Constructor has the parameter |
| `test_governed_path_uses_execute_one` | Governed path exists |
| `test_tool_execution_mode_set_to_tool_runtime_when_provided` | Mode tracking in metadata |
| `test_no_legacy_direct_as_default` | Legacy is fallback, not default |
| `test_subagent_tool_result_carries_envelope_fields` | Result model carries envelope |
| `test_execute_and_format_extracts_envelope_from_tool_runtime_result` | Passthrough from ToolRuntimeResult |

## Evidence Propagation Chain

```
SubagentRuntime._execute_tool_call_governed()
  → tool_adapter.execute_and_format(tool_runtime, call)
    → ToolRuntime.execute_one(request)
      → ToolRuntime._execute_governed()
        → subprocess runner
        → extracts supervisor_result_envelope{_id,_sha256,_classification}
        → returns ToolRuntimeResult with envelope fields populated
    → SubagentToolResult(
        supervisor_envelope_id=result.supervisor_result_envelope_id,
        supervisor_envelope_sha256=result.supervisor_result_envelope_sha256,
        supervisor_classification=result.supervisor_result_classification,
      )
  → LLMMessage(role=tool, content=result.output_text) appended to messages
```

## Guard Tests (existing, 28 tests)

| Test | Purpose |
|---|---|
| `test_task_py_never_constructs_agent_loop` | AST proof: no AgentLoop in task.py |
| `test_subagent_runtime_never_constructs_agent_loop` | AST proof: no AgentLoop in subagent |
| `test_ralph_never_constructs_agent_loop` | AST proof: Ralph is read-only |
| `test_subagent_runtime_has_no_direct_tool_run` | AST proof: no `.run()` bypass |
| `test_legacy_path_is_marked_not_default` | Legacy is explicitly fallback |
| `test_governed_path_is_primary` | Governed path is primary |

## Validation

| Command | Result |
|---|---|
| `pytest tests/core/test_subagent_runtime_*.py -q` | 35 passed |
| `ruff check` touched files | All checks passed |
| `pyright` touched files | 0 errors |
| `collect-only` | 6306 tests, 0 errors |
| `demo-doctor` | 22/22 |

## Phase 3 Readiness

ToolRuntime direct path and SubagentRuntime governed path are **both complete**. The runtime evidence spine now:

1. ToolRuntime extracts envelope evidence from subprocess results ✓
2. ToolRuntime populates ToolRuntimeResult with envelope id/sha/classification ✓
3. All ToolRuntime terminal paths close trace spans ✓
4. SubagentRuntime routes tool calls through ToolRuntime ✓
5. SubagentRuntime extracts envelope evidence from ToolRuntimeResult ✓
6. Envelope evidence reaches SubagentResult metadata ✓

**Phase 3 (ConversationRuntime.execute_turn)** is unblocked. The tool execution spine is governed end-to-end.
