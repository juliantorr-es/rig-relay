from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
import json
import os
import types
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple

import httpx

from rig_relay.core.llm.backend.anthropic import AnthropicAdapter
from rig_relay.core.llm.backend.base import APIAdapter, PreparedRequest
from rig_relay.core.llm.backend.gemini import GeminiAdapter
from rig_relay.core.llm.backend.openai_responses import OpenAIResponsesAdapter
from rig_relay.core.llm.backend.reasoning_adapter import ReasoningAdapter
from rig_relay.core.llm.exceptions import BackendErrorBuilder
from rig_relay.core.llm.message_utils import merge_consecutive_user_messages
from rig_relay.core.types import (
    AvailableTool,
    LLMChunk,
    LLMMessage,
    LLMUsage,
    Role,
    StrToolChoice,
)
from rig_relay.core.utils import async_generator_retry, async_retry
from rig_relay.core.utils.http import build_ssl_context
from rig_relay.providers.invocation import (
    GatewayProvenance,
    GatewayProvenanceSource,
    InvocationOutcomeClass,
    UsageEvidenceSource,
    build_invocation_outcome,
)
from rig_relay.providers.models import ProviderClass

if TYPE_CHECKING:
    from rig_relay.core.config import ModelConfig, ProviderConfig


class OpenAIAdapter(APIAdapter):
    endpoint: ClassVar[str] = "/chat/completions"

    def __init__(self) -> None:
        self._last_model_name: str = ""
        self._last_streaming: bool = False
        self._last_provider_name: str = ""
        self._last_response_headers: dict[str, str] = {}

    def build_payload(
        self,
        model_name: str,
        converted_messages: list[dict[str, Any]],
        temperature: float,
        tools: list[AvailableTool] | None,
        max_tokens: int | None,
        tool_choice: StrToolChoice | AvailableTool | None,
    ) -> dict[str, Any]:
        payload = {
            "model": model_name,
            "messages": converted_messages,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = [tool.model_dump(exclude_none=True) for tool in tools]
        if tool_choice:
            payload["tool_choice"] = (
                tool_choice
                if isinstance(tool_choice, str)
                else tool_choice.model_dump()
            )
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        return payload

    def build_headers(self, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _reasoning_to_api(
        self, msg_dict: dict[str, Any], field_name: str
    ) -> dict[str, Any]:
        if field_name != "reasoning_content" and "reasoning_content" in msg_dict:
            msg_dict[field_name] = msg_dict.pop("reasoning_content")
        return msg_dict

    def _reasoning_from_api(
        self, msg_dict: dict[str, Any], field_name: str
    ) -> dict[str, Any]:
        if field_name != "reasoning_content" and field_name in msg_dict:
            msg_dict["reasoning_content"] = msg_dict.pop(field_name)
        return msg_dict

    def prepare_request(
        self,
        *,
        model_name: str,
        messages: Sequence[LLMMessage],
        temperature: float,
        tools: list[AvailableTool] | None,
        max_tokens: int | None,
        tool_choice: StrToolChoice | AvailableTool | None,
        enable_streaming: bool,
        provider: ProviderConfig,
        api_key: str | None = None,
        thinking: str = "off",
    ) -> PreparedRequest:
        self._last_model_name = model_name
        self._last_streaming = enable_streaming
        self._last_provider_name = provider.name
        merged_messages = merge_consecutive_user_messages(messages)
        field_name = provider.reasoning_field_name
        converted_messages = [
            self._reasoning_to_api(
                msg.model_dump(
                    exclude_none=True,
                    exclude={
                        "message_id",
                        "reasoning_message_id",
                        "reasoning_state",
                        "injected",
                    },
                ),
                field_name,
            )
            for msg in merged_messages
        ]

        payload = self.build_payload(
            model_name, converted_messages, temperature, tools, max_tokens, tool_choice
        )

        if enable_streaming:
            payload["stream"] = True
            stream_options = {"include_usage": True}
            if provider.name == "mistral":
                stream_options["stream_tool_calls"] = True
            payload["stream_options"] = stream_options

        headers = self.build_headers(api_key)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        return PreparedRequest(self.endpoint, headers, body)

    def _parse_message(
        self, data: dict[str, Any], field_name: str
    ) -> LLMMessage | None:
        if data.get("choices"):
            choice = data["choices"][0]
            if "message" in choice:
                msg_dict = self._reasoning_from_api(choice["message"], field_name)
                return LLMMessage.model_validate(msg_dict)
            if "delta" in choice:
                msg_dict = self._reasoning_from_api(choice["delta"], field_name)
                return LLMMessage.model_validate(msg_dict)
            raise ValueError("Invalid response data: missing message or delta")

        if "message" in data:
            msg_dict = self._reasoning_from_api(data["message"], field_name)
            return LLMMessage.model_validate(msg_dict)
        if "delta" in data:
            msg_dict = self._reasoning_from_api(data["delta"], field_name)
            return LLMMessage.model_validate(msg_dict)

        return None

    def parse_response(
        self, data: dict[str, Any], provider: ProviderConfig
    ) -> LLMChunk:
        message = self._parse_message(data, provider.reasoning_field_name)
        if message is None:
            message = LLMMessage(role=Role.assistant, content="")

        usage_data = data.get("usage") or {}
        has_usage = "prompt_tokens" in usage_data or "completion_tokens" in usage_data
        usage = LLMUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
        )

        outcome = None
        if has_usage:
            provider_name = self._last_provider_name or provider.name
            provider_class = _provider_class_for_name(provider_name)
            api_style = getattr(provider, "api_style", "openai")
            response_id: str | None = data.get("id")
            model_id: str | None = data.get("model")
            is_routed = provider_class == ProviderClass.ROUTED_GATEWAY

            evidence = (
                _extract_openrouter_evidence(usage_data, self._last_response_headers)
                if is_routed
                else {}
            )

            outcome = build_invocation_outcome(
                requested_provider_id=provider_name,
                requested_model_id=self._last_model_name,
                provider_class=provider_class,
                api_style=api_style,
                outcome_class=InvocationOutcomeClass.SUCCESS,
                streaming=self._last_streaming,
                input_tokens=usage.prompt_tokens or None,
                output_tokens=usage.completion_tokens or None,
                total_tokens=int(usage_data["total_tokens"])
                if "total_tokens" in usage_data
                else None,
                actual_model_id=model_id
                if model_id and model_id != self._last_model_name
                else None,
                actual_model_verified=model_id is not None,
                provider_response_id=response_id,
                provider_generation_id=response_id if is_routed else None,
                usage_verified=True,
                streaming_terminal_usage_verified=self._last_streaming,
                actual_provider_verified=None,
                safety_refusal_verified=None,
                cache_read_tokens=evidence.get("cache_read_tokens"),
                cache_read_verified=evidence.get("cache_read_verified"),
                reasoning_tokens=evidence.get("reasoning_tokens"),
                reasoning_tokens_verified=evidence.get("reasoning_tokens_verified"),
                gateway_total_cost=evidence.get("gateway_total_cost"),
                gateway_upstream_cost=evidence.get("gateway_upstream_cost"),
                gateway_cost_verified=evidence.get("gateway_cost_verified"),
                usage_evidence_source=evidence.get("usage_evidence_source"),
                gateway_provenance=evidence.get("gateway_provenance"),
                gateway_provenance_verified=evidence.get("gateway_provenance_verified"),
            )

        return LLMChunk(message=message, usage=usage, invocation_outcome=outcome)


def _provider_class_for_name(name: str) -> ProviderClass:
    if name == "openrouter":
        return ProviderClass.ROUTED_GATEWAY
    return ProviderClass.DIRECT_INFERENCE


def _extract_openrouter_evidence(
    usage_data: dict[str, Any], response_headers: dict[str, str]
) -> dict[str, Any]:
    """Extract rich OpenRouter inline usage and gateway provenance.

    Returns a dict of evidence fields for build_invocation_outcome.
    Never stores raw content, credentials, or prompt/completion text.
    """
    result: dict[str, Any] = {
        "cache_read_tokens": None,
        "cache_read_verified": None,
        "reasoning_tokens": None,
        "reasoning_tokens_verified": None,
        "gateway_total_cost": None,
        "gateway_upstream_cost": None,
        "gateway_cost_verified": None,
        "usage_evidence_source": None,
        "gateway_provenance": None,
        "gateway_provenance_verified": None,
    }
    evidence_source = UsageEvidenceSource.INLINE_RESPONSE.value

    # Inline rich usage
    prompt_details = usage_data.get("prompt_tokens_details", {}) or {}
    completion_details = usage_data.get("completion_tokens_details", {}) or {}
    if "cached_tokens" in prompt_details:
        result["cache_read_tokens"] = int(prompt_details["cached_tokens"])
        result["cache_read_verified"] = True
    if "reasoning_tokens" in completion_details:
        result["reasoning_tokens"] = int(completion_details["reasoning_tokens"])
        result["reasoning_tokens_verified"] = True
    if "cost" in usage_data and isinstance(usage_data["cost"], (int, float)):
        result["gateway_total_cost"] = float(usage_data["cost"])
        result["gateway_cost_verified"] = True
    cd = usage_data.get("cost_details") or {}
    if "upstream_inference_cost" in cd:
        result["gateway_upstream_cost"] = float(cd["upstream_inference_cost"])

    # Gateway provenance from response headers
    downstream = response_headers.get("x-provider", "").lower()
    downstream_model = response_headers.get("x-provider-model", "").lower() or None
    if downstream:
        result["gateway_provenance"] = GatewayProvenance(
            downstream_provider=downstream,
            downstream_model=downstream_model,
            provenance_source=GatewayProvenanceSource.RESPONSE_HEADER,
        )
        result["gateway_provenance_verified"] = True
        evidence_source = UsageEvidenceSource.RESPONSE_HEADER_PLUS_INLINE_USAGE.value
    else:
        result["gateway_provenance"] = GatewayProvenance(
            provenance_source=GatewayProvenanceSource.UNAVAILABLE
        )
        result["gateway_provenance_verified"] = False

    result["usage_evidence_source"] = evidence_source
    return result


_ADAPTERS: dict[str, APIAdapter] = {
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
}


def _get_adapter(api_style: str) -> APIAdapter:
    """Create or load the adapter for the given API style.

    OpenAI-compatible and Reasoning adapters return fresh instances
    per request to prevent shared mutable state contamination.
    """
    if api_style == "openai-responses":
        return OpenAIResponsesAdapter()
    if api_style == "openai":
        return OpenAIAdapter()
    if api_style == "reasoning":
        return ReasoningAdapter()
    if api_style not in _ADAPTERS:
        if api_style == "vertex-anthropic":
            from rig_relay.core.llm.backend.vertex import VertexAnthropicAdapter

            _ADAPTERS["vertex-anthropic"] = VertexAnthropicAdapter()
        else:
            raise KeyError(api_style)
    return _ADAPTERS[api_style]


class GenericBackend:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        provider: ProviderConfig,
        timeout: float = 720.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._provider = provider
        self._timeout = timeout

    async def __aenter__(self) -> GenericBackend:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                verify=build_ssl_context(),
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                verify=build_ssl_context(),
            )
            self._owns_client = True
        return self._client

    async def complete(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.2,
        tools: list[AvailableTool] | None = None,
        max_tokens: int | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> LLMChunk:
        api_key = (
            os.getenv(self._provider.api_key_env_var)
            if self._provider.api_key_env_var
            else None
        )

        # Per-invocation adapter (isolation from concurrent calls)
        adapter = _get_adapter(getattr(self._provider, "api_style", "openai"))

        req = adapter.prepare_request(
            model_name=model.name,
            messages=messages,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            tool_choice=tool_choice,
            enable_streaming=False,
            provider=self._provider,
            api_key=api_key,
            thinking=model.thinking,
        )

        headers = req.headers
        if extra_headers:
            headers.update(extra_headers)

        base = req.base_url or self._provider.api_base
        url = f"{base}{req.endpoint}"

        try:
            res_data, resp_headers = await self._make_request(url, req.body, headers)
            if hasattr(adapter, "_last_response_headers"):
                adapter._last_response_headers = dict(resp_headers.items())
            return adapter.parse_response(res_data, self._provider)

        except httpx.HTTPStatusError as e:
            raise BackendErrorBuilder.build_http_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e
        except httpx.RequestError as e:
            raise BackendErrorBuilder.build_request_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e

    async def complete_streaming(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.2,
        tools: list[AvailableTool] | None = None,
        max_tokens: int | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AsyncGenerator[LLMChunk, None]:
        api_key = (
            os.getenv(self._provider.api_key_env_var)
            if self._provider.api_key_env_var
            else None
        )

        # Per-invocation adapter (isolation from concurrent streams)
        adapter = _get_adapter(getattr(self._provider, "api_style", "openai"))

        req = adapter.prepare_request(
            model_name=model.name,
            messages=messages,
            temperature=temperature,
            tools=tools,
            max_tokens=max_tokens,
            tool_choice=tool_choice,
            enable_streaming=True,
            provider=self._provider,
            api_key=api_key,
            thinking=model.thinking,
        )

        headers = req.headers
        if extra_headers:
            headers.update(extra_headers)

        base = req.base_url or self._provider.api_base
        url = f"{base}{req.endpoint}"

        try:
            async for res_data in self._make_streaming_request(
                url, req.body, headers, adapter=adapter
            ):
                yield adapter.parse_response(res_data, self._provider)

        except httpx.HTTPStatusError as e:
            raise BackendErrorBuilder.build_http_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e
        except httpx.RequestError as e:
            raise BackendErrorBuilder.build_request_error(
                provider=self._provider.name,
                endpoint=url,
                error=e,
                model=model.name,
                messages=messages,
                temperature=temperature,
                has_tools=bool(tools),
                tool_choice=tool_choice,
            ) from e

    class HTTPResponse(NamedTuple):
        data: dict[str, Any]
        headers: dict[str, str]

    @async_retry(tries=3)
    async def _make_request(
        self, url: str, data: bytes, headers: dict[str, str]
    ) -> HTTPResponse:
        client = self._get_client()
        response = await client.post(url, content=data, headers=headers)
        response.raise_for_status()

        response_headers = dict(response.headers.items())
        response_body = response.json()
        return self.HTTPResponse(response_body, response_headers)

    @async_generator_retry(tries=3)
    async def _make_streaming_request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        adapter: APIAdapter | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        client = self._get_client()
        async with client.stream(
            method="POST", url=url, content=data, headers=headers
        ) as response:
            if not response.is_success:
                await response.aread()
            response.raise_for_status()
            # Capture response headers for provenance (OpenRouter gateway x-provider etc.)
            # Apply to adapter immediately so parse_response has them during streaming
            if adapter is not None and hasattr(adapter, "_last_response_headers"):
                adapter._last_response_headers = dict(response.headers.items())
            async for line in response.aiter_lines():
                if line.strip() == "":
                    continue

                DELIM_CHAR = ":"
                if f"{DELIM_CHAR} " not in line:
                    raise ValueError(
                        f"Stream chunk improperly formatted. "
                        f"Expected `key{DELIM_CHAR} value`, received `{line}`"
                    )
                delim_index = line.find(DELIM_CHAR)
                key = line[0:delim_index]
                value = line[delim_index + 2 :]

                if key != "data":
                    # This might be the case with openrouter, so we just ignore it
                    continue
                if value == "[DONE]":
                    return
                yield json.loads(value.strip())

    async def count_tokens(
        self,
        *,
        model: ModelConfig,
        messages: Sequence[LLMMessage],
        temperature: float = 0.0,
        tools: list[AvailableTool] | None = None,
        tool_choice: StrToolChoice | AvailableTool | None = None,
        extra_headers: dict[str, str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> int:
        probe_messages = list(messages)
        if not probe_messages or probe_messages[-1].role != Role.user:
            probe_messages.append(LLMMessage(role=Role.user, content=""))

        result = await self.complete(
            model=model,
            messages=probe_messages,
            temperature=temperature,
            tools=tools,
            max_tokens=16,  # Minimal amount for openrouter with openai models
            tool_choice=tool_choice,
            extra_headers=extra_headers,
        )
        if result.usage is None:
            raise ValueError("Missing usage in non streaming completion")

        return result.usage.prompt_tokens

    async def close(self) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None
