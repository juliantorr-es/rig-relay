"""ModelRuntime — LLM call execution and middleware metadata assembly.

Owns the model-request boundary: preparation, streaming/non-streaming
completion, provider error translation, stats accounting, backend
request metadata, and canonical middleware pipeline configuration.
Depends on explicit configuration, not hidden agent state.

Phase 1 extraction — absorbed from former LLMCallMixin and
MiddlewareMetadataMixin; those mixin modules are now deleted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
import time
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4 as _uuid4

from rig_relay.core._agent_helpers import (
    _is_context_too_long_error,
    _is_non_retryable_error,
    _should_raise_rate_limit_error,
)
from rig_relay.core._errors import AgentLoopLLMResponseError
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
    MiddlewarePipeline,
    MiddlewareResult,
    PriceLimitMiddleware,
    ReadOnlyAgentMiddleware,
    TurnLimitMiddleware,
    make_plan_agent_reminder,
)
from rig_relay.core.telemetry.build_metadata import build_request_metadata
from rig_relay.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    ContextTooLongError,
    LLMChunk,
    LLMMessage,
    LLMUsage,
    RateLimitError,
    Role,
)
from rig_relay.core.utils import VIBE_STOP_EVENT_TAG, get_user_agent

if TYPE_CHECKING:
    from rig_relay.core.config import ModelConfig, VibeConfig
    from rig_relay.core.llm.format import APIToolFormatHandler
    from rig_relay.core.telemetry.send import TelemetryClient
    from rig_relay.core.telemetry.types import (
        EntrypointMetadata,
        TelemetryCallType,
        TelemetryRequestMetadata,
    )
    from rig_relay.core.tools.manager import ToolManager
    from rig_relay.core.types import MessageList


class ModelRuntime:
    """LLM call and middleware metadata runtime.

    Owns:
      - LLM call preparation (context assembly, telemetry, metadata)
      - Backend invocation (streaming, non-streaming)
      - Provider error translation
      - Stats accounting
      - Middleware pipeline setup and result handling
      - Backend request metadata assembly
    """

    __slots__ = (
        "_config",
        "_backend",
        "_tool_manager",
        "_format_handler",
        "_messages",
        "_stats",
        "_telemetry_client",
        "_entrypoint_metadata",
        "_session_id_getter",
        "_parent_session_id_getter",
        "_is_user_prompt_call_getter",
        "_current_user_message_id_getter",
        "_middleware_pipeline",
        "_plan_session",
        "_agent_profile_getter",
        "_workspace_root",
        "_headless",
        "_report_context_assembly",
        "_compact_fn",
    )

    def __init__(
        self,
        *,
        config: VibeConfig,
        backend: Any,
        tool_manager: ToolManager,
        format_handler: APIToolFormatHandler,
        messages: MessageList,
        stats: Any,
        telemetry_client: TelemetryClient,
        entrypoint_metadata: EntrypointMetadata | None,
        session_id_getter: Callable[[], str],
        parent_session_id_getter: Callable[[], str | None],
        is_user_prompt_call_getter: Callable[[], bool],
        current_user_message_id_getter: Callable[[], str | None],
        middleware_pipeline: MiddlewarePipeline,
        agent_profile_getter: Any,
        plan_session: Any,
        workspace_root: Any,
        headless: bool,
        report_context_assembly: Any,
        compact_fn: Any,
    ) -> None:
        self._config = config
        self._backend = backend
        self._tool_manager = tool_manager
        self._format_handler = format_handler
        self._messages = messages
        self._stats = stats
        self._telemetry_client = telemetry_client
        self._entrypoint_metadata = entrypoint_metadata
        self._session_id_getter = session_id_getter
        self._parent_session_id_getter = parent_session_id_getter
        self._is_user_prompt_call_getter = is_user_prompt_call_getter
        self._current_user_message_id_getter = current_user_message_id_getter
        self._middleware_pipeline = middleware_pipeline
        self._agent_profile_getter = agent_profile_getter
        self._plan_session = plan_session
        self._workspace_root = workspace_root
        self._headless = headless
        self._report_context_assembly = report_context_assembly
        self._compact_fn = compact_fn

    # ── Middleware setup ─────────────────────────────────────────

    def setup_middleware(self, max_turns: int | None, max_price: float | None) -> None:
        self._middleware_pipeline.clear()

        if max_turns is not None:
            self._middleware_pipeline.add(TurnLimitMiddleware(max_turns))

        if max_price is not None:
            self._middleware_pipeline.add(PriceLimitMiddleware(max_price))

        self._middleware_pipeline.add(AutoCompactMiddleware())
        if self._config.context_warnings:
            self._middleware_pipeline.add(ContextWarningMiddleware(0.5))

        self._middleware_pipeline.add(
            ReadOnlyAgentMiddleware(
                self._agent_profile_getter,
                BuiltinAgentName.PLAN,
                lambda: make_plan_agent_reminder(
                    self._plan_session.plan_file_path_str,
                    has_ask_user_question="ask_user_question"
                    in self._tool_manager.available_tools,
                    has_exit_plan_mode="exit_plan_mode"
                    in self._tool_manager.available_tools,
                ),
                PLAN_AGENT_EXIT,
            )
        )
        self._middleware_pipeline.add(
            ReadOnlyAgentMiddleware(
                self._agent_profile_getter,
                BuiltinAgentName.CHAT,
                CHAT_AGENT_REMINDER,
                CHAT_AGENT_EXIT,
            )
        )

    async def handle_middleware_result(
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
                    self._messages.append(injected_message)

            case MiddlewareAction.COMPACT:
                old_tokens = result.metadata.get(
                    "old_tokens", self._stats.context_tokens
                )
                threshold = result.metadata.get(
                    "threshold", self._config.get_active_model().auto_compact_threshold
                )
                old_session_id = self._session_id_getter()
                tool_call_id = str(_uuid4())

                yield CompactStartEvent(
                    tool_call_id=tool_call_id,
                    current_context_tokens=old_tokens,
                    threshold=threshold,
                )

                compact_status: Literal["success", "failure", "cancelled"] = "success"
                new_tokens = self._stats.context_tokens
                summary_str = ""
                try:
                    summary_str = await self._compact_fn() or ""
                except asyncio.CancelledError:
                    compact_status = "cancelled"
                    raise
                except Exception:
                    compact_status = "failure"
                    raise
                finally:
                    new_tokens = self._stats.context_tokens
                    self._telemetry_client.send_auto_compact_triggered(
                        nb_context_tokens_before=old_tokens,
                        nb_context_tokens_after=new_tokens,
                        auto_compact_threshold=threshold,
                        status=compact_status,
                        session_id=old_session_id,
                        parent_session_id=self._parent_session_id_getter(),
                    )

                yield CompactEndEvent(
                    tool_call_id=tool_call_id,
                    old_context_tokens=old_tokens,
                    new_context_tokens=new_tokens,
                    summary_length=len(summary_str),
                    old_session_id=old_session_id,
                    new_session_id=self._session_id_getter(),
                )

            case MiddlewareAction.CONTINUE:
                pass

    def get_middleware_context(self) -> ConversationContext:
        return ConversationContext(
            messages=self._messages, stats=self._stats, config=self._config
        )

    def build_backend_metadata(
        self, call_type: TelemetryCallType | None = None
    ) -> TelemetryRequestMetadata:
        return build_request_metadata(
            entrypoint_metadata=self._entrypoint_metadata,
            session_id=self._session_id_getter(),
            parent_session_id=self._parent_session_id_getter(),
            call_type=(
                call_type
                if call_type is not None
                else (
                    "main_call"
                    if self._is_user_prompt_call_getter()
                    else "secondary_call"
                )
            ),
            message_id=self._current_user_message_id_getter(),
        )

    def get_extra_headers(
        self, provider: ProviderConfig | None = None
    ) -> dict[str, str]:
        provider_obj = (
            self._config.get_active_provider() if provider is None else provider
        )
        headers: dict[str, str] = {**provider_obj.extra_headers}
        headers["user-agent"] = get_user_agent(provider_obj.backend)
        headers["x-affinity"] = self._session_id_getter()
        return headers

    # ── LLM call execution ──────────────────────────────────────

    async def prepare_llm_call(
        self, max_tokens: int | None = None, model_override: ModelConfig | None = None
    ) -> tuple[
        ModelConfig,
        ProviderConfig,
        dict[str, object],
        object,
        object,
        object | None,
        TelemetryRequestMetadata,
    ]:
        active_model = model_override or self._config.get_active_model()
        provider = self._config.get_provider_for_model(active_model)
        backend_metadata = self.build_backend_metadata()

        available_tools = self._format_handler.get_available_tools(self._tool_manager)
        tool_choice = self._format_handler.get_tool_choice()

        last_user_message = next(
            (
                m
                for m in reversed(self._messages)
                if m.role == Role.user and not m.injected
            ),
            None,
        )
        self._telemetry_client.send_request_sent(
            model=active_model.alias,
            nb_context_chars=sum(len(m.content or "") for m in self._messages),
            nb_context_messages=len(self._messages),
            nb_prompt_chars=len(last_user_message.content or "")
            if last_user_message
            else 0,
            call_type=backend_metadata.call_type,
            message_id=backend_metadata.message_id,
            messages=self._messages,
        )

        await self._report_context_assembly(active_model)

        return (
            active_model,
            provider,
            backend_metadata.model_dump(exclude_none=True),
            available_tools,
            tool_choice,
            last_user_message,
            backend_metadata,
        )

    async def chat(
        self, max_tokens: int | None = None, model_override: ModelConfig | None = None
    ) -> LLMChunk:
        (
            active_model,
            provider,
            metadata,
            available_tools,
            tool_choice,
            _,
            _,
        ) = await self.prepare_llm_call(max_tokens, model_override)

        try:
            start_time = time.perf_counter()
            result = await self._backend.complete(
                model=active_model,
                messages=self._messages,
                temperature=active_model.temperature,
                tools=available_tools,
                tool_choice=tool_choice,
                extra_headers=self.get_extra_headers(provider),
                max_tokens=max_tokens,
                metadata=metadata,
            )
            end_time = time.perf_counter()

            if result.usage is None:
                raise AgentLoopLLMResponseError(
                    "Usage data missing in non-streaming completion response"
                )
            self._update_stats(usage=result.usage, time_seconds=end_time - start_time)

            if result.correlation_id:
                self._telemetry_client.last_correlation_id = result.correlation_id

            processed_message = self._format_handler.process_api_response_message(
                result.message
            )
            self._messages.append(processed_message)
            return LLMChunk(message=processed_message, usage=result.usage)

        except Exception as e:
            self._reraise_llm_error(e, provider, active_model)
            raise

    async def chat_streaming(
        self, max_tokens: int | None = None
    ) -> AsyncGenerator[LLMChunk]:
        (
            active_model,
            provider,
            metadata,
            available_tools,
            tool_choice,
            _,
            _,
        ) = await self.prepare_llm_call(max_tokens)

        try:
            start_time = time.perf_counter()
            usage = LLMUsage()
            chunk_agg: LLMChunk | None = None
            async for chunk in self._backend.complete_streaming(
                model=active_model,
                messages=self._messages,
                temperature=active_model.temperature,
                tools=available_tools,
                tool_choice=tool_choice,
                extra_headers=self.get_extra_headers(),
                max_tokens=max_tokens,
                metadata=metadata,
            ):
                if chunk.correlation_id:
                    self._telemetry_client.last_correlation_id = chunk.correlation_id
                processed_message = self._format_handler.process_api_response_message(
                    chunk.message
                )
                processed_chunk = LLMChunk(message=processed_message, usage=chunk.usage)
                chunk_agg = (
                    processed_chunk
                    if chunk_agg is None
                    else chunk_agg + processed_chunk
                )
                usage += chunk.usage or LLMUsage()
                yield processed_chunk
            end_time = time.perf_counter()

            if chunk_agg is None or chunk_agg.usage is None:
                raise AgentLoopLLMResponseError(
                    "Usage data missing in final chunk of streamed completion"
                )
            self._update_stats(usage=usage, time_seconds=end_time - start_time)

            self._messages.append(chunk_agg.message)

        except Exception as e:
            self._reraise_llm_error(e, provider, active_model)
            raise

    # ── Internal helpers ─────────────────────────────────────────

    def _update_stats(self, usage: LLMUsage, time_seconds: float) -> None:
        self._stats.last_turn_duration = time_seconds
        self._stats.last_turn_prompt_tokens = usage.prompt_tokens
        self._stats.last_turn_completion_tokens = usage.completion_tokens
        self._stats.session_prompt_tokens += usage.prompt_tokens
        self._stats.session_completion_tokens += usage.completion_tokens
        self._stats.context_tokens = usage.prompt_tokens + usage.completion_tokens
        if time_seconds > 0 and usage.completion_tokens > 0:
            self._stats.tokens_per_second = usage.completion_tokens / time_seconds

    def _reraise_llm_error(
        self, error: Exception, provider: ProviderConfig, active_model: ModelConfig
    ) -> None:
        if _should_raise_rate_limit_error(error):
            raise RateLimitError(provider.name, active_model.name) from error
        if _is_context_too_long_error(error):
            raise ContextTooLongError(provider.name, active_model.name) from error
        if _is_non_retryable_error(error):
            raise
        raise RuntimeError(
            f"API error from {provider.name} (model: {active_model.name}): {error}"
        ) from error
