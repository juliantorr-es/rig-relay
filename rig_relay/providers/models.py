"""Provider models — types for provider onboarding, status, and configuration.

Content-light by design: no raw API keys, tokens, or secrets are stored in
these models. Key fingerprints are SHA256 hashes of the key bytes, not the
keys themselves.
"""

from __future__ import annotations

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
