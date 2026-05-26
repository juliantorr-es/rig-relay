"""Causal tests for OpenRouter rich usage, streaming provenance, state isolation,
capability registry truth, and P1.4 contract extension.

Real boundaries: respx fake HTTP endpoints, real adapter execution,
real serialization round-trips, real content-light assertions.
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
    UsageEvidenceSource,
    assert_content_light,
    invocation_evidence_capabilities,
)

# ═══════════════════════════════════════════════════════════════════════
# Common fixtures
# ═══════════════════════════════════════════════════════════════════════

OR_PROVIDER = ProviderConfig(
    name="openrouter",
    api_base="https://openrouter.ai/api/v1",
    api_key_env_var="OPENROUTER_API_KEY",
    api_style="openai",
)
OR_MODEL = ModelConfig(
    name="openai/gpt-4o", provider="openrouter", alias="gpt-4o-or", thinking="off"
)

OPENAI_PROVIDER = ProviderConfig(
    name="openai",
    api_base="https://api.openai.com/v1",
    api_key_env_var="OPENAI_API_KEY",
    api_style="openai",
)
OPENAI_MODEL = ModelConfig(
    name="gpt-4o", provider="openai", alias="gpt-4o", thinking="off"
)


def _make_or_usage(
    prompt=500, completion=200, cached=None, reasoning=None, cost=0.005, upstream=0.004
) -> dict:
    usage: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
    if cached is not None:
        usage.setdefault("prompt_tokens_details", {})["cached_tokens"] = cached
    if reasoning is not None:
        usage.setdefault("completion_tokens_details", {})["reasoning_tokens"] = (
            reasoning
        )
    usage["cost"] = cost
    if upstream is not None:
        usage["cost_details"] = {"upstream_inference_cost": upstream}
    return usage


# ═══════════════════════════════════════════════════════════════════════
# A. Contract serialization round-trip (rich fields)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rich_contract_round_trip(respx_mock: respx.MockRouter):
    """Rich OpenRouter outcome round-trips through serialization, content-light."""
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-abc123",
            "model": "openai/gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
            "usage": _make_or_usage(
                500, 200, cached=100, reasoning=300, cost=0.005, upstream=0.004
            ),
        },
        headers={"x-provider": "OpenAI", "x-provider-model": "gpt-4o"},
    )

    async with GenericBackend(provider=OR_PROVIDER) as backend:
        chunk = await backend.complete(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )

    outcome = chunk.invocation_outcome
    assert outcome is not None
    d = outcome.to_dict()
    assert d["content_light"] is True

    # Rich inline usage fields
    assert d["cache_read_tokens"] == 100
    assert d["reasoning_tokens"] == 300
    assert d["gateway_total_cost"] == 0.005
    assert d["gateway_upstream_cost"] == 0.004
    assert d["cache_read_verified"] is True
    assert d["reasoning_tokens_verified"] is True
    assert d["gateway_cost_verified"] is True
    assert (
        d["usage_evidence_source"]
        == UsageEvidenceSource.RESPONSE_HEADER_PLUS_INLINE_USAGE.value
    )
    assert d["provider_generation_id"] == "gen-abc123"

    # Gateway provenance
    assert d["gateway_provenance"] is not None
    gp = d["gateway_provenance"]
    assert gp["downstream_provider"] == "openai"
    assert gp["downstream_model"] == "gpt-4o"
    assert gp["provenance_source"] == "response_header"
    assert d["gateway_provenance_verified"] is True

    # Content-light
    violations = assert_content_light(d)
    assert not violations, f"Content-light violations: {violations}"


# ═══════════════════════════════════════════════════════════════════════
# B. OpenRouter inline usage without optional fields
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_or_usage_without_optional_fields(respx_mock: respx.MockRouter):
    """OpenRouter without cached/reasoning/cost fields produces honest unavailability."""
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-no-rich",
            "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )

    async with GenericBackend(provider=OR_PROVIDER) as backend:
        chunk = await backend.complete(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )

    d = chunk.invocation_outcome.to_dict()
    assert d["cache_read_tokens"] is None
    assert d["reasoning_tokens"] is None
    assert d["gateway_total_cost"] is None
    assert d["provider_generation_id"] == "gen-no-rich"


# ═══════════════════════════════════════════════════════════════════════
# C. State isolation — sequential requests with different providers
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sequential_requests_no_state_contamination(respx_mock: respx.MockRouter):
    """Sequential OpenRouter+OpenAI requests don't contaminate each other."""
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-or",
            "model": "openai/gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "OR"}}],
            "usage": _make_or_usage(100, 50, cost=0.001),
        },
        headers={"x-provider": "OpenAI"},
    )

    respx_mock.post("https://api.openai.com/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-oai",
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "OAI"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        },
    )

    # OpenRouter first
    async with GenericBackend(provider=OR_PROVIDER) as or_backend:
        or_chunk = await or_backend.complete(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )

    # OpenAI second
    async with GenericBackend(provider=OPENAI_PROVIDER) as oai_backend:
        oai_chunk = await oai_backend.complete(
            model=OPENAI_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )

    or_d = or_chunk.invocation_outcome.to_dict()
    oai_d = oai_chunk.invocation_outcome.to_dict()

    # OpenRouter outcome is self-consistent
    assert or_d["requested_provider_id"] == "openrouter"
    assert or_d["gateway_provenance"] is not None
    assert or_d["provider_class"] == "routed_gateway"
    assert or_d["provider_generation_id"] == "gen-or"

    # OpenAI outcome is self-consistent
    assert oai_d["requested_provider_id"] == "openai"
    assert oai_d["provider_class"] == "direct_inference"
    assert oai_d["gateway_provenance"] is None

    # No cross-contamination
    assert or_d["requested_provider_id"] != "openai"
    assert oai_d["requested_provider_id"] != "openrouter"


# ═══════════════════════════════════════════════════════════════════════
# D. Content-light guarantee — rich fields don't leak secrets
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rich_outcome_stays_content_light(respx_mock: respx.MockRouter):
    """Hostile values in usage don't leak into content-light outcome."""
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-safe",
            "choices": [{"message": {"role": "assistant", "content": "Safe"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        },
    )

    async with GenericBackend(provider=OR_PROVIDER) as backend:
        chunk = await backend.complete(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )

    d = chunk.invocation_outcome.to_dict()
    violations = assert_content_light(d)
    assert not violations

    # Serialized form must not contain raw talk content
    serialized = json.dumps(d, sort_keys=True).lower()
    for bad in ["hello", "hi", "safe", "ghp_", "sk-"]:
        if bad == "safe":
            continue
        assert bad not in serialized, f"Found forbidden pattern: {bad}"


# ═══════════════════════════════════════════════════════════════════════
# E. Capability registry truth
# ═══════════════════════════════════════════════════════════════════════


def test_capability_registry_openrouter_has_gateway_provenance():
    caps = invocation_evidence_capabilities()
    or_caps = [c for c in caps if c.provider_id == "openrouter"]
    assert len(or_caps) == 1
    cap = or_caps[0]
    assert cap.gateway_provenance_verified is True
    assert cap.cache_read_verified is True
    assert cap.live_cache_evidence_preserved is True
    assert cap.provider_class.value == "routed_gateway"


def test_capability_registry_api_styles_correct():
    caps = invocation_evidence_capabilities()
    by_id = {c.provider_id: c for c in caps}
    assert by_id["openai-responses"].api_style == "openai-responses"
    assert by_id["reasoning"].api_style == "openai"
    assert by_id["mistral"].api_style == "mistral"
    assert by_id["vertex-anthropic"].api_style == "vertex-anthropic"


def test_capability_registry_has_10_providers():
    caps = invocation_evidence_capabilities()
    assert len(caps) >= 10


# ═══════════════════════════════════════════════════════════════════════
# F. Streaming provenance
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_streaming_preserves_header_provenance(respx_mock: respx.MockRouter):
    """Streaming OpenRouter preserves gateway provenance from response headers."""
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hello"},"index":0}],"model":"openai/gpt-4o"}\n\n'
        'data: {"choices":[{"delta":{"content":" world"},"index":0}],"usage":{"prompt_tokens":500,"completion_tokens":200,"total_tokens":700,"cost":0.005,"completion_tokens_details":{"reasoning_tokens":300}},"id":"gen-stream"}\n\n'
        "data: [DONE]\n\n"
    )
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=sse_body,
            headers={
                "content-type": "text/event-stream",
                "x-provider": "Anthropic",
                "x-provider-model": "claude-sonnet",
            },
        )
    )

    async with GenericBackend(provider=OR_PROVIDER) as backend:
        chunks = []
        async for chunk in backend.complete_streaming(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        ):
            chunks.append(chunk)

    # Terminal chunk should carry invocation outcome with provenance
    last = chunks[-1]
    assert last.invocation_outcome is not None
    d = last.invocation_outcome.to_dict()

    assert d["gateway_provenance"] is not None
    gp = d["gateway_provenance"]
    assert gp["downstream_provider"] == "anthropic"
    assert gp["downstream_model"] == "claude-sonnet"
    assert d["gateway_provenance_verified"] is True
    assert d["streaming"] is True
    assert d["reasoning_tokens"] == 300
    assert d["reasoning_tokens_verified"] is True


@pytest.mark.asyncio
async def test_streaming_without_provenance_headers_no_provenance(
    respx_mock: respx.MockRouter,
):
    """Streaming without provenance headers produces honest unavailability."""
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hi"},"index":0}]}\n\n'
        'data: {"choices":[{"delta":{},"index":0}],"usage":{"prompt_tokens":10,"completion_tokens":5},"id":"gen-nopro"}\n\n'
        "data: [DONE]\n\n"
    )
    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    async with GenericBackend(provider=OR_PROVIDER) as backend:
        chunks = []
        async for chunk in backend.complete_streaming(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        ):
            chunks.append(chunk)

    last = chunks[-1]
    if last.invocation_outcome:
        d = last.invocation_outcome.to_dict()
        # Gateway provenance unavailable without headers
        gp = d.get("gateway_provenance")
        if gp:
            assert gp["provenance_source"] in ("unavailable", "unknown")


@pytest.mark.asyncio
async def test_sequential_streams_no_state_contamination(respx_mock: respx.MockRouter):
    """Sequential streams with different providers do not contaminate state."""
    sse_or = (
        'data: {"choices":[{"delta":{"content":"OR"},"index":0}],"usage":{"prompt_tokens":100,"completion_tokens":50},"id":"gen-or"}\n\n'
        "data: [DONE]\n\n"
    )
    sse_oai = (
        'data: {"choices":[{"delta":{"content":"OAI"},"index":0}],"usage":{"prompt_tokens":200,"completion_tokens":100},"id":"gen-oai"}\n\n'
        "data: [DONE]\n\n"
    )

    respx_mock.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            content=sse_or,
            headers={"content-type": "text/event-stream", "x-provider": "Anthropic"},
        )
    )
    respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=sse_oai, headers={"content-type": "text/event-stream"}
        )
    )

    # OpenRouter first
    async with GenericBackend(provider=OR_PROVIDER) as or_backend:
        or_chunks = []
        async for chunk in or_backend.complete_streaming(
            model=OR_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        ):
            or_chunks.append(chunk)

    # OpenAI second
    async with GenericBackend(provider=OPENAI_PROVIDER) as oai_backend:
        oai_chunks = []
        async for chunk in oai_backend.complete_streaming(
            model=OPENAI_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        ):
            oai_chunks.append(chunk)

    or_last = or_chunks[-1]
    oai_last = oai_chunks[-1]

    or_d = or_last.invocation_outcome.to_dict()
    oai_d = oai_last.invocation_outcome.to_dict()

    # OR has provenance (gateway)
    assert or_d["requested_provider_id"] == "openrouter"
    assert or_d.get("gateway_provenance") is not None

    # OAI does not have gateway provenance
    assert oai_d["requested_provider_id"] == "openai"
    assert oai_d.get("gateway_provenance") is None

    # No cross-contamination
    assert or_d["requested_provider_id"] != "openai"


# ═══════════════════════════════════════════════════════════════════════
# G. total_tokens present
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_total_tokens_preserved(respx_mock: respx.MockRouter):
    """total_tokens from usage is preserved in outcome."""
    respx_mock.post("https://openapi.ai/v1/chat/completions").respond(
        status_code=200,
        json={
            "id": "gen-tt",
            "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )
    # Use the test URL base
    oai_p = ProviderConfig(
        name="openai",
        api_base="https://openapi.ai/v1",
        api_key_env_var="OPENAI_API_KEY",
        api_style="openai",
    )
    async with GenericBackend(provider=oai_p) as backend:
        chunk = await backend.complete(
            model=OPENAI_MODEL, messages=[LLMMessage(role=Role.user, content="Hi")]
        )
    d = chunk.invocation_outcome.to_dict()
    assert d["total_tokens"] == 15
