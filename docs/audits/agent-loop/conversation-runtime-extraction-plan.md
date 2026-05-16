# ConversationRuntime extraction plan

Audit dates: 2026-05-15 (Phase 0), 2026-05-15 (Phase 1), 2026-05-15 (Phase 2B)

## Phase progression

| Phase | Status | Description |
|---|---|---|
| Phase 0 | ✅ Complete | Observer/runtime-result seam. |
| Phase 1 | ✅ Complete | Trace evidence (`PhaseTraceHook`, `PhaseTraceAttributes`). |
| Phase 2A | ✅ Complete | Terminal/near-terminal decisions: `decide_after_middleware`, `decide_after_model_turn`, `decide_on_exception`. |
| Phase 2B | ✅ Complete | Hook/tool/budget decisions: `decide_after_hook_processing`, `decide_after_tool_batch`, `decide_after_budget_check`. AgentLoop still holds execution mechanics. |
| Phase 3 | **TRANSFERRED_WITH_GAPS** | Loop ownership transferred. `ConversationRuntime.execute_turn_loop()` owns the while-loop. AgentLoop delegates via `_ConversationLoopAdapter`. 29/29 parity tests pass. One gap: `execute_tool_batch()` is a stub. |

## Phase 2B — Decision policy moved to ConversationRuntime

### Decision methods

| Method | Owns |
|---|---|
| `decide_after_middleware(action)` | STOP → stop_middleware, else continue |
| `decide_after_model_turn(user_cancelled, assistant_final, error)` | stop_cancelled, stop_completed, run_tools, fail_error |
| `decide_on_exception(exc)` | fail_error |
| `decide_after_hook_processing(hook_returned_user_message)` | retry_hooks or stop_completed |
| `decide_after_tool_batch()` | continue_turn |
| `decide_after_budget_check(current_turn, max_turns)` | fail_budget_exceeded or continue_turn |

### Decision kinds

| Kind | should_break | should_run_tools | should_retry_hooks |
|---|---|---|---|
| `continue_turn` | False | False | False |
| `stop_completed` | True | False | False |
| `stop_middleware` | True | False | False |
| `stop_cancelled` | True | False | False |
| `run_tools` | False | True | False |
| `retry_hooks` | False | False | True |
| `fail_error` | True | False | False |
| `fail_budget_exceeded` | True | False | False |

### What stays in AgentLoop

- Hook execution loop (`async for hook_event in self._hooks_manager.run(...)`)
- Hook message injection (`self.messages.append(...)`)
- Tool execution (delegates to ToolRuntime)
- Event yielding
- Middleware execution
- Context building
- LLM turn dispatch

## Current flow (AgentLoop._conversation_loop)

```
act()  →  _conversation_loop()
           ├─ create ConversationTurnRuntime
           ├─ create ConversationRuntime (observer)
           ├─ cr.set_turn_id()
           ├─ append user message → yield UserMessageEvent
           ├─ while not should_break:
           │    ├─ middleware → cr.decide_after_middleware()
           │    ├─ first turn: context build
           │    ├─ _perform_llm_turn()
           │    ├─ cr.decide_after_model_turn()
           │    ├─ stop_cancelled? → return
           │    ├─ stop_completed? → hooks →
           │    │   cr.decide_after_hook_processing()
           │    │   retry_hooks? → inject message, continue loop
           │    ├─ run_tools? → cr.decide_after_tool_batch()
           │    ├─ cr.decide_after_budget_check()
           │    └─ fail_budget_exceeded? → return
           ├─ cr._finish(SUCCESS)
           └─ turn.mark_outcome(SUCCESS)

act() finally:
  ├─ self._conversation_runtime = None
  └─ self._current_turn = None
```

## Phase 3 — Loop ownership transfer (planned)

Phase 3 should move the while-loop into `ConversationRuntime.execute_turn()`,
but with an important distinction:

1. **OrchestratorLoop** (renamed from AgentLoop) is the ONLY owner of a full
   turn loop. Only the desktop cockpit, ACP server, and IDE sidecar should
   instantiate it.

2. **SubagentRuntime v1** is built and now owns lifecycle evidence,
   trace propagation, and explicit tool execution mode markers.
   `task.py` delegates to `SubagentRuntime`, NOT `AgentLoop`.
   The `is_subagent=True` pattern is dead and blocked by guard tests.

3. **RalphRuntime** should use SubagentRuntime with
   `profile_kind=AUTONOMOUS_BACKGROUND` — it must never own a full turn loop.

4. **Handoff receipts** are required for ownership transfer: owner_before,
   owner_after, reason, scope, budget, return_condition, trace_id.

5. AgentLoop → OrchestratorLoop rename should occur AFTER SubagentRuntime
   exists, to prevent confusion between "agent" and "subagent."

See `docs/governance/orchestrator-loop-boundary.md` for the full doctrine.
