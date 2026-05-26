"""OpenRouter generation metadata observer.

Read-only. Performs bounded metadata lookup after primary inference
completion for routed gateway providers. Uses the official OpenRouter
generation metadata endpoint (GET /api/v1/generation?id=<id>).

Content-light: never stores prompts, generated text, or credentials.
Gracefully degrades on timeout, 401, 404, or missing generation ID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from rig_relay.providers.invocation import GatewayProvenance, GatewayProvenanceSource

logger = logging.getLogger(__name__)
OPENROUTER_METADATA_URL = "https://openrouter.ai/api/v1/generation"


class OpenRouterGenerationObserver:
    """Observes downstream provider provenance from OpenRouter metadata.

    Usage:
        observer = OpenRouterGenerationObserver(api_key="...")
        provenance, cost = await observer.observe(generation_id="gen-...")
        if provenance is None:
            # Metadata unavailable — response remains successful
            pass
    """

    def __init__(self, api_key: str | None = None, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def observe(
        self, generation_id: str
    ) -> tuple[GatewayProvenance | None, dict[str, Any]]:
        """Observe downstream provenance from generation metadata.

        Returns (provenance, cost_data). provenance is None if metadata
        is unavailable or degraded. The primary inference result must NOT
        be invalidated by metadata observation failure.

        Content-light: never returns raw prompts, generated text, or
        credentials in the cost data dict.
        """
        if not generation_id or not self._api_key:
            return None, {}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    OPENROUTER_METADATA_URL,
                    params={"id": generation_id},
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.debug("OpenRouter metadata timeout/error: %s", e)
            return None, {}

        if response.status_code == 404:
            logger.debug("OpenRouter generation ID not found: %s", generation_id)
            return None, {}
        if response.status_code == 401:
            logger.debug("OpenRouter metadata unauthorized")
            return None, {}
        if response.status_code != 200:
            logger.debug(
                "OpenRouter metadata unexpected status: %d", response.status_code
            )
            return None, {}

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.debug("OpenRouter metadata malformed JSON")
            return None, {}

        if not isinstance(data, dict) or not data.get("data"):
            return None, {}

        gen = data["data"]
        provider_name = gen.get("provider_name", "")
        model = gen.get("model", "")

        provenance = None
        if provider_name:
            provenance = GatewayProvenance(
                downstream_provider=provider_name,
                downstream_model=model if model != provider_name else None,
                provenance_source=GatewayProvenanceSource.RESPONSE_BODY,
            )

        cost_data: dict[str, Any] = {}
        total_cost = gen.get("total_cost")
        if total_cost is not None and total_cost != 0:
            cost_data["gateway_total_cost"] = float(total_cost)
        upstream_cost = gen.get("upstream_inference_cost")
        if upstream_cost is not None:
            cost_data["gateway_upstream_cost"] = float(upstream_cost)
        native_prompt = gen.get("native_tokens_prompt")
        if native_prompt is not None:
            cost_data["gateway_native_tokens_prompt"] = int(native_prompt)
        native_completion = gen.get("native_tokens_completion")
        if native_completion is not None:
            cost_data["gateway_native_tokens_completion"] = int(native_completion)
        native_cached = gen.get("native_tokens_cached")
        if native_cached is not None:
            cost_data["gateway_native_tokens_cached"] = int(native_cached)
        native_reasoning = gen.get("native_tokens_reasoning")
        if native_reasoning is not None:
            cost_data["gateway_native_tokens_reasoning"] = int(native_reasoning)

        return provenance, cost_data


__all__ = ["OpenRouterGenerationObserver"]
