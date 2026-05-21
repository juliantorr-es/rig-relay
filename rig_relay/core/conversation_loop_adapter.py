from __future__ import annotations

from typing import Any

from rig_relay.core.hooks.models import HookType, HookUserMessage
from rig_relay.core.types import LLMMessage, Role


class _ConversationLoopAdapter:
    """Adapter implementing ConversationRuntimeCallbacks for AgentLoop."""

    __slots__ = ("_loop", "_user_msg")

    def __init__(self, loop: Any, user_msg: str) -> None:
        self._loop = loop
        self._user_msg = user_msg

    def get_turn(self) -> Any:
        return self._loop._current_turn

    def get_turn_id(self) -> str:
        return str(self._loop._current_turn.turn_id)

    def mark_turn_outcome(self, outcome: Any, reason: str) -> None:
        self._loop._current_turn.mark_outcome(outcome, reason)

    def persist_turn_state(self) -> None:
        pass

    async def middleware_before_turn(
        self, ctx: dict[str, str]
    ) -> tuple[Any, list[Any]]:
        """Run AgentLoop middleware pipeline and return (result, events)."""
        result = await self._loop.middleware_pipeline.run_before_turn(
            self._loop._get_context()
        )
        events: list[Any] = []
        async for event in self._loop._handle_middleware_result(result):
            events.append(event)
        return result, events

    def reset_hooks(self) -> None:
        if self._loop._hooks_manager:
            self._loop._hooks_manager.reset_retry_count()

    async def build_context_envelope(self, request: Any) -> Any:
        """Build context envelope asynchronously. No run_until_complete."""
        await self._loop._build_context_envelope(self._user_msg)
        return self._loop._current_context_envelope

    def set_context_envelope(self, receipt: Any) -> None:
        if receipt is not None:
            turn = self._loop._current_turn
            turn.context_envelope_id = receipt.envelope_id
            turn.context_section_count = receipt.section_count

    async def stream_llm_turn(self) -> Any:
        async for event in self._loop._perform_llm_turn():
            yield event

    def is_user_cancellation_event(self, event: Any) -> bool:
        from rig_relay.core._llm_call import is_user_cancellation_event

        return is_user_cancellation_event(event)

    async def stream_hooks_post_turn(self) -> Any:
        if not self._loop._hooks_manager:
            return
        async for hook_event in self._loop._hooks_manager.run(
            HookType.POST_AGENT_TURN,  # type: ignore[name-defined]
            self._loop.session_id,
            self._loop.session_logger,
        ):
            yield hook_event

    def is_hook_user_message(self, event: Any) -> bool:
        return isinstance(event, HookUserMessage)  # type: ignore[name-defined]

    def inject_hook_message(self, hook_message: Any) -> None:
        self._loop.messages.append(
            LLMMessage(  # type: ignore[name-defined]
                role=Role.user,  # type: ignore[name-defined]
                content=hook_message.content,
                injected=True,
            )
        )

    def last_message_has_no_tool_calls(self) -> bool:
        last = self._loop.messages[-1]
        return last.role != Role.tool  # type: ignore[name-defined]

    async def execute_tool_batch(self) -> Any:
        """Execute tool calls stored from stream_llm_turn().

        _perform_llm_turn() stores resolved tool calls in
        _pending_tool_resolved instead of executing them.
        This method executes those pending calls via _handle_tool_calls().
        """
        async for event in self._loop._execute_pending_tool_batch():
            yield event

    def check_max_turns(self) -> int | None:
        return self._loop._max_turns
