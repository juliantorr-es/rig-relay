"""Provider models — types for provider onboarding, status, and configuration.

Content-light by design: no raw API keys, tokens, or secrets are stored in
these models. Key fingerprints are SHA256 hashes of the key bytes, not the
keys themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Provider(StrEnum):
    """Supported cloud model providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    LOCAL_INFERENCE = "local_inference"


class ProviderClass(StrEnum):
    """Classifier for a provider's architectural role.

    Distinguishes inference providers from gateways, local runtimes,
    and external coding harnesses. API compatibility does not imply
    class equivalence — DeepSeek using an OpenAI-compatible protocol is
    still a direct inference provider, not OpenAI.
    """

    DIRECT_INFERENCE = "direct_inference"
    ROUTED_GATEWAY = "routed_gateway"
    LOCAL_SERVER = "local_server"
    CLOUD_OFFLOADED_LOCAL = "cloud_offloaded_local"
    LOCAL_LIBRARY = "local_library"
    EXTERNAL_HARNESS = "external_harness"
    ACP_CLIENT = "acp_client"
    A2A_PEER = "a2a_peer"


_PROVIDER_CLASS_MAP: dict[Provider, ProviderClass] = {
    Provider.OPENAI: ProviderClass.DIRECT_INFERENCE,
    Provider.ANTHROPIC: ProviderClass.DIRECT_INFERENCE,
    Provider.GOOGLE: ProviderClass.DIRECT_INFERENCE,
    Provider.OPENROUTER: ProviderClass.ROUTED_GATEWAY,
    Provider.DEEPSEEK: ProviderClass.DIRECT_INFERENCE,
    Provider.LOCAL_INFERENCE: ProviderClass.LOCAL_SERVER,
}


def provider_class_for(provider: Provider) -> ProviderClass:
    """Return the architectural class for a provider identity."""
    return _PROVIDER_CLASS_MAP[provider]


@dataclass
class ProviderCapability:
    """Read-only capability summary for a configured provider.

    Describes what class of provider this is, whether it requires
    network egress, what API style it uses, and which capability
    flags are verified.

    Content-light: no secrets, no raw credentials.
    """

    provider_id: str
    provider_class: ProviderClass
    api_style: str = "openai"
    network_egress: bool = True
    requires_credential: bool = True
    credential_model: str = "api_key"
    configured: bool = False
    executable: bool = False
    default_model: str | None = None
    adapter_available: bool = False
    verified_tool_use: bool = False
    verified_structured_output: bool = False
    verified_streaming: bool = False
    verified_thinking: bool = False
    verified_caching: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_class": self.provider_class.value,
            "api_style": self.api_style,
            "network_egress": self.network_egress,
            "requires_credential": self.requires_credential,
            "credential_model": self.credential_model,
            "configured": self.configured,
            "executable": self.executable,
            "default_model": self.default_model,
            "adapter_available": self.adapter_available,
            "verified_tool_use": self.verified_tool_use,
            "verified_structured_output": self.verified_structured_output,
            "verified_streaming": self.verified_streaming,
            "verified_thinking": self.verified_thinking,
            "verified_caching": self.verified_caching,
            "notes": self.notes,
        }


class KeySource(StrEnum):
    """Where a provider's API key is sourced from."""

    ENV = "env"
    KEYCHAIN = "keychain"
    DEV_FILE = "dev_file"
    MISSING = "missing"


class ProviderConfig:
    """Provider configuration — content-light metadata about a provider's setup.

    Never contains the raw API key.
    """

    def __init__(
        self,
        provider: Provider,
        configured: bool = False,
        key_source: KeySource = KeySource.MISSING,
        key_fingerprint: str = "",
        base_url: str | None = None,
        default_model: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.configured = configured
        self.key_source = key_source
        self.key_fingerprint = key_fingerprint
        self.base_url = base_url
        self.default_model = default_model
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "display_name": self.provider.value.title(),
            "configured": self.configured,
            "key_source": self.key_source.value,
            "key_fingerprint": self.key_fingerprint,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "warnings": self.warnings,
        }


class ProviderStatus:
    """Status of a provider health check — content-light, no raw keys."""

    def __init__(
        self,
        provider: Provider,
        configured: bool = False,
        key_source: KeySource = KeySource.MISSING,
        key_fingerprint: str = "",
        base_url: str | None = None,
        default_model: str | None = None,
        status: str = "unknown",
        last_checked_at: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.configured = configured
        self.key_source = key_source
        self.key_fingerprint = key_fingerprint
        self.base_url = base_url
        self.default_model = default_model
        self.status = status
        self.last_checked_at = last_checked_at or datetime.now(UTC).isoformat()
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "display_name": self.provider.value.title(),
            "configured": self.configured,
            "key_source": self.key_source.value,
            "key_fingerprint": self.key_fingerprint,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "status": self.status,
            "last_checked_at": self.last_checked_at,
            "warnings": self.warnings,
        }


class ProviderStatusSummary:
    """Aggregate provider status summary — content-light."""

    def __init__(
        self,
        total: int = 0,
        configured: int = 0,
        providers: list[dict[str, Any]] | None = None,
    ) -> None:
        self.total = total
        self.configured = configured
        self.providers = providers or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "configured": self.configured,
            "providers": self.providers,
        }


class ProviderOnboardingResult:
    """Result of a provider onboarding operation — content-light."""

    def __init__(
        self,
        provider: Provider,
        status: str = "completed",
        key_source: KeySource = KeySource.MISSING,
        key_fingerprint: str = "",
        summary: str = "",
        warnings: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.status = status
        self.key_source = key_source
        self.key_fingerprint = key_fingerprint
        self.summary = summary
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "status": self.status,
            "key_source": self.key_source.value,
            "key_fingerprint": self.key_fingerprint,
            "summary": self.summary,
            "warnings": self.warnings,
        }
