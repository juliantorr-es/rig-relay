from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from rig_relay.core.conversation_runtime.models import (
    ConversationRuntimeCallbacks,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeRequest,
    TurnBatchResult,
)
from rig_relay.core.hooks.models import HookType, HookUserMessage
from rig_relay.core.types import BaseEvent, LLMMessage, Role

if TYPE_CHECKING:
    pass


class _ConversationLoopAdapter(ConversationRuntimeCallbacks):
    """Adapter implementing ConversationRuntimeCallbacks for AgentLoop.

    All methods required by the Protocol are present — no cast() needed.
    setup_turn, emit_phase_event, and yield_user_message_event are
    reserved for future migration of turn-setup into the adapter.
    """

    __slots__ = ("_loop", "_user_msg")

    def __init__(self, loop: Any, user_msg: str) -> None:
        self._loop = loop
        self._user_msg = user_msg

    # ── Turn lifecycle ──────────────────────────────────────────

    def setup_turn(self, request: ConversationRuntimeRequest) -> None:
        """Reserved for future migration. Currently handled in AgentLoop._conversation_loop."""
        raise NotImplementedError(
            "setup_turn not yet implemented; handled inline in AgentLoop._conversation_loop"
        )

    def get_turn(self) -> Any:
        return self._loop._current_turn

    def get_turn_id(self) -> str:
        return str(self._loop._current_turn.turn_id)

    def mark_turn_outcome(self, outcome: Any, reason: str) -> None:
        self._loop._current_turn.mark_outcome(outcome, reason)

    def persist_turn_state(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._loop._save_messages())

    def emit_phase_event(self, event: ConversationRuntimePhaseEvent) -> None:
        """Reserved for future migration. Phase events managed by ConversationRuntime."""
        raise NotImplementedError(
            "emit_phase_event not yet implemented; handled inline in ConversationRuntime"
        )

    # ── Middleware ───────────────────────────────────────────────

    async def middleware_before_turn(
        self, ctx: dict[str, str]
    ) -> tuple[Any, list[BaseEvent]]:
        """Run AgentLoop middleware pipeline and return (result, events)."""
        result = await self._loop.middleware_pipeline.run_before_turn(
            self._loop._get_context()
        )
        events: list[BaseEvent] = []
        async for event in self._loop._handle_middleware_result(result):
            events.append(event)
        return result, events

    def reset_hooks(self) -> None:
        if self._loop._hooks_manager:
            self._loop._hooks_manager.reset_retry_count()

    # ── Context ──────────────────────────────────────────────────

    async def build_context_envelope(
        self, request: ConversationRuntimeRequest
    ) -> Any | None:
        """Build context envelope asynchronously. No run_until_complete."""
        await self._loop._build_context_envelope(self._user_msg)
        return self._loop._current_context_envelope

    def set_context_envelope(self, receipt: Any) -> None:
        if receipt is not None:
            turn = self._loop._current_turn
            turn.context_envelope_id = receipt.envelope_id
            turn.context_section_count = receipt.section_count

    # ── LLM ──────────────────────────────────────────────────────

    async def stream_llm_turn(self) -> AsyncGenerator[BaseEvent, None]:
        async for event in self._loop._perform_llm_turn():
            yield event

    def is_user_cancellation_event(self, event: BaseEvent) -> bool:
        from rig_relay.core.utils.tags import is_user_cancellation_event

        return is_user_cancellation_event(event)

    # ── Hooks ────────────────────────────────────────────────────

    async def stream_hooks_post_turn(self) -> AsyncGenerator[BaseEvent, None]:
        if not self._loop._hooks_manager:
            return
        async for hook_event in self._loop._hooks_manager.run(
            HookType.POST_AGENT_TURN,  # type: ignore[name-defined]
            self._loop.session_id,
            self._loop.session_logger,
        ):
            yield hook_event

    def is_hook_user_message(self, event: BaseEvent) -> bool:
        return isinstance(event, HookUserMessage)  # type: ignore[name-defined]

    def inject_hook_message(self, hook_message: Any) -> None:
        self._loop.messages.append(
            LLMMessage(  # type: ignore[name-defined]
                role=Role.user,  # type: ignore[name-defined]
                content=hook_message.content,
                injected=True,
            )
        )

    # ── Loop control ─────────────────────────────────────────────

    def last_message_has_no_tool_calls(self) -> bool:
        """Check whether the model turn produced pending tool calls to execute.

        Replaced per-role inference with direct pending-state check because
        assistant messages with tool calls have Role.assistant, not Role.tool.
        """
        resolved = self._loop._pending_tool_resolved
        if resolved is None:
            return True
        return not resolved.tool_calls and not resolved.failed_calls

    def get_turn_batch_result(self) -> TurnBatchResult:
        resolved = self._loop._pending_tool_resolved
        if resolved is None:
            return TurnBatchResult(pending_batch=None, assistant_is_final=True)
        has_tool_calls = bool(resolved.tool_calls)
        has_failed = bool(resolved.failed_calls)
        return TurnBatchResult(
            pending_batch=list(resolved.tool_calls) if has_tool_calls else None,
            failed_calls=list(resolved.failed_calls) if has_failed else [],
            assistant_is_final=not has_tool_calls and not has_failed,
        )

    # ── Tool execution ─────────────────────────────────────────

    async def execute_tool_batch(self) -> AsyncGenerator[BaseEvent, None]:
        """Execute tool calls stored from stream_llm_turn().

        _perform_llm_turn() stores resolved tool calls in
        _pending_tool_resolved instead of executing them.
        This method executes those pending calls via _execute_pending_tool_batch().
        """
        async for event in self._loop._execute_pending_tool_batch():
            yield event

    # ── Budget ──────────────────────────────────────────────────

    def check_max_turns(self) -> int | None:
        return self._loop._max_turns

    # ── Event emission ─────────────────────────────────────────

    def yield_user_message_event(self) -> AsyncGenerator[BaseEvent, None]:
        """Reserved for future migration. Currently handled inline in AgentLoop._conversation_loop."""

        async def _stub() -> AsyncGenerator[BaseEvent, None]:
            if False:
                yield

        return _stub()
