"""Model capability discovery — fetches model metadata from provider APIs.

Supports OpenAI-compatible /v1/models endpoints and provider-specific
endpoints. Returns structured capability data (context window, pricing,
supported features, etc.).

Providers that expose a /v1/models endpoint:
  - OpenAI: https://api.openai.com/v1/models
  - Anthropic: https://api.anthropic.com/v1/models (different schema)
  - Google: https://generativelanguage.googleapis.com/v1beta/models
  - OpenRouter: https://openrouter.ai/api/v1/models (includes pricing)
  - DeepSeek: https://api.deepseek.com/v1/models
  - Mistral: https://api.mistral.ai/v1/models

Each provider returns different metadata shapes, so we normalize into
a common ModelCapabilities schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ModelCapabilities:
    """Normalized model capabilities from a provider API response.

    All fields are optional — the provider may not report all of them.
    """

    id: str
    provider: str
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_vision: bool = False
    supports_tools: bool = True
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    supports_audio: bool = False
    supports_audio_generation: bool = False
    supports_video_generation: bool = False
    supports_image_generation: bool = False
    supports_thinking: bool = False
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    cached_input_price_per_million: float = 0.0
    pricing_source: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


_MODEL_LIST_TIMEOUT = 15.0


async def fetch_openai_models(
    api_key: str, base_url: str = "https://api.openai.com/v1"
) -> list[ModelCapabilities]:
    """Fetch models from an OpenAI-compatible /v1/models endpoint.

    OpenAI returns model IDs but not pricing from the models list endpoint.
    Pricing is hardcoded from known values where possible.
    """
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("data", []):
        model_id = item.get("id", "")
        if not model_id:
            continue
        cap = ModelCapabilities(
            id=model_id,
            provider="openai",
            context_window=_openai_context_window(model_id),
            max_output_tokens=_openai_max_output(model_id),
            supports_vision=_openai_supports_vision(model_id),
            supports_structured_output=_openai_supports_structured(model_id),
            supports_thinking=_openai_supports_thinking(model_id),
            input_price_per_million=_openai_input_price(model_id),
            output_price_per_million=_openai_output_price(model_id),
            supports_tools=True,
            raw=item,
        )
        models.append(cap)
    return models


def _openai_context_window(model_id: str) -> int | None:
    m = model_id.lower()
    if "gpt-4" in m or "o1" in m or "o3" in m:
        return 128_000
    if "gpt-3.5" in m:
        return 16_385
    return None


def _openai_max_output(model_id: str) -> int | None:
    m = model_id.lower()
    if "o1" in m or "o3" in m:
        return 100_000
    if "gpt-4" in m:
        return 16_384
    if "gpt-3.5" in m:
        return 4_096
    return None


def _openai_supports_vision(model_id: str) -> bool:
    m = model_id.lower()
    return "vision" in m or "gpt-4o" in m or "gpt-4.1" in m


def _openai_supports_structured(model_id: str) -> bool:
    m = model_id.lower()
    return "gpt-4" in m or "o1" in m or "o3" in m


def _openai_supports_thinking(model_id: str) -> bool:
    m = model_id.lower()
    return m.startswith("o1") or m.startswith("o3")


def _openai_input_price(model_id: str) -> float:
    """Known pricing per million input tokens (approximate)."""
    m = model_id.lower()
    if "gpt-4o" in m:
        return 2.50
    if "gpt-4.1" in m:
        return 2.00
    if "gpt-4-turbo" in m:
        return 10.00
    if "gpt-4" in m:
        return 30.00
    if "gpt-3.5" in m:
        return 0.50
    if "o1" in m:
        return 15.00
    if "o3" in m:
        return 10.00
    return 0.0


def _openai_output_price(model_id: str) -> float:
    m = model_id.lower()
    if "gpt-4o" in m:
        return 10.00
    if "gpt-4.1" in m:
        return 8.00
    if "gpt-4-turbo" in m:
        return 30.00
    if "gpt-4" in m:
        return 60.00
    if "gpt-3.5" in m:
        return 1.50
    if "o1" in m:
        return 60.00
    if "o3" in m:
        return 40.00
    return 0.0


async def fetch_openrouter_models(
    api_key: str, base_url: str = "https://openrouter.ai/api/v1"
) -> list[ModelCapabilities]:
    """Fetch models from OpenRouter.

    OpenRouter's /api/v1/models endpoint includes pricing in the response.
    """
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("data", []):
        model_id = item.get("id", "")
        if not model_id:
            continue

        pricing = item.get("pricing", {})
        input_price = _parse_price(pricing.get("prompt", 0))
        output_price = _parse_price(pricing.get("completion", 0))

        models.append(ModelCapabilities(
            id=model_id,
            provider="openrouter",
            context_window=_openrouter_context_window(item),
            supports_vision="vision" in model_id.lower() or "vl" in model_id.lower(),
            supports_tools=True,
            input_price_per_million=input_price,
            output_price_per_million=output_price,
            pricing_source="openrouter_api",
            raw=item,
        ))
    return models


def _parse_price(price: Any) -> float:
    try:
        return float(price) * 1_000_000  # OpenRouter returns per-token prices
    except (TypeError, ValueError):
        return 0.0


def _openrouter_context_window(item: dict) -> int | None:
    context_length = item.get("context_length")
    if context_length is not None:
        try:
            return int(context_length)
        except (TypeError, ValueError):
            pass
    # Fallback: check top_provider
    top_provider = item.get("top_provider", {})
    max_context = top_provider.get("max_context")
    if max_context is not None:
        try:
            return int(max_context)
        except (TypeError, ValueError):
            pass
    return None


async def fetch_anthropic_models(
    api_key: str, base_url: str = "https://api.anthropic.com/v1"
) -> list[ModelCapabilities]:
    """Fetch models from Anthropic.

    Anthropic returns model IDs with display names.
    """
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("data", []):
        model_id = item.get("id", "") or item.get("name", "")
        if not model_id:
            continue
        cap = ModelCapabilities(
            id=model_id,
            provider="anthropic",
            context_window=_anthropic_context_window(model_id),
            max_output_tokens=_anthropic_max_output(model_id),
            supports_vision=_anthropic_supports_vision(model_id),
            supports_tools=True,
            supports_thinking="sonnet" in model_id or "opus" in model_id,
            input_price_per_million=_anthropic_input_price(model_id),
            output_price_per_million=_anthropic_output_price(model_id),
            raw=item,
        )
        models.append(cap)
    return models


def _anthropic_context_window(model_id: str) -> int | None:
    m = model_id.lower()
    if "sonnet" in m or "opus" in m or "haiku" in m:
        return 200_000
    return None


def _anthropic_max_output(model_id: str) -> int | None:
    return 8_192


def _anthropic_supports_vision(model_id: str) -> bool:
    return True  # All Claude models support vision


def _anthropic_input_price(model_id: str) -> float:
    m = model_id.lower()
    if "sonnet" in m:
        return 3.00
    if "opus" in m:
        return 15.00
    if "haiku" in m:
        return 0.25
    return 0.0


def _anthropic_output_price(model_id: str) -> float:
    m = model_id.lower()
    if "sonnet" in m:
        return 15.00
    if "opus" in m:
        return 75.00
    if "haiku" in m:
        return 1.25
    return 0.0


async def fetch_google_models(
    api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta"
) -> list[ModelCapabilities]:
    """Fetch models from Google Generative AI.

    Google returns models with supported generation methods.
    """
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(f"{base_url}/models?key={api_key}")
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("models", []):
        model_id = item.get("name", "")
        if not model_id:
            continue
        # Strip "models/" prefix
        if model_id.startswith("models/"):
            model_id = model_id[7:]

        supported_methods = item.get("supportedGenerationMethods", [])
        supports_vision = "generateContent" in supported_methods
        supports_embedding = "embedContent" in supported_methods

        cap = ModelCapabilities(
            id=model_id,
            provider="google",
            context_window=_google_context_window(model_id),
            supports_vision=supports_vision,
            supports_tools="generateContent" in supported_methods,
            supports_embeddings=supports_embedding,
            input_price_per_million=_google_input_price(model_id),
            output_price_per_million=_google_output_price(model_id),
            raw=item,
        )
        models.append(cap)
    return models


def _google_context_window(model_id: str) -> int | None:
    m = model_id.lower()
    if "gemini-2.5" in m:
        return 1_000_000
    if "gemini-2.0" in m or "gemini-1.5" in m:
        return 1_000_000
    return None


def _google_input_price(model_id: str) -> float:
    m = model_id.lower()
    if "gemini-2.0-flash" in m:
        return 0.10
    if "gemini-2.0-flash-lite" in m:
        return 0.075
    if "gemini-1.5-flash" in m:
        return 0.075
    if "gemini-1.5-pro" in m:
        return 1.25
    if "gemini-2.5-pro" in m:
        return 1.25
    return 0.0


def _google_output_price(model_id: str) -> float:
    m = model_id.lower()
    if "gemini-2.0-flash" in m:
        return 0.40
    if "gemini-2.0-flash-lite" in m:
        return 0.30
    if "gemini-1.5-flash" in m:
        return 0.30
    if "gemini-1.5-pro" in m:
        return 5.00
    if "gemini-2.5-pro" in m:
        return 10.00
    return 0.0


async def fetch_deepseek_models(
    api_key: str, base_url: str = "https://api.deepseek.com"
) -> list[ModelCapabilities]:
    """Fetch models from DeepSeek (OpenAI-compatible endpoint)."""
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("data", []):
        model_id = item.get("id", "")
        if not model_id:
            continue
        cap = ModelCapabilities(
            id=model_id,
            provider="deepseek",
            context_window=_deepseek_context_window(model_id),
            supports_tools=True,
            supports_thinking="reasoner" in model_id.lower(),
            input_price_per_million=_deepseek_input_price(model_id),
            output_price_per_million=_deepseek_output_price(model_id),
            raw=item,
        )
        models.append(cap)
    return models


def _deepseek_context_window(model_id: str) -> int | None:
    m = model_id.lower()
    if "v4" in m or "v3" in m:
        return 64_000
    if "r1" in m:
        return 64_000
    return None


def _deepseek_input_price(model_id: str) -> float:
    m = model_id.lower()
    if "v4" in m:
        return 0.20
    if "v3" in m or "chat" in m:
        return 0.27
    if "reasoner" in m or "r1" in m:
        return 0.55
    return 0.0


def _deepseek_output_price(model_id: str) -> float:
    m = model_id.lower()
    if "v4" in m:
        return 1.10
    if "v3" in m or "chat" in m:
        return 1.10
    if "reasoner" in m or "r1" in m:
        return 2.19
    return 0.0


async def fetch_mistral_models(
    api_key: str, base_url: str = "https://api.mistral.ai/v1"
) -> list[ModelCapabilities]:
    """Fetch models from Mistral AI."""
    async with httpx.AsyncClient(timeout=_MODEL_LIST_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    models: list[ModelCapabilities] = []
    for item in data.get("data", []):
        model_id = item.get("id", "")
        if not model_id:
            continue
        cap = ModelCapabilities(
            id=model_id,
            provider="mistral",
            context_window=_mistral_context_window(model_id),
            supports_tools=True,
            supports_vision="pixtral" in model_id.lower(),
            input_price_per_million=_mistral_input_price(model_id),
            output_price_per_million=_mistral_output_price(model_id),
            raw=item,
        )
        models.append(cap)
    return models


def _mistral_context_window(model_id: str) -> int | None:
    m = model_id.lower()
    if "large" in m or "medium" in m or "small" in m:
        return 128_000
    if "pixtral" in m:
        return 128_000
    if "codestral" in m:
        return 256_000
    return None


def _mistral_input_price(model_id: str) -> float:
    m = model_id.lower()
    if "large" in m:
        return 2.00
    if "medium" in m or "pixtral" in m:
        return 1.50
    if "small" in m:
        return 0.60
    if "codestral" in m:
        return 1.00
    return 0.0


def _mistral_output_price(model_id: str) -> float:
    m = model_id.lower()
    if "large" in m:
        return 6.00
    if "medium" in m or "pixtral" in m:
        return 4.50
    if "small" in m:
        return 1.80
    if "codestral" in m:
        return 3.00
    return 0.0


async def discover_models(
    provider_name: str,
    api_key: str,
    base_url: str | None = None,
) -> list[ModelCapabilities]:
    """Fetch models from a provider's API, returning normalized capabilities.

    Args:
        provider_name: One of "openai", "anthropic", "google", "openrouter",
            "deepseek", "mistral".
        api_key: Provider API key.
        base_url: Optional custom base URL. Uses provider default if None.

    Returns:
        List of ModelCapabilities, or empty list on error.
    """
    fetchers = {
        "openai": (fetch_openai_models, "https://api.openai.com/v1"),
        "openrouter": (fetch_openrouter_models, "https://openrouter.ai/api/v1"),
        "anthropic": (fetch_anthropic_models, "https://api.anthropic.com/v1"),
        "google": (
            fetch_google_models,
            "https://generativelanguage.googleapis.com/v1beta",
        ),
        "deepseek": (fetch_deepseek_models, "https://api.deepseek.com"),
        "mistral": (fetch_mistral_models, "https://api.mistral.ai/v1"),
    }

    entry = fetchers.get(provider_name)
    if entry is None:
        return []

    fetcher, default_url = entry
    url = base_url or default_url

    try:
        return await fetcher(api_key, url)
    except Exception:
        return []
