"""Boundary tests for native Gemini adapter.

Uses respx to simulate the real Gemini generateContent API at the
HTTP transport boundary. Does not mock adapter internals.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from rig_relay.core.config import ModelConfig, ProviderConfig
from rig_relay.core.llm.backend.gemini import GeminiAdapter
from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.types import LLMChunk, LLMMessage, Role
from tests.backend.data.gemini import (
    GEMINI_EMPTY_CANDIDATES_RESPONSE,
    GEMINI_ERROR_RESPONSE,
    GEMINI_SAFETY_BLOCK_RESPONSE,
    GEMINI_SAFETY_REFUSAL_RESPONSE,
    GEMINI_SIMPLE_TEXT_RESPONSE,
    GEMINI_SIMPLE_TEXT_RESULT,
    GEMINI_STREAM_CHUNKS,
    GEMINI_STREAM_RESULTS,
    GEMINI_TEST_BASE_URL,
)


@pytest.fixture
def gemini_provider() -> ProviderConfig:
    return ProviderConfig(
        name="google",
        api_base=GEMINI_TEST_BASE_URL,
        api_key_env_var="GEMINI_API_KEY",
        api_style="gemini",
    )


@pytest.fixture
def gemini_model() -> ModelConfig:
    return ModelConfig(
        name="gemini-2.0-flash",
        provider="google",
        alias="gemini-2.0-flash",
        temperature=0.7,
    )


class TestGeminiAdapterDirectly:
    """Tests against GeminiAdapter directly — transport boundary only."""

    def test_prepare_request_includes_x_goog_api_key(self, gemini_provider):
        adapter = GeminiAdapter()
        req = adapter.prepare_request(
            model_name="gemini-2.0-flash",
            messages=[LLMMessage(role=Role.user, content="Hello")],
            temperature=0.7,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=False,
            provider=gemini_provider,
            api_key="test-gemini-key",
        )
        assert req.headers["x-goog-api-key"] == "test-gemini-key"
        assert "Authorization" not in req.headers

    def test_prepare_request_no_api_key_in_header_when_none(self, gemini_provider):
        adapter = GeminiAdapter()
        req = adapter.prepare_request(
            model_name="gemini-2.0-flash",
            messages=[LLMMessage(role=Role.user, content="Hello")],
            temperature=0.7,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=False,
            provider=gemini_provider,
            api_key=None,
        )
        assert "x-goog-api-key" not in req.headers

    def test_generate_content_endpoint(self, gemini_provider):
        adapter = GeminiAdapter()
        req = adapter.prepare_request(
            model_name="gemini-2.0-flash",
            messages=[LLMMessage(role=Role.user, content="Hello")],
            temperature=0.7,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=False,
            provider=gemini_provider,
            api_key="key",
        )
        assert "gemini-2.0-flash:generateContent" in req.endpoint
        assert "alt=sse" not in req.endpoint

    def test_stream_endpoint(self, gemini_provider):
        adapter = GeminiAdapter()
        req = adapter.prepare_request(
            model_name="gemini-2.0-flash",
            messages=[LLMMessage(role=Role.user, content="Hello")],
            temperature=0.7,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=True,
            provider=gemini_provider,
            api_key="key",
        )
        assert "streamGenerateContent" in req.endpoint
        assert "alt=sse" in req.endpoint

    def test_system_instruction_in_payload(self, gemini_provider):
        adapter = GeminiAdapter()
        req = adapter.prepare_request(
            model_name="gemini-2.0-flash",
            messages=[
                LLMMessage(role=Role.system, content="You are helpful."),
                LLMMessage(role=Role.user, content="Hello"),
            ],
            temperature=0.7,
            tools=None,
            max_tokens=None,
            tool_choice=None,
            enable_streaming=False,
            provider=gemini_provider,
            api_key="key",
        )
        import json

        body = json.loads(req.body.decode())
        assert "system_instruction" in body
        assert body["system_instruction"]["parts"][0]["text"] == "You are helpful."

    def test_parse_simple_text_response(self, gemini_provider):
        adapter = GeminiAdapter()
        result = adapter.parse_response(GEMINI_SIMPLE_TEXT_RESPONSE, gemini_provider)
        assert result.message.content == GEMINI_SIMPLE_TEXT_RESULT["message"]
        assert result.usage is not None
        assert (
            result.usage.prompt_tokens
            == GEMINI_SIMPLE_TEXT_RESULT["usage"]["prompt_tokens"]
        )
        assert (
            result.usage.completion_tokens
            == GEMINI_SIMPLE_TEXT_RESULT["usage"]["completion_tokens"]
        )

    def test_parse_safety_refusal(self, gemini_provider):
        adapter = GeminiAdapter()
        result = adapter.parse_response(GEMINI_SAFETY_REFUSAL_RESPONSE, gemini_provider)
        assert result.message.content is not None
        assert "SAFETY_REFUSAL" in result.message.content

    def test_parse_safety_block(self, gemini_provider):
        adapter = GeminiAdapter()
        result = adapter.parse_response(GEMINI_SAFETY_BLOCK_RESPONSE, gemini_provider)
        assert result.message.content is not None
        assert "SAFETY_BLOCK" in result.message.content

    def test_parse_empty_candidates(self, gemini_provider):
        adapter = GeminiAdapter()
        result = adapter.parse_response(
            GEMINI_EMPTY_CANDIDATES_RESPONSE, gemini_provider
        )
        assert result.message.content == ""

    def test_parse_error_response(self, gemini_provider):
        adapter = GeminiAdapter()
        result = adapter.parse_response(GEMINI_ERROR_RESPONSE, gemini_provider)
        assert "API key not valid" in (result.message.content or "")


class TestGeminiThroughGenericBackend:
    """Tests GeminiAdapter through GenericBackend — full adapter resolution path."""

    @pytest.mark.asyncio
    async def test_backend_resolves_gemini_adapter(self, gemini_provider, gemini_model):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock_api:
            endpoint = "/v1beta/models/gemini-2.0-flash:generateContent"
            mock_api.post(endpoint).mock(
                return_value=httpx.Response(
                    status_code=200, json=GEMINI_SIMPLE_TEXT_RESPONSE
                )
            )
            backend = GenericBackend(provider=gemini_provider)
            messages = [LLMMessage(role=Role.user, content="Just say hi")]
            result = await backend.complete(
                model=gemini_model,
                messages=messages,
                temperature=0.2,
                tools=None,
                max_tokens=None,
                tool_choice=None,
                extra_headers=None,
            )
            assert result.message.content == GEMINI_SIMPLE_TEXT_RESULT["message"]
            assert result.usage is not None

    @pytest.mark.asyncio
    async def test_backend_streaming_resolves_gemini_adapter(
        self, gemini_provider, gemini_model
    ):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock_api:
            endpoint = "/v1beta/models/gemini-2.0-flash:streamGenerateContent"
            mock_api.post(endpoint).mock(
                return_value=httpx.Response(
                    status_code=200,
                    stream=httpx.ByteStream(stream=b"\n".join(GEMINI_STREAM_CHUNKS)),
                    headers={"Content-Type": "text/event-stream"},
                )
            )
            backend = GenericBackend(provider=gemini_provider)
            messages = [LLMMessage(role=Role.user, content="Say hello")]
            results: list[LLMChunk] = []
            async for result in backend.complete_streaming(
                model=gemini_model,
                messages=messages,
                temperature=0.2,
                tools=None,
                max_tokens=None,
                tool_choice=None,
                extra_headers=None,
            ):
                results.append(result)

            assert len(results) == len(GEMINI_STREAM_RESULTS)
            for result, expected in zip(results, GEMINI_STREAM_RESULTS, strict=True):
                assert result.message.content == expected["message"]

    @pytest.mark.asyncio
    async def test_backend_http_error_surfaces_as_backend_error(
        self, gemini_provider, gemini_model
    ):
        from rig_relay.core.llm.exceptions import BackendError

        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock_api:
            endpoint = "/v1beta/models/gemini-2.0-flash:generateContent"
            mock_api.post(endpoint).mock(
                return_value=httpx.Response(status_code=403, json=GEMINI_ERROR_RESPONSE)
            )
            backend = GenericBackend(provider=gemini_provider)
            messages = [LLMMessage(role=Role.user, content="hi")]
            with pytest.raises(BackendError) as exc_info:
                await backend.complete(
                    model=gemini_model,
                    messages=messages,
                    temperature=0.2,
                    tools=None,
                    max_tokens=None,
                    tool_choice=None,
                    extra_headers=None,
                )
            assert exc_info.value.status == 403

    @pytest.mark.asyncio
    async def test_streaming_http_error_surfaces_as_backend_error(
        self, gemini_provider, gemini_model
    ):
        from rig_relay.core.llm.exceptions import BackendError

        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock_api:
            endpoint = "/v1beta/models/gemini-2.0-flash:streamGenerateContent"
            mock_api.post(endpoint).mock(
                return_value=httpx.Response(status_code=503, text="Service Unavailable")
            )
            backend = GenericBackend(provider=gemini_provider)
            messages = [LLMMessage(role=Role.user, content="hi")]
            with pytest.raises(BackendError) as exc_info:
                async for _ in backend.complete_streaming(
                    model=gemini_model,
                    messages=messages,
                    temperature=0.2,
                    tools=None,
                    max_tokens=None,
                    tool_choice=None,
                    extra_headers=None,
                ):
                    pass
            assert exc_info.value.status == 503

    @pytest.mark.asyncio
    async def test_credentials_not_in_result(self, gemini_provider, gemini_model):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock_api:
            endpoint = "/v1beta/models/gemini-2.0-flash:generateContent"
            mock_api.post(endpoint).mock(
                return_value=httpx.Response(
                    status_code=200, json=GEMINI_SIMPLE_TEXT_RESPONSE
                )
            )
            backend = GenericBackend(provider=gemini_provider)
            messages = [LLMMessage(role=Role.user, content="hi")]
            result = await backend.complete(
                model=gemini_model,
                messages=messages,
                temperature=0.2,
                tools=None,
                max_tokens=None,
                tool_choice=None,
                extra_headers=None,
            )
            content = result.message.content or ""
            assert "test-gemini-key" not in content
            assert "GEMINI_API_KEY" not in content


class TestGeminiNoToolOrStructuredClaims:
    """Verify the adapter does not claim unsupported capabilities."""

    def test_gemini_capability_record_marks_tools_unavailable(self):
        from rig_relay.providers.registry import get_provider_capability

        cap = get_provider_capability("google")
        assert cap is not None
        assert cap.verified_tool_use is False
        assert cap.verified_structured_output is False
        assert cap.verified_thinking is False
        assert cap.verified_caching is False
        assert cap.verified_streaming is True

    def test_gemini_capability_has_notes_explaining_unsupported(self):
        from rig_relay.providers.registry import get_provider_capability

        cap = get_provider_capability("google")
        assert cap is not None
        joined = " ".join(cap.notes).lower()
        assert "tool_use" in joined
        assert "not yet implemented" in joined
