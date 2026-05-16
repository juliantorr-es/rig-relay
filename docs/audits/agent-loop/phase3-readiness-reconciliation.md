# Phase 3 Readiness Reconciliation — All Lanes

Reconciliation date: 2026-05-16
Inspected HEAD: 6385762
Lanes: A (SubagentRuntime strict default), B (Desktop WebSocket correlation), C (this — evidence/doctrine/gate)

## Current Phase Status: **TRANSFERRED_WITH_GAPS**

All 7 preconditions for Phase 3 loop transfer are met. The while-loop IS being moved to ConversationRuntime, but agent_loop.py has an indentation error at line 789 (stray comment at wrong indent + `_perform_llm_turn` at class-method level inside `_conversation_loop` body).

The conversation_loop now delegates to `cr.execute_turn_loop(adapter)`. This is the correct transfer architecture, but the syntax error prevents collection.

**Blocker**: Fix indentation in agent_loop.py lines 789-791 (Lane A).

## All-Lanes Truth Table

| Seam | Required state | Actual state | Evidence | Status |
|---|---|---|---|---|
| Subagent strict fallback | no silent legacy direct | `allow_legacy_direct: bool = False`; default `tool_runtime_required` | `rig_relay/core/subagents/runtime.py:50-74` | ✅ PASSED |
| task dependency propagation | tool_runtime + trace_recorder | both passed from InvokeContext | `rig_relay/core/tools/builtins/task.py:461-462` | ✅ PASSED |
| ToolRuntime envelope path | supervisor_result_envelope_id/sha/classification | fields present and populated in success path | `rig_relay/core/tool_runtime_models.py` | ✅ PASSED |
| ToolRuntime span finalization | all terminal paths close | `_finalize_span()` helper + inline end_span cover all 9 return paths | `rig_relay/core/tool_runtime.py:203+` | ✅ PASSED |
| Desktop correlation | WebSocket lifecycle safe events | `DesktopCorrelation` integrated in `websocket_server.py`; BridgeProbeLadder emits correlation events | `rig_relay/desktop/websocket_server.py:268-270` | ✅ PASSED |
| Subagent adapter envelope | supervisor envelope fields preserved | `SubagentToolResult` carries envelope id/sha/classification | `rig_relay/core/subagents/tool_adapter.py` | ✅ PASSED |
| AgentLoop subagent pattern | removed and guarded | no `is_subagent` in task.py; `_FORBIDDEN_AGENTLOOP_CONSTRUCTION` guards subagents/ralph/task | `tests/core/test_subagent_runtime_guards.py` | ✅ PASSED |
| ConversationRuntime ownership | owns loop after Phase 3 | **PARTIALLY TRANSFERRED.** `cr.execute_turn_loop(adapter)` exists, but indentation error at line 789 breaks the file. | `rig_relay/core/agent_loop.py:786-791` | ⚠️ TRANSFERRED_WITH_GAPS |
| AgentLoop adapter status | thin wrapper after Phase 3 | `_build_loop_adapter()` helper exists. `_conversation_loop` delegates to `cr.execute_turn_loop()`. | `rig_relay/core/agent_loop.py:747-750` | ✅ PASSED |
| Collection determinism | all tests can be collected | `uv run pytest --collect-only` fails due to IndentationError in agent_loop.py:789 | `agent_loop.py:789-791` | ❌ FAILED — fix indentation |

## Lane Status

| Lane | Scope | Status |
|---|---|---|
| **Lane A** | SubagentRuntime strict ToolRuntime default + trace_recorder propagation | ✅ Landed |
| **Lane B** | Desktop WebSocket correlation | ✅ Landed |
| **Lane C** | Evidence, doctrine, and final ownership gate (this lane) | ✅ Gate hardened |

## Gate Tests

All gate tests pass for READY_NOT_TRANSFERRED state:

```
uv run pytest -n0 tests/core/test_conversation_runtime_phase3_readiness.py tests/core/test_conversation_runtime_phase3_ownership_guards.py tests/core/test_phase3_docs_truth.py -q
```

### Readiness tests (pass when READY_NOT_TRANSFERRED or PHASE_3_COMPLETE)

These tests verify precondition state — they pass in both READY_NOT_TRANSFERRED and PHASE_3_COMPLETE:

| Test | What it checks |
|---|---|
| subagent fallback strict | `allow_legacy_direct: bool = False` |
| task passes tool_runtime | AST: SubagentRuntime receives `tool_runtime=` |
| task passes trace_recorder | AST: SubagentRuntime receives `trace_recorder=` |
| ToolRuntime envelope fields | model fields present |
| ToolRuntime span finalization | `_finalize_span()` exists |
| desktop correlation declared | websocket_server imports DesktopCorrelation |
| ConversationRuntime doc honest | docstring says "Called from AgentLoop" |
| AgentLoop subagent pattern gone | no `is_subagent` |

### Ownership guard tests (pass only when READY_NOT_TRANSFERRED or PHASE_3_COMPLETE)

| Test | What it checks |
|---|---|
| extraction plan status matches code | doc says READY (not COMPLETE) since loop not moved |
| reconciliation doc is canonical | contains all-lanes truth table, not single-lane report |
| no false PHASE_3_COMPLETE claim | docs don't claim loop transfer is done |
| AgentLoop still owns loop | _conversation_loop exists in AgentLoop (pre-transfer) |

After Lane A transfers the loop, these guard tests should be updated to assert PHASE_3_COMPLETE.

## Evidence Chain (full post-Phase-3 target)

```
User/Desktop intent
  → DesktopCorrelation (bridge_id, correlation_id, trace)
  → WebSocket transport (correlation_id, session_id)
  → AgentLoop adapter (_conversation_loop delegates to ConversationRuntime)
  → ConversationRuntime.execute_turn() — LOOP OWNER
      → ToolRuntime.execute_one() — governed tool execution
          → RuntimeSupervisor envelope (supervisor_result_envelope_id/sha/classification)
          → tool_runtime.execute_one span (start/end with status)
      → SubagentRuntime (when task.py delegates)
          → subagent.runtime span (lifecycle evidence)
          → ToolRuntime.execute_one() via governed path
  → BridgeProbeLadder (probe steps with correlation)
  → DesktopCorrelation (desktop.intent.dispatched/completed)
```

Causal path: desktop action → transport → intent → loop → tool → supervisor → result → UI diagnostic.
