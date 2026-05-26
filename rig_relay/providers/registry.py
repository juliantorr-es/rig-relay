"""Provider registry — metadata and env var conventions for supported providers.

Content-light: contains only provider metadata, no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

from rig_relay.providers.models import (
    Provider,
    ProviderCapability,
    ProviderClass,
    provider_class_for,
)


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
    ProviderInfo(
        provider=Provider.LOCAL_INFERENCE,
        display_name="Local Inference",
        env_var="",
        docs_hint="Local inference requires an explicitly configured endpoint URL.",
        supports_base_url=True,
        supports_alt_endpoint=True,
        alt_endpoint_note=(
            "vLLM, llama.cpp, and other local servers expose an OpenAI-compatible API. "
            "Set base_url to the server URL (e.g. http://localhost:8080). "
            "No API key required for local servers."
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


def get_provider_class(name: str) -> ProviderClass | None:
    """Return the architectural class for a provider by string name."""
    try:
        provider = Provider(name.lower())
    except ValueError:
        return None
    return provider_class_for(provider)


_ADAPTER_VERIFIED_CAPS: dict[Provider, dict[str, bool]] = {
    Provider.OPENAI: {
        "streaming": True,
        "tool_use": True,
        "structured_output": True,
        "thinking": True,
        "caching": False,
    },
    Provider.ANTHROPIC: {
        "streaming": True,
        "tool_use": True,
        "structured_output": True,
        "thinking": True,
        "caching": True,
    },
    Provider.GOOGLE: {
        "streaming": True,
        "tool_use": False,
        "structured_output": False,
        "thinking": False,
        "caching": False,
    },
    Provider.OPENROUTER: {
        "streaming": True,
        "tool_use": True,
        "structured_output": False,
        "thinking": False,
        "caching": False,
    },
    Provider.DEEPSEEK: {
        "streaming": True,
        "tool_use": True,
        "structured_output": False,
        "thinking": True,
        "caching": False,
    },
    Provider.LOCAL_INFERENCE: {
        "streaming": True,
        "tool_use": True,
        "structured_output": False,
        "thinking": False,
        "caching": False,
    },
}


def compute_provider_capabilities(
    adapter_available: bool = True, configured: bool = False
) -> list[ProviderCapability]:
    """Return a read-only capability summary for every registered provider.

    No network calls. No secrets. No inference. No persistence mutation.
    """
    capabilities: list[ProviderCapability] = []
    for info in PROVIDER_REGISTRY:
        pv_class = provider_class_for(info.provider)
        caps = _ADAPTER_VERIFIED_CAPS.get(info.provider, {})
        api_style = _api_style_for(info.provider)
        notes: list[str] = []

        if info.provider == Provider.OPENROUTER:
            notes.append("gateway: downstream provider provenance not yet recorded")
        elif info.provider == Provider.GOOGLE:
            notes.append("tool_use: not yet implemented in Gemini adapter")
            notes.append("structured_output: not yet implemented")
            notes.append("thinking: not yet implemented")
        elif info.provider == Provider.LOCAL_INFERENCE:
            notes.append(
                "local server: no credential required; endpoint URL must be configured"
            )

        capabilities.append(
            ProviderCapability(
                provider_id=info.provider.value,
                provider_class=pv_class,
                api_style=api_style,
                network_egress=pv_class
                not in {ProviderClass.LOCAL_SERVER, ProviderClass.LOCAL_LIBRARY},
                requires_credential=info.provider != Provider.LOCAL_INFERENCE,
                credential_model="api_key",
                configured=configured,
                executable=adapter_available and configured,
                default_model=info.default_model,
                adapter_available=adapter_available,
                verified_tool_use=caps.get("tool_use", False),
                verified_structured_output=caps.get("structured_output", False),
                verified_streaming=caps.get("streaming", False),
                verified_thinking=caps.get("thinking", False),
                verified_caching=caps.get("caching", False),
                notes=notes,
            )
        )
    return capabilities


def get_provider_capability(name: str) -> ProviderCapability | None:
    """Return the capability summary for a single provider by name."""
    try:
        provider = Provider(name.lower())
    except ValueError:
        return None
    for cap in compute_provider_capabilities():
        if cap.provider_id == provider.value:
            return cap
    return None


def _api_style_for(provider: Provider) -> str:
    style_map: dict[Provider, str] = {
        Provider.OPENAI: "openai",
        Provider.ANTHROPIC: "anthropic",
        Provider.GOOGLE: "gemini",
        Provider.OPENROUTER: "openai",
        Provider.DEEPSEEK: "openai",
        Provider.LOCAL_INFERENCE: "openai",
    }
    return style_map.get(provider, "openai")
