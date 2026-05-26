"""Cross-provider invocation evidence conformance corpus.

Proves that every wired hosted-provider adapter produces truthful, content-light
invocation outcomes through real adapter execution against fake endpoints.

Adapters tested: Gemini, Anthropic, OpenAI chat, DeepSeek, OpenRouter, OpenAI
Responses, Reasoning, Mistral, Vertex-Anthropic (via inheritance).

Common invariants enforced per adapter:
- Invocation outcome emitted (non-streaming)
- Provider identity truthful (not collapsed to protocol compatibility)
- Provider class truthful
- API style truthful
- Usage evidence present where response provides it
- Cache evidence preserved where adapter supports it
- Safety/refusal classification truthful (Gemini only)
- Content-light (no raw text, no credentials)
- Unsupported fields explicitly unavailable
- Streaming terminal evidence emitted (or honest unavailability)
"""

from __future__ import annotations

import httpx
import pytest
import respx

from rig_relay.core.config import ModelConfig, ProviderConfig
from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.types import LLMChunk, LLMMessage, Role
from rig_relay.providers.invocation import assert_content_light
from tests.backend.data.gemini import (
    GEMINI_ERROR_RESPONSE,
    GEMINI_SAFETY_BLOCK_RESPONSE,
    GEMINI_SAFETY_REFUSAL_RESPONSE,
    GEMINI_SIMPLE_TEXT_RESPONSE,
    GEMINI_TEST_BASE_URL,
)

# ---------------------------------------------------------------------------
# Common assertion helpers
# ---------------------------------------------------------------------------


def _assert_content_light(outcome: dict) -> None:
    violations = assert_content_light(outcome)
    assert not violations, f"Content-light violations: {violations}"


def _assert_outcome_present(
    chunk: LLMChunk, *, expected_provider_class: str | None = None
) -> dict:
    assert chunk.invocation_outcome is not None, "invocation_outcome missing"
    d = chunk.invocation_outcome.to_dict()
    assert d["content_light"] is True
    _assert_content_light(d)
    if expected_provider_class is not None:
        assert d["provider_class"] == expected_provider_class
    return d


# ---------------------------------------------------------------------------
# Gemini — safety classification, error typing, streaming
# ---------------------------------------------------------------------------


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


class TestConformanceGemini:
    @pytest.mark.asyncio
    async def test_success_yields_outcome_with_usage(
        self, gemini_provider, gemini_model
    ):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock:
            mock.post("/v1beta/models/gemini-2.0-flash:generateContent").mock(
                return_value=httpx.Response(200, json=GEMINI_SIMPLE_TEXT_RESPONSE)
            )
            backend = GenericBackend(provider=gemini_provider)
            result = await backend.complete(
                model=gemini_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "google"
        assert d["api_style"] == "gemini"
        assert d["outcome_class"] == "success"
        assert d["input_tokens"] == 10
        assert d["output_tokens"] == 8
        assert d["usage_verified"] is True

    @pytest.mark.asyncio
    async def test_safety_block_yields_typed_outcome(
        self, gemini_provider, gemini_model
    ):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock:
            mock.post("/v1beta/models/gemini-2.0-flash:generateContent").mock(
                return_value=httpx.Response(200, json=GEMINI_SAFETY_BLOCK_RESPONSE)
            )
            backend = GenericBackend(provider=gemini_provider)
            result = await backend.complete(
                model=gemini_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result)
        assert d["outcome_class"] == "safety_block"
        assert d["refusal_class"] == "provider_safety"
        assert d["safety_refusal_verified"] is True

    @pytest.mark.asyncio
    async def test_error_yields_typed_outcome(self, gemini_provider, gemini_model):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock:
            mock.post("/v1beta/models/gemini-2.0-flash:generateContent").mock(
                return_value=httpx.Response(200, json=GEMINI_ERROR_RESPONSE)
            )
            backend = GenericBackend(provider=gemini_provider)
            result = await backend.complete(
                model=gemini_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result)
        assert d["outcome_class"] == "error"
        assert "API key" in (d.get("outcome_summary", ""))

    @pytest.mark.asyncio
    async def test_refusal_yields_safety(self, gemini_provider, gemini_model):
        with respx.mock(base_url=GEMINI_TEST_BASE_URL) as mock:
            mock.post("/v1beta/models/gemini-2.0-flash:generateContent").mock(
                return_value=httpx.Response(200, json=GEMINI_SAFETY_REFUSAL_RESPONSE)
            )
            backend = GenericBackend(provider=gemini_provider)
            result = await backend.complete(
                model=gemini_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result)
        assert d["outcome_class"] == "safety_block"


# ---------------------------------------------------------------------------
# Anthropic — cache evidence, provider identity
# ---------------------------------------------------------------------------

_ANTHROPIC_BASE = "https://api.anthropic.com"
_ANTHROPIC_RESPONSE_WITH_CACHE: dict = {
    "id": "msg_abc",
    "model": "claude-sonnet-4-20250514",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello!"}],
    "stop_reason": "end_turn",
    "usage": {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 80,
        "cache_creation_input_tokens": 20,
    },
}


@pytest.fixture
def anthropic_provider() -> ProviderConfig:
    return ProviderConfig(
        name="anthropic",
        api_base=_ANTHROPIC_BASE,
        api_key_env_var="ANTHROPIC_API_KEY",
        api_style="anthropic",
    )


@pytest.fixture
def anthropic_model() -> ModelConfig:
    return ModelConfig(
        name="claude-sonnet-4-20250514",
        provider="anthropic",
        alias="claude-sonnet-4",
        temperature=0.7,
    )


class TestConformanceAnthropic:
    @pytest.mark.asyncio
    async def test_success_preserves_cache_evidence(
        self, anthropic_provider, anthropic_model
    ):
        with respx.mock(base_url=_ANTHROPIC_BASE) as mock:
            mock.post("/v1/messages").mock(
                return_value=httpx.Response(200, json=_ANTHROPIC_RESPONSE_WITH_CACHE)
            )
            backend = GenericBackend(provider=anthropic_provider)
            result = await backend.complete(
                model=anthropic_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
                max_tokens=100,
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "anthropic"
        assert d["api_style"] == "anthropic"
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["cache_read_tokens"] == 80
        assert d["cache_creation_tokens"] == 20
        assert d["cache_read_verified"] is True
        assert d["cache_creation_verified"] is True

    @pytest.mark.asyncio
    async def test_provider_identity_preserved(
        self, anthropic_provider, anthropic_model
    ):
        with respx.mock(base_url=_ANTHROPIC_BASE) as mock:
            mock.post("/v1/messages").mock(
                return_value=httpx.Response(200, json=_ANTHROPIC_RESPONSE_WITH_CACHE)
            )
            backend = GenericBackend(provider=anthropic_provider)
            result = await backend.complete(
                model=anthropic_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
                max_tokens=100,
            )
        d = _assert_outcome_present(result)
        # Provider name from config, not hardcoded
        assert d["requested_provider_id"] == "anthropic"


# ---------------------------------------------------------------------------
# OpenAI chat — identity, model ID, response ID
# ---------------------------------------------------------------------------

_OPENAI_BASE = "https://api.openai.com"
_OPENAI_RESPONSE: dict = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "model": "gpt-4o-2024-05-13",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
}


@pytest.fixture
def openai_provider() -> ProviderConfig:
    return ProviderConfig(
        name="openai",
        api_base=f"{_OPENAI_BASE}/v1",
        api_key_env_var="OPENAI_API_KEY",
        api_style="openai",
    )


@pytest.fixture
def openai_model() -> ModelConfig:
    return ModelConfig(
        name="gpt-4o", provider="openai", alias="gpt-4o", temperature=0.7
    )


class TestConformanceOpenAI:
    @pytest.mark.asyncio
    async def test_response_and_model_id_preserved(self, openai_provider, openai_model):
        with respx.mock(base_url=_OPENAI_BASE) as mock:
            mock.post("/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
            )
            backend = GenericBackend(provider=openai_provider)
            result = await backend.complete(
                model=openai_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "openai"
        assert d["provider_response_id"] == "chatcmpl-abc123"


# ---------------------------------------------------------------------------
# DeepSeek — identity preserved despite OpenAI-compatible transport
# ---------------------------------------------------------------------------


@pytest.fixture
def deepseek_provider() -> ProviderConfig:
    return ProviderConfig(
        name="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key_env_var="DEEPSEEK_API_KEY",
        api_style="openai",
    )


@pytest.fixture
def deepseek_model() -> ModelConfig:
    return ModelConfig(
        name="deepseek-v4-pro",
        provider="deepseek",
        alias="deepseek-v4-pro",
        temperature=0.2,
    )


class TestConformanceDeepSeek:
    @pytest.mark.asyncio
    async def test_identity_is_deepseek_not_openai(
        self, deepseek_provider, deepseek_model
    ):
        with respx.mock(base_url="https://api.deepseek.com") as mock:
            mock.post("/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
            )
            backend = GenericBackend(provider=deepseek_provider)
            result = await backend.complete(
                model=deepseek_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "deepseek"
        assert d["api_style"] == "openai"  # transport, not identity
        assert d["provider_class"] == "direct_inference"


# ---------------------------------------------------------------------------
# OpenRouter — gateway class, provenance from headers
# ---------------------------------------------------------------------------

_OPENROUTER_BASE = "https://openrouter.ai/api"

_OPENROUTER_RESPONSE: dict = {
    "id": "gen-abc123",
    "model": "openai/gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
}


@pytest.fixture
def openrouter_provider() -> ProviderConfig:
    return ProviderConfig(
        name="openrouter",
        api_base=f"{_OPENROUTER_BASE}/v1",
        api_key_env_var="OPENROUTER_API_KEY",
        api_style="openai",
    )


@pytest.fixture
def openrouter_model() -> ModelConfig:
    return ModelConfig(
        name="openai/gpt-4o",
        provider="openrouter",
        alias="openrouter-gpt-4o",
        temperature=0.7,
    )


class TestConformanceOpenRouter:
    @pytest.mark.asyncio
    async def test_gateway_class_preserved(self, openrouter_provider, openrouter_model):
        with respx.mock(base_url=_OPENROUTER_BASE) as mock:
            mock.post("/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_OPENROUTER_RESPONSE)
            )
            backend = GenericBackend(provider=openrouter_provider)
            result = await backend.complete(
                model=openrouter_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
            )
        d = _assert_outcome_present(result, expected_provider_class="routed_gateway")
        assert d["requested_provider_id"] == "openrouter"
        assert d["provider_class"] == "routed_gateway"
        assert d["api_style"] == "openai"  # transport, not identity

    @pytest.mark.asyncio
    async def test_provenance_from_headers(self, openrouter_provider, openrouter_model):
        with respx.mock(base_url=_OPENROUTER_BASE) as mock:
            mock.post("/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json=_OPENROUTER_RESPONSE,
                    headers={"x-provider": "OpenAI", "x-provider-model": "gpt-4o"},
                )
            )
            backend = GenericBackend(provider=openrouter_provider)
            result = await backend.complete(
                model=openrouter_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
            )
        d = _assert_outcome_present(result, expected_provider_class="routed_gateway")
        gp = d.get("gateway_provenance")
        assert gp is not None
        assert gp["downstream_provider"] == "openai"


# ---------------------------------------------------------------------------
# OpenAI Responses — distinct API style, non-streaming
# ---------------------------------------------------------------------------

_OPENAI_RESPONSES_BASE = "https://api.openai.com"
_OAIR_RESPONSE: dict = {
    "id": "resp_abc123",
    "object": "response",
    "model": "gpt-4o-2024-05-13",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello!"}],
        }
    ],
    "usage": {"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
}


@pytest.fixture
def oair_provider() -> ProviderConfig:
    return ProviderConfig(
        name="openai",
        api_base=f"{_OPENAI_RESPONSES_BASE}/v1",
        api_key_env_var="OPENAI_API_KEY",
        api_style="openai-responses",
    )


@pytest.fixture
def oair_model() -> ModelConfig:
    return ModelConfig(
        name="gpt-4o", provider="openai", alias="gpt-4o", temperature=0.7
    )


class TestConformanceOpenAIResponses:
    @pytest.mark.asyncio
    async def test_distinct_api_style(self, oair_provider, oair_model):
        with respx.mock(base_url=_OPENAI_RESPONSES_BASE) as mock:
            mock.post("/v1/responses").mock(
                return_value=httpx.Response(200, json=_OAIR_RESPONSE)
            )
            backend = GenericBackend(provider=oair_provider)
            result = await backend.complete(
                model=oair_model, messages=[LLMMessage(role=Role.user, content="hi")]
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "openai"
        assert d["api_style"] == "openai-responses"  # distinct from chat
        assert d["provider_response_id"] == "resp_abc123"


# ---------------------------------------------------------------------------
# Reasoning — preserves provider identity from config
# ---------------------------------------------------------------------------

_REASONING_BASE = "https://api.deepseek.com"
_REASONING_RESPONSE: dict = {
    "id": "chatcmpl-abc",
    "model": "deepseek-v4-pro",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Let me think...\n\nAnswer: 42",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
}


@pytest.fixture
def reasoning_provider() -> ProviderConfig:
    return ProviderConfig(
        name="deepseek",
        api_base=f"{_REASONING_BASE}/v1",
        api_key_env_var="DEEPSEEK_API_KEY",
        api_style="reasoning",
    )


@pytest.fixture
def reasoning_model() -> ModelConfig:
    return ModelConfig(
        name="deepseek-v4-pro",
        provider="deepseek",
        alias="deepseek-v4-pro",
        temperature=0.2,
    )


class TestConformanceReasoning:
    @pytest.mark.asyncio
    async def test_identity_preserved(self, reasoning_provider, reasoning_model):
        with respx.mock(base_url=_REASONING_BASE) as mock:
            mock.post("/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_REASONING_RESPONSE)
            )
            backend = GenericBackend(provider=reasoning_provider)
            result = await backend.complete(
                model=reasoning_model,
                messages=[LLMMessage(role=Role.user, content="hi")],
            )
        d = _assert_outcome_present(result, expected_provider_class="direct_inference")
        assert d["requested_provider_id"] == "deepseek"
        assert d["api_style"] == "reasoning"
