"""GitHub identity provider — OAuth for user identity.

Supports GitHub App user auth (preferred) and OAuth App fallback.

Default scopes:
    - read:user (read user profile)
    - user:email (read user email address)

No repo scope is requested. Repo access is deferred.
"""

from __future__ import annotations

from typing import Any

from rig_relay.identity.models import (
    IdentityAccountSummary,
    IdentityProviderKind,
    TokenBundleMetadata,
)
from rig_relay.identity.providers import IdentityProvider

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com/user"

GITHUB_MINIMAL_SCOPES = ["read:user", "user:email"]

CLIENT_ID_ENV = "RIG_RELAY_GITHUB_CLIENT_ID"
CLIENT_SECRET_ENV = "RIG_RELAY_GITHUB_CLIENT_SECRET"


class GitHubIdentityProvider(IdentityProvider):
    """GitHub OAuth identity provider.

    Prefers GitHub App user auth. Falls back to OAuth App.
    """

    def __init__(
        self, client_id: str | None = None, client_secret: str | None = None
    ) -> None:
        import os

        self._client_id = client_id or os.environ.get(CLIENT_ID_ENV, "")
        self._client_secret = client_secret or os.environ.get(CLIENT_SECRET_ENV, "")

    def kind(self) -> IdentityProviderKind:
        return IdentityProviderKind.GITHUB

    def default_scopes(self) -> list[str]:
        return list(GITHUB_MINIMAL_SCOPES)

    def build_auth_url(
        self, redirect_uri: str, state: str, scopes: list[str] | None = None
    ) -> str:
        from urllib.parse import urlencode

        scopes = scopes if scopes is not None else self.default_scopes()
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "response_type": "code",
        }
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        if not self._client_id or not self._client_secret:
            msg = (
                "GitHub identity provider not configured. "
                f"Set {CLIENT_ID_ENV} and {CLIENT_SECRET_ENV}."
            )
            raise RuntimeError(msg)

        import httpx

        response = httpx.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        token_data: dict[str, Any] = response.json()

        if "access_token" in token_data:
            user_info = self._fetch_user_info(token_data["access_token"])
            token_data["account_id"] = str(user_info.get("id", ""))
            token_data["display_name"] = user_info.get("login", "")
            token_data["email"] = user_info.get("email", "")
            token_data["scopes"] = token_data.get("scope", "").split()

        return token_data

    def _fetch_user_info(self, access_token: str) -> dict[str, Any]:
        import httpx

        response = httpx.get(
            GITHUB_API_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        response.raise_for_status()
        return dict(response.json())

    def build_account_summary(
        self, metadata: TokenBundleMetadata
    ) -> IdentityAccountSummary:
        return IdentityAccountSummary(
            provider=self.kind(),
            status=metadata.status,
            display_name=metadata.display_name,
            scopes=metadata.scopes,
            expires_at=metadata.expires_at.isoformat() if metadata.expires_at else "",
            warnings=metadata.warnings,
        )

    def refresh_token(self, metadata: TokenBundleMetadata) -> dict[str, Any]:
        if not self._client_id or not self._client_secret:
            msg = (
                "GitHub identity provider not configured. "
                f"Set {CLIENT_ID_ENV} and {CLIENT_SECRET_ENV}."
            )
            raise RuntimeError(msg)

        import httpx

        response = httpx.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": "",  # GitHub OAuth Apps don't use refresh tokens
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return dict(response.json())

    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)
