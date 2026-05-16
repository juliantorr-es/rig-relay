# ConversationRuntime Phase 2A — Decision Policy Inventory

**AgentLoop**: `rig_relay/core/agent_loop.py` (1563 lines)
**Method**: `_conversation_loop` (lines 745–865)

## Current Decision Points in `_conversation_loop`

### 1. Middleware STOP (line 789)
```python
if result.action == MiddlewareAction.STOP:
    cr._finish(TurnOutcome.MIDDLEWARE_STOP)
    return
```
Decision: Stop loop immediately. Outcome: MIDDLEWARE_STOP.

### 2. User cancellation detection (lines 814–817 + 825–830)
```python
if is_user_cancellation_event(event):
    user_cancelled = True

if user_cancelled:
    cr._finish(TurnOutcome.USER_CANCELLED, "user cancelled")
    turn.mark_outcome(TurnOutcome.USER_CANCELLED, "user cancelled")
    return
```
Decision: Stop loop, outcome USER_CANCELLED.

### 3. Break condition: no tool calls / assistant final (line 823)
```python
should_break_loop = last_message.role != Role.tool
```
Decision: Assistant sent a final reply (not a tool call). Loop should break.

### 4. Hook retry (lines 831–848)
```python
if should_break_loop and self._hooks_manager:
    hook_retry = ...
    if hook_retry is not None:
        should_break_loop = False
```
Decision: An injected hook message keeps the loop running.

### 5. Tool call batch (lines 876+)
```python
if not resolved.tool_calls and not resolved.failed_calls:
    # no tool calls to run
```
Decision: Tool calls present → run tools. No tool calls → continue to next model turn.

### 6. Exception/failure (lines 870–874, try/finally)
```python
try:
    ...
finally:
    await self._save_messages()
```
Decision: Exception propagates up to caller. No dedicated failure outcome classification here.

### 7. Max turns budget (line 329)
```python
max_turns=self._max_turns,
```
Decision: Enforced elsewhere in `act()` method. Not yet in `_conversation_loop`.

### 8. Loop termination: SUCCESS (lines 862–863)
```python
cr._finish(TurnOutcome.SUCCESS)
turn.advance(TurnPhase.FINALIZING)
turn.mark_outcome(TurnOutcome.SUCCESS)
```
Decision: Final outcome after loop ends normally.

## Summary

| # | Decision Kind | Location | Currently In |
|---|---|---|---|
| 1 | MIDDLEWARE_STOP | Line 789 | AgentLoop |
| 2 | USER_CANCELLED | Lines 814–830 | AgentLoop |
| 3 | Assistant final (break) | Line 823 | AgentLoop |
| 4 | Hook retry (continue) | Lines 831–848 | AgentLoop |
| 5 | Tool calls present | Line 876 | AgentLoop |
| 6 | Exception/failure | try/finally | AgentLoop |
| 7 | Max turns budget | Line 329 | AgentLoop |
| 8 | SUCCESS outcome | Lines 862–863 | AgentLoop |

## Phase 2A Target

Move decisions 1, 2, 3, 6, 8 (the terminal and loop-control decisions) into `ConversationRuntime.decide_*()` methods. Keep execution mechanics (model call, tool batch, hook run) in AgentLoop but have the decision returned by ConversationRuntime.

Decisions 4 (hook retry) and 5 (tool batch) stay in AgentLoop for now — they involve execution state too deeply coupled to the loop.
