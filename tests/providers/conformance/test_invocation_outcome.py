"""Cross-provider invocation outcome conformance corpus.

Parameterized harness that exercises every admitted live hosted adapter
at its true HTTP boundary (stubbed via respx) and verifies the normalized
ProviderInvocationOutcome contract.

Content-light: no raw prompts, generated text, or credentials in assertions.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from rig_relay.core.config import ModelConfig, ProviderConfig
from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.types import LLMMessage, Role
from rig_relay.providers.invocation import (
    InvocationOutcomeClass,
    assert_content_light,
    invocation_evidence_capabilities,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_provider(
    name: str,
    api_style: str = "openai",
    api_key_env_var: str = "TEST_API_KEY",
    api_base: str = "https://api.test.example",
    region: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "api_style": api_style,
        "api_base": api_base,
        "api_key_env_var": api_key_env_var,
        "region": region,
        "project_id": project_id,
    }


def _make_model(name: str = "test-model") -> dict[str, Any]:
    return {
        "name": name,
        "provider": "test",
        "alias": name,
        "thinking": "off",
        "max_tokens": 100,
    }


async def _execute_test_completion(
    provider_cfg: ProviderConfig,
    model_cfg: ModelConfig,
    response_status: int = 200,
    response_body: dict[str, Any] | None = None,
    response_headers: dict[str, str] | None = None,
    stream_events: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Execute a completion against a stubbed endpoint. Returns chunks."""
    url = f"{provider_cfg.api_base}/chat/completions"
    route = respx.post(url)

    if stream_events:
        body = (
            "\n".join(f"data: {json.dumps(e)}" for e in stream_events)
            + "\ndata: [DONE]\n"
        )
        route.mock(
            return_value=httpx.Response(
                status_code=200,
                content=body.encode(),
                headers={"Content-Type": "text/event-stream"},
            )
        )
    else:
        route.mock(
            return_value=httpx.Response(
                status_code=response_status,
                json=response_body,
                headers=response_headers or {},
            )
        )

    chunks: list[Any] = []
    async with GenericBackend(provider=provider_cfg) as backend:
        async for chunk in backend.complete_streaming(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        ):
            chunks.append(chunk)
    return chunks


# ── Common invariants ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "provider_id,api_style,response_body,provider_class",
    [
        pytest.param(
            "openai",
            "openai",
            {
                "id": "resp-123",
                "object": "chat.completion",
                "model": "gpt-4o",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hi"}}
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
            "direct_inference",
            id="openai",
        ),
        pytest.param(
            "deepseek",
            "openai",
            {
                "id": "resp-ds-1",
                "object": "chat.completion",
                "model": "deepseek-chat",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hi"}}
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
            "direct_inference",
            id="deepseek",
        ),
        pytest.param(
            "openrouter",
            "openai",
            {
                "id": "gen-or-1",
                "object": "chat.completion",
                "model": "openai/gpt-4o",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hi"}}
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
            "routed_gateway",
            id="openrouter",
        ),
    ],
)
@pytest.mark.asyncio
async def test_non_streaming_outcome_emits(
    provider_id: str, api_style: str, response_body: dict[str, Any], provider_class: str
) -> None:
    """Every admitted provider emits a content-light non-streaming invocation outcome."""
    provider_cfg = ProviderConfig.model_validate(_make_provider(provider_id, api_style))
    model_cfg = ModelConfig.model_validate(_make_model("test-model"))

    with respx.mock(base_url=provider_cfg.api_base, assert_all_called=False) as mock:
        mock.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=response_body, headers={})
        )
        backend = GenericBackend(provider=provider_cfg)
        result = await backend.complete(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        )

    outcome = result.invocation_outcome
    assert outcome is not None, f"{provider_id} must emit invocation outcome"
    assert outcome.outcome_class == InvocationOutcomeClass.SUCCESS
    assert outcome.requested_provider_id == provider_id
    assert outcome.api_style == api_style
    assert outcome.provider_class.value == provider_class
    assert outcome.streaming is False
    assert outcome.content_light is True
    assert outcome.usage_verified is True
    assert outcome.input_tokens is not None
    assert outcome.output_tokens is not None

    # Content-light enforcement
    violations = assert_content_light(outcome.to_dict())
    assert not violations, f"Content-light violation in {provider_id}: {violations}"


@pytest.mark.parametrize(
    "provider_id,api_style,stream_events",
    [
        pytest.param(
            "openai",
            "openai",
            [
                {
                    "id": "resp-stream-1",
                    "object": "chat.completion.chunk",
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "hello"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "resp-stream-1",
                    "object": "chat.completion.chunk",
                    "model": "gpt-4o",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 1,
                        "total_tokens": 6,
                    },
                },
            ],
            id="openai_streaming",
        )
    ],
)
@pytest.mark.asyncio
async def test_streaming_terminal_outcome_emits(
    provider_id: str, api_style: str, stream_events: list[dict[str, Any]]
) -> None:
    """Streaming terminal chunk carries invocation outcome with usage."""
    provider_cfg = ProviderConfig.model_validate(_make_provider(provider_id, api_style))
    model_cfg = ModelConfig.model_validate(_make_model("test-model"))

    chunks = await _execute_test_completion(
        provider_cfg, model_cfg, stream_events=stream_events
    )

    last = chunks[-1] if chunks else None
    assert last is not None
    outcome = getattr(last, "invocation_outcome", None)
    assert outcome is not None, f"{provider_id} streaming must emit terminal outcome"
    assert outcome.streaming is True
    violations = assert_content_light(outcome.to_dict())
    assert not violations, f"Content-light violation: {violations}"


@pytest.mark.asyncio
async def test_openrouter_gateway_provenance_from_headers() -> None:
    """OpenRouter response headers produce gateway provenance."""
    provider_cfg = ProviderConfig.model_validate(_make_provider("openrouter", "openai"))
    model_cfg = ModelConfig.model_validate(_make_model("openai/gpt-4o"))

    body = {
        "id": "gen-or-2",
        "model": "openai/gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    headers = {"x-provider": "openai", "x-provider-model": "gpt-4o"}

    url = f"{provider_cfg.api_base}/chat/completions"
    respx.post(url).mock(return_value=httpx.Response(200, json=body, headers=headers))

    async with GenericBackend(provider=provider_cfg) as backend:
        result = await backend.complete(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        )

    outcome = result.invocation_outcome
    assert outcome is not None
    assert outcome.provider_class.value == "routed_gateway"
    assert outcome.gateway_provenance is not None
    assert outcome.gateway_provenance.downstream_provider == "openai"
    assert outcome.gateway_provenance.downstream_model == "gpt-4o"
    assert outcome.gateway_provenance_verified is True


@pytest.mark.asyncio
async def test_openrouter_identity_preserved() -> None:
    """OpenRouter invocation preserves provider identity as 'openrouter'."""
    provider_cfg = ProviderConfig.model_validate(_make_provider("openrouter", "openai"))
    model_cfg = ModelConfig.model_validate(_make_model("openai/gpt-4o"))

    body = {
        "id": "gen-or-3",
        "model": "openai/gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }

    url = f"{provider_cfg.api_base}/chat/completions"
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    async with GenericBackend(provider=provider_cfg) as backend:
        result = await backend.complete(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        )

    outcome = result.invocation_outcome
    assert outcome is not None
    assert outcome.requested_provider_id == "openrouter"
    assert outcome.provider_class.value == "routed_gateway"
    assert outcome.api_style == "openai"


@pytest.mark.asyncio
async def test_deepseek_identity_preserved() -> None:
    """DeepSeek preserves identity despite OpenAI-compatible transport."""
    provider_cfg = ProviderConfig.model_validate(
        _make_provider("deepseek", "openai", api_base="https://api.deepseek.com/v1")
    )
    model_cfg = ModelConfig.model_validate(_make_model("deepseek-chat"))

    body = {
        "id": "resp-ds-2",
        "model": "deepseek-chat",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }

    url = f"{provider_cfg.api_base}/chat/completions"
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    async with GenericBackend(provider=provider_cfg) as backend:
        result = await backend.complete(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        )

    outcome = result.invocation_outcome
    assert outcome is not None
    assert outcome.requested_provider_id == "deepseek"
    assert outcome.provider_class.value == "direct_inference"


@pytest.mark.asyncio
async def test_provider_evidence_capability_registry_covers_all() -> None:
    """All known provider IDs have an evidence capability entry."""
    caps = invocation_evidence_capabilities()
    provider_ids = {c.provider_id for c in caps}
    expected = {
        "openai",
        "anthropic",
        "gemini",
        "openrouter",
        "deepseek",
        "local_inference",
        "mistral",
        "vertex-anthropic",
        "openai-responses",
        "reasoning",
    }
    assert provider_ids == expected, f"Missing: {expected - provider_ids}"


@pytest.mark.asyncio
async def test_no_secrets_in_outcomes() -> None:
    """Token patterns and secrets never appear in invocation outcomes."""
    provider_cfg = ProviderConfig.model_validate(_make_provider("openai"))
    model_cfg = ModelConfig.model_validate(_make_model("gpt-4o"))

    body = {
        "id": "resp-safe-1",
        "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }

    url = f"{provider_cfg.api_base}/chat/completions"
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    async with GenericBackend(provider=provider_cfg) as backend:
        result = await backend.complete(
            model=model_cfg,
            messages=[LLMMessage(role=Role.user, content="hello")],
            temperature=0.0,
            max_tokens=10,
        )

    outcome = result.invocation_outcome
    assert outcome is not None
    outcome_dict = outcome.to_dict()
    outcome_str = str(outcome_dict).lower()

    forbidden = {"sk-", "Bearer ", "api_key"}
    for token in forbidden:
        assert token not in outcome_str, f"Forbidden token '{token}' in outcome"
