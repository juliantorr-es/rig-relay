"""Identity provider abstraction — protocol for provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rig_relay.identity.models import (
    IdentityAccountSummary,
    IdentityProviderKind,
    TokenBundleMetadata,
)


class IdentityProvider(ABC):
    """Abstract base for an OAuth identity provider."""

    @abstractmethod
    def kind(self) -> IdentityProviderKind: ...

    @abstractmethod
    def default_scopes(self) -> list[str]: ...

    @abstractmethod
    def build_auth_url(
        self, redirect_uri: str, state: str, scopes: list[str] | None = None
    ) -> str:
        """Build the authorization URL for the provider.

        Args:
            redirect_uri: Local loopback callback URI.
            state: OAuth state value (generated externally).
            scopes: Scopes to request. If None, use default_scopes().

        Returns:
            Full authorization URL string.
        """
        ...

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange an authorization code for tokens.

        Returns:
            Dict with token bundle (access_token, refresh_token, id_token, etc.).

        Raises:
            RuntimeError: If credentials are not configured.
        """
        ...

    @abstractmethod
    def build_account_summary(
        self, metadata: TokenBundleMetadata
    ) -> IdentityAccountSummary: ...

    @abstractmethod
    def refresh_token(self, metadata: TokenBundleMetadata) -> dict[str, Any]: ...

    def is_configured(self) -> bool:
        """Whether this provider has credentials configured."""
        return False
