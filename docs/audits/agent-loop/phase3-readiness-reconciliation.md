# Phase 3 Readiness Reconciliation — Canonical All-Lanes Truth Table

Reconciliation date: 2026-05-16
Inspected HEAD: 798a8363
Lanes: A (SubagentRuntime + trace_recorder), B (Desktop WebSocket correlation), C (this — evidence/doctrine/gate)

## Current Phase Status: **TRANSFERRED_WITH_GAPS**

The while-loop has been moved to ConversationRuntime.execute_turn_loop(). AgentLoop delegates via _ConversationLoopAdapter. Collection is green (6394 tests, 0 errors). 29/29 behavior parity tests pass for decision policy, phase sequencing, and privacy.

**One gap remains**: the adapter's `execute_tool_batch()` method is a stub (`if False: yield` at agent_loop.py:1574). ConversationRuntime correctly decides `run_tools` when tool calls are present, but the adapter does not execute them. This is a Lane A implementation gap — the decision machinery is correct but the execution bridge is missing.

## Canonical Truth Table

| Seam | Required state | Actual state | Evidence | Status |
|---|---|---|---|---|
| Subagent strict fallback | no silent legacy direct | `allow_legacy_direct=False`; default `tool_runtime_required` | `runtime.py:50-74` | ✅ PASSED |
| Task dependency propagation | tool_runtime + trace_recorder | both passed from InvokeContext | `task.py:461-462` | ✅ PASSED |
| ToolRuntime envelope path | id/sha/classification | fields present and populated | `tool_runtime_models.py` | ✅ PASSED |
| ToolRuntime span finalization | all terminal paths close | `_finalize_span()` covers 9 return paths | `tool_runtime.py:203+` | ✅ PASSED |
| Desktop correlation | WebSocket lifecycle safe events | `DesktopCorrelation` integrated; BridgeProbeLadder emits | `websocket_server.py:268-270` | ✅ PASSED |
| Subagent adapter envelope | supervisor envelope fields preserved | `SubagentToolResult` carries id/sha/classification | `tool_adapter.py` | ✅ PASSED |
| AgentLoop subagent pattern | removed and guarded | no `is_subagent`; guards enforce | `test_subagent_runtime_guards.py` | ✅ PASSED |
| ConversationRuntime loop ownership | owns while-loop after Phase 3 | `execute_turn_loop()` owns the while-loop; AgentLoop delegates via adapter | `agent_loop.py:781-782`, `runtime.py:267` | ✅ PASSED |
| AgentLoop adapter status | thin wrapper after Phase 3 | `_ConversationLoopAdapter` with real methods for LLM, hooks, middleware, context | `agent_loop.py:1495-1578` | ✅ PASSED |
| Tool batch adapter | real, not stub | **STUB.** `execute_tool_batch()` is `if False: yield` | `agent_loop.py:1574-1575` | ❌ GAP |
| Behavior parity tests | all pass | **29/29 passed** — decision paths, phase sequencing, privacy, no-forbidden-imports | `test_conversation_runtime_phase3_*` | ✅ PASSED |
| Collection determinism | collect-only green | 6394 tests collected, 0 errors | `uv run pytest --collect-only -q` | ✅ PASSED |
| ConversationRuntime boundary | no forbidden imports | runtime module clean (verified by parity test) | `test_conversation_runtime_phase3_behavior_parity.py` | ✅ PASSED |
| Docs honesty | no false complete claim | Status is TRANSFERRED_WITH_GAPS with exact blocker named | This document | ✅ PASSED |

## Lane Status

| Lane | Scope | Status |
|---|---|---|
| **Lane A** | Loop transfer + adapter | ✅ Landed with 1 gap: `execute_tool_batch()` stub |
| **Lane B** | Desktop WebSocket correlation | ✅ Landed |
| **Lane C** | Evidence, doctrine, ownership gate | ✅ Gate hardened |

## Gap Resolution

**Remaining blocker**: Implement `_ConversationLoopAdapter.execute_tool_batch()` in `rig_relay/core/agent_loop.py`. It should delegate to the existing `_execute_tool_call()` path through ToolRuntime. This is a Lane A implementation slice, not a Lane C concern.

## Gate Tests

```
uv run pytest -n0 tests/core/test_phase3_docs_truth.py tests/core/test_conversation_runtime_phase3_readiness.py tests/core/test_conversation_runtime_phase3_ownership_guards.py -q
uv run pytest -n0 tests/core/test_conversation_runtime_phase3_behavior_parity.py tests/core/test_conversation_runtime_phase3_event_stream.py -q
```

## Evidence Chain

```
User/Desktop intent
  → DesktopCorrelation (bridge_id, correlation_id, trace)
  → WebSocket transport (correlation_id, session_id)
  → AgentLoop adapter (_conversation_loop → cr.execute_turn_loop)
  → ConversationRuntime.execute_turn_loop() — LOOP OWNER
      → ToolRuntime.execute_one() — governed tool execution
          → RuntimeSupervisor envelope (id/sha/classification)
          → tool_runtime.execute_one span (start/end with status)
      → SubagentRuntime (when task.py delegates, via governed ToolRuntime path)
          → subagent.runtime span (lifecycle evidence)
  → BridgeProbeLadder (probe steps with correlation)
  → DesktopCorrelation (desktop.intent.dispatched/completed)
```

Causal path: desktop action → transport → intent → loop → tool → supervisor → result → UI diagnostic.
