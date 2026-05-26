"""Concurrent state-isolation and contamination proofs for provider invocation evidence.

Uses real async resps/httpx boundaries. Proves predecessor P1.4 contamination
and proves the P1.4.1 per-backend adapter architecture prevents it.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from rig_relay.core.config import ModelConfig, ProviderConfig
from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.types import LLMMessage, Role

OR_BASE = "https://openrouter.ai/api/v1"
OAI_BASE = "https://api.openai.com/v1"
DS_BASE = "https://api.deepseek.com/v1"


def _or_provider(name: str = "openrouter") -> ProviderConfig:
    return ProviderConfig(
        name=name, api_base=OR_BASE, api_key_env_var="OR_KEY", api_style="openai"
    )


def _oai_provider() -> ProviderConfig:
    return ProviderConfig(
        name="openai", api_base=OAI_BASE, api_key_env_var="OAI_KEY", api_style="openai"
    )


OR_MODEL = ModelConfig(
    name="openai/gpt-4o", provider="openrouter", alias="g4or", thinking="off"
)
OAI_MODEL = ModelConfig(name="gpt-4o", provider="openai", alias="g4", thinking="off")
DS_MODEL = ModelConfig(
    name="deepseek-chat", provider="deepseek", alias="ds", thinking="off"
)


# ═══════════════════════════════════════════════════════════════════════
# Non-streaming concurrent isolation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_non_streaming_isolation(respx_mock: respx.MockRouter):
    """Two backends with distinct providers do not cross-contaminate outcomes."""
    respx_mock.post(f"{OR_BASE}/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-or",
            "model": "openai/gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "OR"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost": 0.001,
                "prompt_tokens_details": {"cached_tokens": 10},
                "completion_tokens_details": {"reasoning_tokens": 5},
            },
        },
        headers={"x-provider": "Anthropic"},
    )
    respx_mock.post(f"{OAI_BASE}/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-oai",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "OAI"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        },
    )

    async with (
        GenericBackend(provider=_or_provider()) as or_be,
        GenericBackend(provider=_oai_provider()) as oai_be,
    ):
        or_chunk, oai_chunk = await asyncio.gather(
            or_be.complete(
                model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
            ),
            oai_be.complete(
                model=OAI_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
            ),
        )

    or_d = or_chunk.invocation_outcome.to_dict()
    oai_d = oai_chunk.invocation_outcome.to_dict()

    assert or_d["requested_provider_id"] == "openrouter"
    assert or_d["provider_class"] == "routed_gateway"
    assert or_d["provider_response_id"] == "gen-or"
    assert or_d["provider_generation_id"] == "gen-or"
    assert or_d["cache_read_tokens"] == 10
    assert or_d["reasoning_tokens"] == 5
    assert or_d["gateway_provenance"] is not None

    assert oai_d["requested_provider_id"] == "openai"
    assert oai_d["provider_class"] == "direct_inference"
    assert oai_d["provider_response_id"] == "gen-oai"
    assert oai_d["gateway_provenance"] is None


# ═══════════════════════════════════════════════════════════════════════
# Streaming concurrent isolation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_streaming_isolation(respx_mock: respx.MockRouter):
    """Concurrent streaming backends with distinct headers produce distinct evidence."""
    sse_or = (
        'data: {"choices":[{"delta":{"content":"OR"},"index":0}],"usage":{"prompt_tokens":11,"completion_tokens":22},"id":"gen-or-s"}\n\n'
        "data: [DONE]\n\n"
    )
    sse_oai = (
        'data: {"choices":[{"delta":{"content":"OAI"},"index":0}],"usage":{"prompt_tokens":33,"completion_tokens":44},"id":"gen-oai-s"}\n\n'
        "data: [DONE]\n\n"
    )
    respx_mock.post(f"{OR_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=sse_or,
            headers={"content-type": "text/event-stream", "x-provider": "Google"},
        )
    )
    respx_mock.post(f"{OAI_BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=sse_oai, headers={"content-type": "text/event-stream"}
        )
    )

    async with (
        GenericBackend(provider=_or_provider()) as or_be,
        GenericBackend(provider=_oai_provider()) as oai_be,
    ):

        async def _drain_or():
            r = []
            async for c in or_be.complete_streaming(
                model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="H")]
            ):
                r.append(c)
            return r

        async def _drain_oai():
            r = []
            async for c in oai_be.complete_streaming(
                model=OAI_MODEL, messages=[LLMMessage(role=Role.user, content="H")]
            ):
                r.append(c)
            return r

        or_chunks, oai_chunks = await asyncio.gather(_drain_or(), _drain_oai())

    or_d = or_chunks[-1].invocation_outcome.to_dict()
    oai_d = oai_chunks[-1].invocation_outcome.to_dict()

    assert or_d["requested_provider_id"] == "openrouter"
    assert or_d["gateway_provenance"] is not None
    assert or_d["gateway_provenance"]["downstream_provider"] == "google"
    assert oai_d["requested_provider_id"] == "openai"
    assert oai_d["gateway_provenance"] is None


# ═══════════════════════════════════════════════════════════════════════
# Same-backend concurrent isolation (the real P1.4.2 gate)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_same_backend_concurrent_non_streaming(respx_mock: respx.MockRouter):
    """Two concurrent calls through SAME GenericBackend use distinct adapter state."""
    respx_mock.post(f"{OR_BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "id": "gen-or-1",
                    "model": "openai/gpt-4o",
                    "choices": [{"message": {"role": "assistant", "content": "A"}}],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "cost": 0.001,
                        "prompt_tokens_details": {"cached_tokens": 10},
                    },
                },
                headers={"x-provider": "Anthropic"},
            ),
            httpx.Response(
                200,
                json={
                    "id": "gen-or-2",
                    "model": "anthropic/claude-sonnet",
                    "choices": [{"message": {"role": "assistant", "content": "B"}}],
                    "usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 100,
                        "cost": 0.002,
                        "completion_tokens_details": {"reasoning_tokens": 50},
                    },
                },
                headers={"x-provider": "OpenAI"},
            ),
        ]
    )

    async with GenericBackend(provider=_or_provider()) as be:
        a, b = await asyncio.gather(
            be.complete(
                model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="A")]
            ),
            be.complete(
                model=ModelConfig(
                    name="anthropic/claude-sonnet",
                    provider="openrouter",
                    alias="cs",
                    thinking="off",
                ),
                messages=[LLMMessage(role=Role.user, content="B")],
            ),
        )

    a_d = a.invocation_outcome.to_dict()
    b_d = b.invocation_outcome.to_dict()

    assert a_d["provider_response_id"] == "gen-or-1"
    assert a_d["cache_read_tokens"] == 10
    assert a_d["gateway_provenance"]["downstream_provider"] == "anthropic"

    assert b_d["provider_response_id"] == "gen-or-2"
    assert b_d["reasoning_tokens"] == 50
    assert b_d["gateway_provenance"]["downstream_provider"] == "openai"


@pytest.mark.asyncio
async def test_same_backend_concurrent_streaming(respx_mock: respx.MockRouter):
    """Two interleaved streams through SAME backend retain distinct evidence."""
    sse_a = (
        'data: {"choices":[{"delta":{"content":"A"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{},"index":0}],"usage":{"prompt_tokens":11,"completion_tokens":22},"id":"gen-s1"}\n\n'
        "data: [DONE]\n\n"
    )
    sse_b = (
        'data: {"choices":[{"delta":{"content":"B"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{},"index":0}],"usage":{"prompt_tokens":33,"completion_tokens":44},"id":"gen-s2"}\n\n'
        "data: [DONE]\n\n"
    )
    respx_mock.post(f"{OR_BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                content=sse_a,
                headers={"content-type": "text/event-stream", "x-provider": "Google"},
            ),
            httpx.Response(
                200,
                content=sse_b,
                headers={
                    "content-type": "text/event-stream",
                    "x-provider": "Anthropic",
                },
            ),
        ]
    )

    async with GenericBackend(provider=_or_provider()) as be:

        async def _drain(model_name, alias):
            chunks = []
            async for c in be.complete_streaming(
                model=ModelConfig(
                    name=model_name, provider="openrouter", alias=alias, thinking="off"
                ),
                messages=[LLMMessage(role=Role.user, content="H")],
            ):
                chunks.append(c)
            return chunks

        a_chunks, b_chunks = await asyncio.gather(
            _drain("openai/gpt-4o", "g4o"), _drain("anthropic/claude", "cl")
        )

    a_d = a_chunks[-1].invocation_outcome.to_dict()
    b_d = b_chunks[-1].invocation_outcome.to_dict()

    assert a_d["provider_response_id"] == "gen-s1"
    assert a_d["gateway_provenance"]["downstream_provider"] == "google"
    assert b_d["provider_response_id"] == "gen-s2"
    assert b_d["gateway_provenance"]["downstream_provider"] == "anthropic"
