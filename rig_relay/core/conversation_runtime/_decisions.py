"""Pure decision logic extracted from ConversationRuntime.

These functions are stateless — they receive inputs and return a
ConversationLoopDecision. Side effects (e.g. _finish_decision) are
applied by the wrapper methods in runtime.py.
"""

from __future__ import annotations

from rig_relay.core.conversation_runtime.models import ConversationLoopDecision


def decide_after_middleware(action: str) -> ConversationLoopDecision:
    """Middleware STOP → stop_middleware. Otherwise continue."""
    if action == "STOP":
        return ConversationLoopDecision.stop_middleware("middleware action STOP")
    return ConversationLoopDecision.continue_turn("middleware action CONTINUE")


def decide_after_model_turn(
    user_cancelled: bool = False, assistant_final: bool = True, error: str | None = None
) -> ConversationLoopDecision:
    """After LLM turn: decide to stop, continue, or fail."""
    if error:
        return ConversationLoopDecision.fail_error(error)
    if user_cancelled:
        return ConversationLoopDecision.stop_cancelled("user cancelled")
    if assistant_final:
        return ConversationLoopDecision.stop_completed("assistant final reply")
    return ConversationLoopDecision.run_tools("tool calls present")


def decide_on_exception(exc: Exception) -> ConversationLoopDecision:
    """Exception → fail_error."""
    return ConversationLoopDecision.fail_error(
        str(exc)[:500], attributes={"error_type": type(exc).__name__}
    )


def decide_after_hook_processing(
    hook_returned_user_message: bool = False,
) -> ConversationLoopDecision:
    """After processing hooks: retry or accept completion."""
    if hook_returned_user_message:
        return ConversationLoopDecision.retry_hooks(
            "hook returned user message → retry turn"
        )
    return ConversationLoopDecision.stop_completed("hooks processed, no retry message")


def decide_after_tool_batch() -> ConversationLoopDecision:
    """After tool execution batch: continue the turn loop."""
    return ConversationLoopDecision.continue_turn("tool batch completed")


def decide_after_budget_check(
    current_turn: int, max_turns: int | None
) -> ConversationLoopDecision:
    """Check max-turn budget. Fail if exceeded."""
    if max_turns is not None and current_turn >= max_turns:
        return ConversationLoopDecision.fail_budget_exceeded(
            f"max turns {max_turns} reached at turn {current_turn}"
        )
    return ConversationLoopDecision.continue_turn("budget ok")
