"""Identity models — typed data structures for identity provider scaffold.

Content-light models: no raw tokens, no client secrets, no authorization codes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict


class IdentityProviderKind(StrEnum):
    GITHUB = auto()
    GOOGLE = auto()


class IdentitySessionStatus(StrEnum):
    SIGNED_OUT = auto()
    PENDING = auto()
    SIGNED_IN = auto()
    ERROR = auto()


class TokenBundleMetadata(BaseModel):
    """Content-light metadata about a stored token bundle.

    No raw access_token, refresh_token, id_token, or authorization code.
    """

    model_config = ConfigDict(extra="forbid")

    provider: IdentityProviderKind
    account_id_hash: str = ""
    email_hash: str = ""
    display_name: str = ""
    scopes: list[str] = []
    expires_at: datetime | None = None
    status: IdentitySessionStatus = IdentitySessionStatus.SIGNED_OUT
    warnings: list[str] = []


class IdentityAccountSummary(BaseModel):
    """Content-light summary of an identity provider account session."""

    model_config = ConfigDict(extra="forbid")

    provider: IdentityProviderKind
    status: IdentitySessionStatus
    display_name: str = ""
    scopes: list[str] = []
    expires_at: str = ""
    warnings: list[str] = []


class OAuthStartRequest(BaseModel):
    """Request to initiate an OAuth sign-in flow."""

    model_config = ConfigDict(extra="forbid")

    provider: IdentityProviderKind
    redirect_port: int = 0
    scopes: list[str] | None = None


class OAuthStartResult(BaseModel):
    """Result of initiating an OAuth sign-in flow.

    Content-light: no access/refresh/id tokens, no client_secret.
    """

    model_config = ConfigDict(extra="forbid")

    auth_url: str
    loopback_port: int
    state_hash: str
    provider: IdentityProviderKind
    status: IdentitySessionStatus = IdentitySessionStatus.PENDING
    warnings: list[str] = []


class OAuthCallbackReceipt(BaseModel):
    """Receipt for an OAuth callback exchange.

    Contains content-light metadata only — no raw tokens or codes.
    """

    model_config = ConfigDict(extra="forbid")

    provider: IdentityProviderKind
    state_hash: str
    status: IdentitySessionStatus
    account_id_hash: str = ""
    email_hash: str = ""
    display_name: str = ""
    scopes: list[str] = []
    expires_at: str = ""
    warnings: list[str] = []

    def model_dump_content_light(self) -> dict[str, Any]:
        """Dump content-light fields safe for audit/UI."""
        return self.model_dump(mode="json", exclude_none=True)
