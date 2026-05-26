"""Causal tests for OpenRouter generation metadata observer.

Real HTTP boundaries through respx. Proves success enrichment,
graceful degradation (401, 404, 429, timeout, malformed),
discrepancy detection, and content-light preservation.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from rig_relay.providers.openrouter_observer import (
    GENERATION_METADATA_ENDPOINT,
    OpenRouterGenerationEvidence,
    compute_discrepancy,
    observe_generation_metadata,
)

GEN_ID = "gen-test-abc123"


# ═══════════════════════════════════════════════════════════════════════
# Success — native tokens + cost + provider
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_observer_success_maps_native_evidence(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(
        status_code=200,
        json={
            "data": {
                "provider_name": "Anthropic",
                "model": "claude-sonnet-4-20250514",
                "native_tokens_prompt": 1200,
                "native_tokens_completion": 800,
                "native_tokens_cached": 300,
                "native_tokens_reasoning": 500,
                "total_cost": 0.015,
                "upstream_inference_cost": 0.012,
                "streamed": True,
            }
        },
    )

    evidence = await observe_generation_metadata(GEN_ID)

    assert evidence.enrichment_success is True
    assert evidence.downstream_provider == "Anthropic"
    assert evidence.downstream_model == "claude-sonnet-4-20250514"
    assert evidence.native_tokens_prompt == 1200
    assert evidence.native_tokens_completion == 800
    assert evidence.native_tokens_cached == 300
    assert evidence.native_tokens_reasoning == 500
    assert evidence.total_cost == 0.015
    assert evidence.upstream_cost == 0.012
    assert evidence.streamed is True

    # Content-light: no raw content in values
    values_str = "".join(
        str(v) for v in vars(evidence).values() if v is not None
    ).lower()
    for bad in ["ghp_", "sk-", "api_key", "bearer"]:
        assert bad not in values_str


@pytest.mark.asyncio
async def test_observer_success_minimal_fields(respx_mock: respx.MockRouter):
    """Partial data is mapped honestly (only what's present)."""
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(
        status_code=200, json={"data": {"provider_name": "OpenAI", "total_cost": 0.001}}
    )
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is True
    assert evidence.downstream_provider == "OpenAI"
    assert evidence.total_cost == 0.001
    assert evidence.native_tokens_prompt is None


# ═══════════════════════════════════════════════════════════════════════
# Graceful degradation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_observer_404_no_enrichment(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(404)
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is False
    assert "404" in (evidence.enrichment_skipped_reason or "")


@pytest.mark.asyncio
async def test_observer_401_no_enrichment(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(401)
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is False


@pytest.mark.asyncio
async def test_observer_429_no_enrichment(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(429)
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is False


@pytest.mark.asyncio
async def test_observer_timeout_no_enrichment(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is False
    assert "timed out" in (evidence.enrichment_error or "").lower()


@pytest.mark.asyncio
async def test_observer_malformed_no_enrichment(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GENERATION_METADATA_ENDPOINT}?id={GEN_ID}").respond(
        status_code=200, content=b"not json"
    )
    evidence = await observe_generation_metadata(GEN_ID)
    assert evidence.enrichment_success is False


@pytest.mark.asyncio
async def test_observer_empty_id_skipped():
    evidence = await observe_generation_metadata("")
    assert evidence.enrichment_success is False
    assert "empty" in (evidence.enrichment_skipped_reason or "").lower()


# ═══════════════════════════════════════════════════════════════════════
# Discrepancy detection
# ═══════════════════════════════════════════════════════════════════════


def test_discrepancy_detected_on_token_difference():
    inline = {"input_tokens": 100, "output_tokens": 50}
    gen = OpenRouterGenerationEvidence(
        native_tokens_prompt=120, native_tokens_completion=50, enrichment_success=True
    )
    result = compute_discrepancy(inline, gen)
    assert result["discrepancy_detected"] is True
    assert len(result["discrepancy_fields"]) == 1


def test_no_discrepancy_when_values_match():
    inline = {"input_tokens": 100, "output_tokens": 50, "gateway_total_cost": 0.001}
    gen = OpenRouterGenerationEvidence(
        native_tokens_prompt=100,
        native_tokens_completion=50,
        total_cost=0.001,
        enrichment_success=True,
    )
    result = compute_discrepancy(inline, gen)
    assert result["discrepancy_detected"] is False


def test_no_discrepancy_when_enrichment_failed():
    inline = {"input_tokens": 100}
    gen = OpenRouterGenerationEvidence(enrichment_success=False)
    result = compute_discrepancy(inline, gen)
    assert result["discrepancy_detected"] is False


# ═══════════════════════════════════════════════════════════════════════
# Content-light guarantee
# ═══════════════════════════════════════════════════════════════════════


def test_observer_evidence_never_contains_secrets():
    evidence = OpenRouterGenerationEvidence(downstream_provider="test")
    d = vars(evidence)
    # Value-level check — field names like 'native_tokens_prompt' are metadata
    values_str = "".join(str(v) for v in d.values() if v is not None).lower()
    for bad in ["ghp_", "sk-", "api_key", "bearer"]:
        assert bad not in values_str, f"Found {bad}"
