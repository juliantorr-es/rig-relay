"""ACP mixin — usage."""

from __future__ import annotations

from acp.schema import Cost, Usage, UsageUpdate

from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.utils import (
    create_assistant_message_replay,
    create_reasoning_replay,
    create_tool_call_replay,
    create_tool_result_replay,
    create_user_message_replay,
)
from rig_relay.core.types import LLMMessage, Role


class UsageMixin:
    """Mixin for VibeAcpAgentLoop."""

    def _build_usage(self, session: AcpSessionLoop) -> Usage:
        stats = session.agent_loop.stats
        return Usage(
            input_tokens=stats.session_prompt_tokens,
            output_tokens=stats.session_completion_tokens,
            total_tokens=stats.session_total_llm_tokens,
        )

    def _build_usage_update(self, session: AcpSessionLoop) -> UsageUpdate:
        stats = session.agent_loop.stats
        active_model = session.agent_loop.config.get_active_model()
        cost = (
            Cost(amount=stats.session_cost, currency="USD")
            if stats.input_price_per_million > 0 or stats.output_price_per_million > 0
            else None
        )
        return UsageUpdate(
            session_update="usage_update",
            used=stats.context_tokens,
            size=active_model.auto_compact_threshold,
            cost=cost,
        )

    def _send_usage_update(self, session: AcpSessionLoop) -> None:
        async def _send() -> None:
            try:
                update = self._build_usage_update(session)
                await self.client.session_update(session_id=session.id, update=update)
            except Exception:
                pass

        session.spawn(_send())

    async def _replay_tool_calls(self, session_id: str, msg: LLMMessage) -> None:
        if not msg.tool_calls:
            return
        for tool_call in msg.tool_calls:
            if tool_call.id and tool_call.function.name:
                update = create_tool_call_replay(
                    tool_call.id, tool_call.function.name, tool_call.function.arguments
                )
                await self.client.session_update(session_id=session_id, update=update)

    async def _replay_conversation_history(
        self, session_id: str, messages: list[LLMMessage]
    ) -> None:
        for msg in messages:
            if msg.role == Role.user:
                update = create_user_message_replay(msg)
                await self.client.session_update(session_id=session_id, update=update)

            elif msg.role == Role.assistant:
                if reasoning_update := create_reasoning_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=reasoning_update
                    )
                if text_update := create_assistant_message_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=text_update
                    )
                await self._replay_tool_calls(session_id, msg)

            elif msg.role == Role.tool:
                if result_update := create_tool_result_replay(msg):
                    await self.client.session_update(
                        session_id=session_id, update=result_update
                    )
