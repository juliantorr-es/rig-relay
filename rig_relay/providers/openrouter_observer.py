"""OpenRouter Generation Metadata Observer — content-light, read-only audit enrichment.

Performs a documented read-only GET lookup by generation ID against
the OpenRouter generation metadata endpoint. Maps safe fields into
canonical content-light evidence. Never stores prompts, completions,
raw bodies, or credentials. Degrades safely on failure.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx

from rig_relay.providers.invocation import UsageEvidenceSource

GENERATION_METADATA_ENDPOINT = "https://openrouter.ai/api/v1/generation"


@dataclass
class OpenRouterGenerationEvidence:
    """Content-light generation audit evidence from read-only metadata lookup."""

    evidence_source: str = UsageEvidenceSource.GENERATION_METADATA_LOOKUP.value
    provider_generation_id: str | None = None
    downstream_provider: str | None = None
    downstream_model: str | None = None
    native_tokens_prompt: int | None = None
    native_tokens_completion: int | None = None
    native_tokens_cached: int | None = None
    native_tokens_reasoning: int | None = None
    total_cost: float | None = None
    upstream_cost: float | None = None
    streamed: bool | None = None

    # Audit enrichment status
    enrichment_success: bool = False
    enrichment_error: str | None = None
    enrichment_skipped_reason: str | None = None

    # Discrepancy markers
    audit_total_cost: float | None = None

    def has_any_evidence(self) -> bool:
        return any(
            v is not None
            for v in [
                self.native_tokens_prompt,
                self.native_tokens_completion,
                self.native_tokens_cached,
                self.native_tokens_reasoning,
                self.total_cost,
                self.upstream_cost,
                self.downstream_provider,
            ]
        )

    def set_skipped(self, reason: str) -> None:
        self.enrichment_success = False
        self.enrichment_skipped_reason = reason

    def set_error(self, error: str) -> None:
        self.enrichment_success = False
        self.enrichment_error = error


async def observe_generation_metadata(
    generation_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> OpenRouterGenerationEvidence:
    """Observe OpenRouter generation metadata for a completed generation.

    Content-light: never stores prompts, completions, or raw bodies.
    Degrades safely: failure never converts primary success into failure.
    """
    evidence = OpenRouterGenerationEvidence(provider_generation_id=generation_id)

    if not generation_id or not generation_id.startswith("gen-"):
        evidence.set_skipped("Invalid or empty generation ID")
        return evidence

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        close_client = True

    try:
        url = f"{GENERATION_METADATA_ENDPOINT}?id={generation_id}"
        response = await client.get(url, headers=headers)
        if response.status_code == 404:
            evidence.set_skipped("Generation not found (404)")
            return evidence
        if response.status_code == 401:
            evidence.set_skipped("Auth failure (401)")
            return evidence
        if response.status_code == 403:
            evidence.set_skipped("Access denied (403)")
            return evidence
        if response.status_code == 429:
            evidence.set_skipped("Rate limited (429)")
            return evidence
        if not response.is_success:
            evidence.set_error(f"HTTP {response.status_code}")
            return evidence

        data = response.json()
        return _parse_generation_data(data, evidence)

    except httpx.TimeoutException:
        evidence.set_error("Generation metadata lookup timed out")
    except (json.JSONDecodeError, KeyError, TypeError):
        evidence.set_error("Malformed generation metadata response")
    except httpx.RequestError as e:
        evidence.set_error(f"Network error: {type(e).__name__}")
    finally:
        if close_client:
            await client.aclose()

    return evidence


def _parse_generation_data(
    data: dict[str, Any], evidence: OpenRouterGenerationEvidence
) -> OpenRouterGenerationEvidence:
    """Map safe generation metadata fields into content-light evidence."""
    gen_data = data.get("data", data)

    if (provider := gen_data.get("provider_name")) is not None:
        evidence.downstream_provider = str(provider)
    if (model := gen_data.get("model")) is not None:
        evidence.downstream_model = str(model)
    if "native_tokens_prompt" in gen_data:
        evidence.native_tokens_prompt = int(gen_data["native_tokens_prompt"])
    if "native_tokens_completion" in gen_data:
        evidence.native_tokens_completion = int(gen_data["native_tokens_completion"])
    if "native_tokens_cached" in gen_data:
        evidence.native_tokens_cached = int(gen_data["native_tokens_cached"])
    if "native_tokens_reasoning" in gen_data:
        evidence.native_tokens_reasoning = int(gen_data["native_tokens_reasoning"])
    if "total_cost" in gen_data:
        cost = gen_data["total_cost"]
        if isinstance(cost, (int, float)):
            evidence.total_cost = float(cost)
    if "upstream_inference_cost" in gen_data:
        up = gen_data["upstream_inference_cost"]
        if isinstance(up, (int, float)):
            evidence.upstream_cost = float(up)
    if "streamed" in gen_data:
        evidence.streamed = bool(gen_data["streamed"])

    if evidence.has_any_evidence():
        evidence.enrichment_success = True
    else:
        evidence.set_skipped("Generation data contained no usable evidence fields")

    return evidence


def compute_discrepancy(
    inline: dict[str, Any], gen: OpenRouterGenerationEvidence
) -> dict[str, Any]:
    """Compare inline and generation metadata evidence. Surface discrepancies."""
    result: dict[str, Any] = {
        "discrepancy_detected": False,
        "discrepancy_fields": [],
        "inline_retained": True,
        "audit_enriched": gen.enrichment_success,
    }

    if not gen.enrichment_success:
        return result

    comparisons = [
        (
            "input_tokens",
            "native_tokens_prompt",
            inline.get("input_tokens"),
            gen.native_tokens_prompt,
        ),
        (
            "output_tokens",
            "native_tokens_completion",
            inline.get("output_tokens"),
            gen.native_tokens_completion,
        ),
        (
            "cached_tokens",
            "native_tokens_cached",
            inline.get("cache_read_tokens"),
            gen.native_tokens_cached,
        ),
        (
            "reasoning_tokens",
            "native_tokens_reasoning",
            inline.get("reasoning_tokens"),
            gen.native_tokens_reasoning,
        ),
        ("total_cost", "total_cost", inline.get("gateway_total_cost"), gen.total_cost),
    ]

    for inline_name, audit_name, inline_val, audit_val in comparisons:
        if inline_val is not None and audit_val is not None and inline_val != audit_val:
            result["discrepancy_detected"] = True
            result["discrepancy_fields"].append(f"{inline_name}/{audit_name}")

    return result


__all__ = [
    "GENERATION_METADATA_ENDPOINT",
    "OpenRouterGenerationEvidence",
    "compute_discrepancy",
    "observe_generation_metadata",
]
