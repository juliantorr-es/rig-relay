# Phase 3 Readiness Reconciliation

Reconciliation date: 2026-05-15
Inspected HEAD: 2b73610

## Repo truth table — actual state by file

| File | Claim | **Actual truth** |
|---|---|---|
| `rig_relay/core/subagents/runtime.py` | "legacy_direct only" | **Partially stale.** Constructor accepts `tool_runtime: Any | None` param. When provided, dispatches to `_execute_tool_call_governed()` which calls `tool_adapter.execute_and_format()`. When absent, falls back to `_execute_tool_call_legacy()`. `tool_execution_mode` reflects this at construction time. |
| `rig_relay/core/subagents/tool_adapter.py` | "adapter exists" | **Exists.** `execute_and_format()` builds a `ToolRuntimeRequest`, calls `runtime.execute_one()`, captures envelope fields (`supervisor_envelope_id`, `_sha256`, `_classification`) into `SubagentToolResult`. Clean adapter — no AgentLoop or forbidden imports. |
| `rig_relay/core/tools/builtins/task.py` | "still uses AgentLoop(is_subagent=True)" | **Stale.** Task.py imports `SubagentMission`, `SubagentResult`, `SubagentRuntime`. `_collect_subagent_output()` constructs `SubagentRuntime(mission, tool_runtime=getattr(ctx, "tool_runtime", None))`. Passes `tool_runtime` from `InvokeContext` if available. Zero `is_subagent` references remaining. |
| `rig_relay/core/tool_runtime.py` | "spans not closed" | **Stale.** 8 `_finalize_span()` calls cover all 8 early-return paths. 9th path (success) uses inline `recorder.end_span()`. All 9 return paths close the trace span. Envelope fields (`supervisor_result_envelope_id`, `_sha256`, `_classification`) populated in success path from result model. |
| `rig_relay/core/tool_runtime_models.py` | "envelope fields missing" | **Stale.** `ToolRuntimeResult` has `supervisor_result_envelope_id`, `supervisor_result_envelope_sha256`, `supervisor_result_classification` since the push. |
| `rig_relay/core/tool_subprocess.py` | "envelope fields missing" | **Stale.** `ToolSubprocessResult` has `supervisor_result_envelope`, `supervisor_result_envelope_sha256`, `supervisor_result_classification` since the push. |
| `rig_relay/runtime/supervisor_invoker.py` | "result_id placeholder as SHA" | **Fixed.** `_envelope_sha256()` helper computes actual `sha256:<64 hex>` over canonical JSON serialization. Runner populates all three envelope fields from invoker result. |
| `rig_relay/desktop/correlation.py` | "DesktopCorrelation privacy fix applied" | **Stale.** File only has `new_correlation_id()` — correlation ID generation. No `_safe_details()` or path sanitization. Desktop privacy is **not** implemented here. |
| `rig_relay/desktop/websocket_server.py` | "integrated with DesktopCorrelation" | **Stale.** No `DesktopCorrelation`, `correlation_id`, `TraceRecorder`, or `start_span` references. WebSocket is **not** integrated with the correlation utility. |
| `rig_relay/core/conversation_runtime/runtime.py` | "owns loop policy" | **Accurate.** Docstring correctly states: "Today it observes while AgentLoop retains loop policy." AgentLoop still owns the while-loop in `_conversation_loop()`. |
| `docs/audits/agent-loop/conversation-runtime-extraction-plan.md` | "Phase 2B complete, Phase 3 future" | **Accurate.** Phase 2B decisions moved. Phase 3 marked as Future. |

## Conflicting report resolution

| Report claim | Resolution |
|---|---|
| "SubagentRuntime still bypasses ToolRuntime, uses legacy_direct" | **Stale.** Runtime dispatches based on `_tool_runtime` parameter. Task tool passes `tool_runtime` from context when available. The default IS legacy_direct (when no ToolRuntime is provided), but this is by design — SubagentRuntime doesn't own ToolRuntime construction. |
| "DesktopCorrelation privacy fix applied, raw frontend_dir removed" | **Stale.** `correlation.py` only provides ID generation. No path sanitization exists. WebSocket does not integrate with it. |
| "Phase 3 is one gate away" | **Stale.** Phase 3 is still blocked. ConversationRuntime remains an observer. AgentLoop still owns the while-loop. SubagentRuntime defaults to legacy_direct when ToolRuntime is absent. Desktop has no correlation integration. |

## Phase 3 decision: NOT READY

### Exact blockers

| # | Blocker | Evidence |
|---|---|---|
| 1 | **ConversationRuntime still observer, not loop owner** | AgentLoop still owns `_conversation_loop()` while-loop; ConversationRuntime docstring says "today it observes" |
| 2 | **SubagentRuntime defaults to legacy_direct** when ToolRuntime absent | Runtime.py constructor: `_tool_execution_mode = "legacy_direct" if tool_runtime is None else "tool_runtime"`. Production task tool passes `getattr(ctx, "tool_runtime", None)` — if context lacks it, side tunnel opens. |
| 3 | **Desktop correlation not integrated** | `correlation.py` is ID-only. WebSocket has no correlation integration. |
| 4 | **No SubagentRuntime lifecycle evidence emission in production** | Runtime has `_emit_start()` / `_emit_end()` methods but they require `_trace_recorder` which task tool does not provide. |

### Required blocker slice

**SubagentRuntime ToolRuntime Default + Desktop Wiring v1**

Not a full Phase 3. A small gate-closing slice:

1. Make `SubagentRuntime` require or construct a `ToolRuntime` by default (no silent legacy_direct fallback in production). Legacy path becomes test-only.
2. Wire `tool_runtime` into `InvokeContext` in desktop cockpit (the production orchestrator).
3. Wire `trace_recorder` into `InvokeContext` so SubagentRuntime lifecycle evidence is emitted.
4. Integrate `correlation_id` into WebSocket lifecycle (or document the gap explicitly).

Only after these three wiring seams are closed should Phase 3 begin loop transfer.
