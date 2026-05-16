# ConversationRuntime Phase 2B — Hook/Tool/Budget Decision Policy

Audit date: 2026-05-15

## Context

Phase 2A moved terminal/near-terminal decisions:
- `decide_after_middleware()` — STOP vs continue
- `decide_after_model_turn()` — stop_cancelled, stop_completed, run_tools, fail_error
- `decide_on_exception()` — fail_error

Phase 2B moves hook retry, tool batch, and budget decisions out of AgentLoop.

## Decisions moved

| Decision method | Owns | Previous owner |
|---|---|---|
| `decide_after_hook_processing(hook_returned_user_message)` | Whether hook retry is required or completion should proceed | AgentLoop inline `hook_retry` check |
| `decide_after_tool_batch()` | Tool batch completed → continue_turn | (new — previously implicit) |
| `decide_after_budget_check(current_turn, max_turns)` | Max-turn budget exceeded → fail_budget_exceeded | (new — previously unenforced) |

## What stays in AgentLoop

- Hook execution loop (`async for hook_event in self._hooks_manager.run(...)`)
- Hook message injection (`self.messages.append(LLMMessage(...))`)
- Tool execution (delegates to ToolRuntime)
- Event yielding
- Middleware execution

## Decision kind map

| Decision | Kind | should_break | should_retry_hooks |
|---|---|---|---|
| Hook returns user message | `retry_hooks` | False | True |
| Hook passes through | `stop_completed` | True | False |
| Tool batch completed | `continue_turn` | False | False |
| Budget exceeded | `fail_budget_exceeded` | True | False |
| Budget ok | `continue_turn` | False | False |

## Trace

Decision methods emit `PhaseTraceHook` attributes if a hook is registered.
No raw message content, tool outputs, or prompts appear in decision attributes.

## Future (Phase 3)

Phase 3 will move the while-loop itself into ConversationRuntime, making
AgentLoop a pure callback adapter.
