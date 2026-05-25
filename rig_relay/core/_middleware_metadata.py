"""Middleware and backend metadata mixin for AgentLoop.

Extracted from agent_loop.py. Provides middleware pipeline configuration
(multi-agent guardrails, auto-compact, price/turn limits), middleware
result handling (stop/inject/compact actions), and backend request
metadata assembly for LLM calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.config import ProviderConfig
from rig_relay.core.middleware import (
    CHAT_AGENT_EXIT,
    CHAT_AGENT_REMINDER,
    PLAN_AGENT_EXIT,
    AutoCompactMiddleware,
    ContextWarningMiddleware,
    ConversationContext,
    MiddlewareAction,
    MiddlewareResult,
    PriceLimitMiddleware,
    ReadOnlyAgentMiddleware,
    TurnLimitMiddleware,
    make_plan_agent_reminder,
)
from rig_relay.core.telemetry.build_metadata import build_request_metadata
from rig_relay.core.telemetry.types import TelemetryRequestMetadata
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    LLMMessage,
    Role,
)
from rig_relay.core.utils import VIBE_STOP_EVENT_TAG, get_user_agent

if TYPE_CHECKING:
    from rig_relay.core.telemetry.types import TelemetryCallType


class MiddlewareMetadataMixin:
    """Mixin providing middleware setup and backend metadata assembly."""

    def _setup_middleware(self) -> None:
        self.middleware_pipeline.clear()

        if self._max_turns is not None:
            self.middleware_pipeline.add(TurnLimitMiddleware(self._max_turns))

        if self._max_price is not None:
            self.middleware_pipeline.add(PriceLimitMiddleware(self._max_price))

        self.middleware_pipeline.add(AutoCompactMiddleware())
        if self.config.context_warnings:
            self.middleware_pipeline.add(ContextWarningMiddleware(0.5))

        self.middleware_pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: self.agent_profile,
                BuiltinAgentName.PLAN,
                lambda: make_plan_agent_reminder(
                    self._plan_session.plan_file_path_str,
                    has_ask_user_question="ask_user_question"
                    in self.tool_manager.available_tools,
                    has_exit_plan_mode="exit_plan_mode"
                    in self.tool_manager.available_tools,
                ),
                PLAN_AGENT_EXIT,
            )
        )
        self.middleware_pipeline.add(
            ReadOnlyAgentMiddleware(
                lambda: self.agent_profile,
                BuiltinAgentName.CHAT,
                CHAT_AGENT_REMINDER,
                CHAT_AGENT_EXIT,
            )
        )

    async def _handle_middleware_result(
        self, result: MiddlewareResult
    ) -> AsyncGenerator[BaseEvent]:
        match result.action:
            case MiddlewareAction.STOP:
                yield AssistantEvent(
                    content=f"<{VIBE_STOP_EVENT_TAG}>{result.reason}</{VIBE_STOP_EVENT_TAG}>",
                    stopped_by_middleware=True,
                )

            case MiddlewareAction.INJECT_MESSAGE:
                if result.message:
                    injected_message = LLMMessage(
                        role=Role.user, content=result.message, injected=True
                    )
                    self.messages.append(injected_message)

            case MiddlewareAction.COMPACT:
                old_tokens = result.metadata.get(
                    "old_tokens", self.stats.context_tokens
                )
                threshold = result.metadata.get(
                    "threshold", self.config.get_active_model().auto_compact_threshold
                )
                old_session_id = self.session_id
                old_parent_session_id = self.parent_session_id
                tool_call_id = str(uuid4())

                yield CompactStartEvent(
                    tool_call_id=tool_call_id,
                    current_context_tokens=old_tokens,
                    threshold=threshold,
                )

                compact_status: Literal["success", "failure", "cancelled"] = "success"
                new_tokens = self.stats.context_tokens
                try:
                    summary = await self.compact()
                except asyncio.CancelledError:
                    compact_status = "cancelled"
                    raise
                except Exception:
                    compact_status = "failure"
                    raise
                finally:
                    new_tokens = self.stats.context_tokens
                    self.telemetry_client.send_auto_compact_triggered(
                        nb_context_tokens_before=old_tokens,
                        nb_context_tokens_after=new_tokens,
                        auto_compact_threshold=threshold,
                        status=compact_status,
                        session_id=old_session_id,
                        parent_session_id=old_parent_session_id,
                    )

                yield CompactEndEvent(
                    tool_call_id=tool_call_id,
                    old_context_tokens=old_tokens,
                    new_context_tokens=new_tokens,
                    summary_length=len(summary),
                    old_session_id=old_session_id,
                    new_session_id=self.session_id,
                )

            case MiddlewareAction.CONTINUE:
                pass

    def _get_context(self) -> ConversationContext:
        return ConversationContext(
            messages=self.messages, stats=self.stats, config=self.config
        )

    def _build_backend_metadata(
        self, call_type: TelemetryCallType | None = None
    ) -> TelemetryRequestMetadata:
        return build_request_metadata(
            entrypoint_metadata=self.entrypoint_metadata,
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            call_type=(
                call_type
                if call_type is not None
                else ("main_call" if self._is_user_prompt_call else "secondary_call")
            ),
            message_id=self._current_user_message_id,
        )

    def _get_extra_headers(
        self, provider: ProviderConfig | None = None
    ) -> dict[str, str]:
        provider = self.config.get_active_provider() if provider is None else provider
        headers: dict[str, str] = {**provider.extra_headers}
        headers["user-agent"] = get_user_agent(provider.backend)
        headers["x-affinity"] = self.session_id
        return headers
