"""Provider registry — metadata and env var conventions for supported providers.

Content-light: contains only provider metadata, no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

from rig_relay.providers.models import Provider


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for a single provider in the registry."""

    provider: Provider
    display_name: str
    env_var: str
    alt_env_var: str | None = None
    docs_hint: str = ""
    default_model: str | None = None
    base_url: str | None = None
    supports_base_url: bool = False
    supports_alt_endpoint: bool = False
    alt_endpoint_note: str = ""


PROVIDER_REGISTRY: list[ProviderInfo] = [
    ProviderInfo(
        provider=Provider.OPENAI,
        display_name="OpenAI",
        env_var="OPENAI_API_KEY",
        docs_hint="OpenAI API key",
        default_model="gpt-4o",
        supports_base_url=True,
    ),
    ProviderInfo(
        provider=Provider.ANTHROPIC,
        display_name="Anthropic",
        env_var="ANTHROPIC_API_KEY",
        docs_hint="Anthropic API key",
        default_model="claude-sonnet-4-20250514",
        supports_base_url=True,
    ),
    ProviderInfo(
        provider=Provider.GOOGLE,
        display_name="Google Gemini",
        env_var="GEMINI_API_KEY",
        alt_env_var="GOOGLE_API_KEY",
        docs_hint="Google AI Studio API key",
        default_model="gemini-2.0-flash",
        supports_base_url=True,
    ),
    ProviderInfo(
        provider=Provider.OPENROUTER,
        display_name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        docs_hint="OpenRouter API key",
        default_model="openai/gpt-4o",
        supports_base_url=True,
    ),
    ProviderInfo(
        provider=Provider.DEEPSEEK,
        display_name="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        docs_hint="DeepSeek API key",
        default_model="deepseek-chat",
        supports_base_url=True,
        supports_alt_endpoint=True,
        alt_endpoint_note=(
            "DeepSeek also supports an Anthropic-compatible endpoint. "
            "Use DEEPSEEK_API_KEY for the standard endpoint."
        ),
    ),
]


def get_provider_info(provider: Provider) -> ProviderInfo | None:
    """Look up provider metadata by enum value."""
    for info in PROVIDER_REGISTRY:
        if info.provider == provider:
            return info
    return None


def get_provider_info_by_name(name: str) -> ProviderInfo | None:
    """Look up provider metadata by string name (case-insensitive)."""
    for info in PROVIDER_REGISTRY:
        if info.provider.value == name.lower():
            return info
    return None


def is_supported_provider(name: str) -> bool:
    """Check if a provider name is in the registry."""
    return get_provider_info_by_name(name) is not None
