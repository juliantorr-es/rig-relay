# SubagentRuntime v1 — Evidence and Tool Execution Mode

Implementation date: 2026-05-15

## What changed from v0

| Area | v0 | v1 |
|---|---|---|
| Lifecycle evidence | None | `TraceRecorder` start/end/cancel/error/budget |
| Tool execution mode | Hidden (direct ToolManager) | Explicit `tool_execution_mode: "legacy_direct"` in result metadata and trace |
| Parent trace propagation | Stored in mission only | Emitted in span attributes |
| Timestamp handling | `time.monotonic()` used as wall clock (bug) | `started_at` = `datetime.now(UTC)`, `duration_ms` = monotonic delta |
| Trace recorder | Not accepted | Optional `trace_recorder` parameter |

## Events emitted

| Event | When | TraceRecorder API |
|---|---|---|
| `subagent.runtime` span | Mission starts | `recorder.start_span()` |
| span end (ok) | Normal completion | `recorder.end_span(status=ok)` |
| span end (cancelled) | Cancelled | `recorder.end_span(status=cancelled)` |
| span end (error) | Runtime error | `recorder.end_span(status=error, error=...)` |
| `subagent.runtime.budget.exhausted` | Budget exceeded | `span.event()` |

## What SubagentRuntime owns now

- Bounded mission execution
- **Lifecycle evidence emission** (v1)
- **Explicit tool execution mode** (v1)
- Budget enforcement
- Structured result artifact

## What still belongs to OrchestratorLoop

- User-facing turn orchestration
- Approval policy
- Final synthesis
- Merge/push

## What remains before ToolRuntime adoption

Tool execution still goes through direct `ToolManager.get()` / `tool_inst.run()`.
This is marked as `tool_execution_mode: "legacy_direct"` in both result metadata
and trace span attributes so there are no invisible side tunnels.

The full ToolRuntime adapter (with permission, approval, cache, receipt pipeline)
requires the AgentLoop adapter closures. A future slice should:

1. Extract minimal ToolRuntime adapter helpers
2. Wire SubagentRuntime tool calls through `ToolRuntime.execute_one()`
3. Change `tool_execution_mode` to `"governed"`
