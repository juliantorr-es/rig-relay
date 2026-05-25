"""LLM call helpers mixin for AgentLoop.

Extracted from agent_loop.py to keep the main class manageable.
Provides _prepare_llm_call, _chat, _chat_streaming, _reraise_llm_error,
and _update_stats.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import time
from typing import TYPE_CHECKING

from rig_relay.core._agent_helpers import (
    _is_context_too_long_error,
    _is_non_retryable_error,
    _should_raise_rate_limit_error,
)
from rig_relay.core._errors import AgentLoopLLMResponseError
from rig_relay.core.types import (
    ContextTooLongError,
    LLMChunk,
    LLMUsage,
    RateLimitError,
    Role,
)

if TYPE_CHECKING:
    from rig_relay.core.config import ModelConfig, ProviderConfig
    from rig_relay.core.telemetry.types import TelemetryRequestMetadata


class LLMCallMixin:
    """Mixin providing LLM completion call orchestration."""

    async def _prepare_llm_call(
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
        active_model = model_override or self.config.get_active_model()
        provider = self.config.get_provider_for_model(active_model)
        backend_metadata = self._build_backend_metadata()

        available_tools = self.format_handler.get_available_tools(self.tool_manager)
        tool_choice = self.format_handler.get_tool_choice()

        last_user_message = next(
            (
                m
                for m in reversed(self.messages)
                if m.role == Role.user and not m.injected
            ),
            None,
        )
        self.telemetry_client.send_request_sent(
            model=active_model.alias,
            nb_context_chars=sum(len(m.content or "") for m in self.messages),
            nb_context_messages=len(self.messages),
            nb_prompt_chars=len(last_user_message.content or "")
            if last_user_message
            else 0,
            call_type=backend_metadata.call_type,
            message_id=backend_metadata.message_id,
            messages=self.messages,
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

    async def _chat(
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
        ) = await self._prepare_llm_call(max_tokens, model_override)

        try:
            start_time = time.perf_counter()
            result = await self.backend.complete(
                model=active_model,
                messages=self.messages,
                temperature=active_model.temperature,
                tools=available_tools,
                tool_choice=tool_choice,
                extra_headers=self._get_extra_headers(provider),
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
                self.telemetry_client.last_correlation_id = result.correlation_id

            processed_message = self.format_handler.process_api_response_message(
                result.message
            )
            self.messages.append(processed_message)
            return LLMChunk(message=processed_message, usage=result.usage)

        except Exception as e:
            self._reraise_llm_error(e, provider, active_model)
            raise

    async def _chat_streaming(
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
        ) = await self._prepare_llm_call(max_tokens)

        try:
            start_time = time.perf_counter()
            usage = LLMUsage()
            chunk_agg: LLMChunk | None = None
            async for chunk in self.backend.complete_streaming(
                model=active_model,
                messages=self.messages,
                temperature=active_model.temperature,
                tools=available_tools,
                tool_choice=tool_choice,
                extra_headers=self._get_extra_headers(),
                max_tokens=max_tokens,
                metadata=metadata,
            ):
                if chunk.correlation_id:
                    self.telemetry_client.last_correlation_id = chunk.correlation_id
                processed_message = self.format_handler.process_api_response_message(
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

            self.messages.append(chunk_agg.message)

        except Exception as e:
            self._reraise_llm_error(e, provider, active_model)
            raise

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

    def _update_stats(self, usage: LLMUsage, time_seconds: float) -> None:
        self.stats.last_turn_duration = time_seconds
        self.stats.last_turn_prompt_tokens = usage.prompt_tokens
        self.stats.last_turn_completion_tokens = usage.completion_tokens
        self.stats.session_prompt_tokens += usage.prompt_tokens
        self.stats.session_completion_tokens += usage.completion_tokens
        self.stats.context_tokens = usage.prompt_tokens + usage.completion_tokens
        if time_seconds > 0 and usage.completion_tokens > 0:
            self.stats.tokens_per_second = usage.completion_tokens / time_seconds
