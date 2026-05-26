"""Native Gemini adapter — maps LLMMessage to Google Gemini generateContent API.

Implements the APIAdapter Protocol for the Gemini native API surface.
Does NOT route through OpenAI compatibility. Does NOT implement function
calling or structured output in this bounded slice.

Auth: x-goog-api-key header (preferred by Google for server-side).
Streaming: SSE via :streamGenerateContent?alt=sse endpoint.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any, ClassVar

from rig_relay.core.config import ProviderConfig
from rig_relay.core.llm.backend.base import APIAdapter, PreparedRequest
from rig_relay.core.llm.message_utils import merge_consecutive_user_messages
from rig_relay.core.types import (
    AvailableTool,
    LLMChunk,
    LLMMessage,
    LLMUsage,
    Role,
    StrToolChoice,
)


class GeminiMapper:
    """Convert Rig Relay messages to/from Gemini native API format.

    Gemini uses a ``contents`` array with ``role`` / ``parts`` entries
    and an optional top-level ``system_instruction`` object.
    """

    def prepare_contents(
        self, messages: Sequence[LLMMessage]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        system_instruction: dict[str, Any] | None = None
        contents: list[dict[str, Any]] = []

        for msg in messages:
            match msg.role:
                case Role.system:
                    if msg.content:
                        system_instruction = {"parts": [{"text": msg.content}]}
                case Role.user:
                    parts: list[dict[str, Any]] = []
                    if msg.content:
                        parts.append({"text": msg.content})
                    if parts:
                        contents.append({"role": "user", "parts": parts})
                case Role.assistant:
                    model_parts: list[dict[str, Any]] = []
                    if msg.content:
                        model_parts.append({"text": msg.content})
                    if model_parts:
                        contents.append({"role": "model", "parts": model_parts})
                case Role.tool:
                    # Tool results not yet supported — silently drop.
                    # Future: convert to functionResponse parts.
                    pass

        return system_instruction, contents


_GEMINI_CONTENT_ENDPOINT = "/v1beta/models/{model}:generateContent"
_GEMINI_STREAM_ENDPOINT = "/v1beta/models/{model}:streamGenerateContent"


class GeminiAdapter(APIAdapter):
    """Native Gemini generateContent adapter.

    Supports text-only completion and streaming. Tool use, structured output,
    reasoning/thinking, and vision are not implemented in this bounded slice.
    """

    endpoint: ClassVar[str] = ""

    _GEMINI_VERSION = "v1beta"

    def __init__(self) -> None:
        self._mapper = GeminiMapper()

    def _build_generation_config(
        self, temperature: float, max_tokens: int | None, thinking: str
    ) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        # TODO: map thinking modes to Gemini thinkingConfig when available
        return config

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
        merged_messages = merge_consecutive_user_messages(messages)
        system_instruction, contents = self._mapper.prepare_contents(merged_messages)

        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": self._build_generation_config(
                temperature, max_tokens, thinking
            ),
        }
        if system_instruction is not None:
            payload["system_instruction"] = system_instruction

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["x-goog-api-key"] = api_key

        if enable_streaming:
            endpoint = f"{_GEMINI_STREAM_ENDPOINT}?alt=sse".format(model=model_name)
        else:
            endpoint = _GEMINI_CONTENT_ENDPOINT.format(model=model_name)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return PreparedRequest(endpoint, headers, body)

    def _extract_text(self, candidate: dict[str, Any]) -> str | None:
        content = candidate.get("content")
        if not content:
            return None
        parts = content.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        return "".join(text_parts) or None

    def _check_safety_refusal(self, data: dict[str, Any]) -> str | None:
        """Return refusal reason if response was blocked by safety filters."""
        prompt_feedback = data.get("promptFeedback")
        if prompt_feedback and prompt_feedback.get("blockReason"):
            return f"SAFETY_BLOCK: {prompt_feedback['blockReason']}"

        candidates = data.get("candidates", [])
        for c in candidates:
            finish_reason = c.get("finishReason", "")
            if finish_reason == "SAFETY":
                ratings = c.get("safetyRatings", [])
                blocked = [
                    r.get("category", "unknown") for r in ratings if r.get("blocked")
                ]
                return f"SAFETY_REFUSAL: {', '.join(blocked) if blocked else 'unknown_category'}"

        return None

    def _check_error(self, data: dict[str, Any]) -> str | None:
        err = data.get("error")
        if err:
            code = err.get("code", "unknown")
            message = err.get("message", "unknown error")
            return f"Gemini error {code}: {message}"
        return None

    def parse_response(
        self, data: dict[str, Any], provider: ProviderConfig
    ) -> LLMChunk:
        error_msg = self._check_error(data)
        if error_msg is not None:
            return LLMChunk(
                message=LLMMessage(role=Role.assistant, content=error_msg),
                usage=LLMUsage(prompt_tokens=0, completion_tokens=0),
            )

        safety_refusal = self._check_safety_refusal(data)
        if safety_refusal is not None:
            return LLMChunk(
                message=LLMMessage(role=Role.assistant, content=safety_refusal),
                usage=LLMUsage(prompt_tokens=0, completion_tokens=0),
            )

        candidates = data.get("candidates", [])
        text_parts: list[str] = []
        for c in candidates:
            text = self._extract_text(c)
            if text:
                text_parts.append(text)

        text_content = "".join(text_parts) if text_parts else None

        usage_meta = data.get("usageMetadata", {})
        usage = LLMUsage(
            prompt_tokens=usage_meta.get("promptTokenCount", 0),
            completion_tokens=usage_meta.get("candidatesTokenCount", 0),
        )

        return LLMChunk(
            message=LLMMessage(role=Role.assistant, content=text_content or ""),
            usage=usage,
        )
