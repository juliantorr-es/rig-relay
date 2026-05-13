"""Google identity provider — OAuth/OIDC for user identity.

Default scopes:
    - openid (OIDC)
    - email (email address)
    - profile (display name, avatar)

No Drive scope is requested. Drive access is deferred and will use
incremental authorization when implemented.
"""

from __future__ import annotations

from typing import Any

from rig_relay.identity.models import (
    IdentityAccountSummary,
    IdentityProviderKind,
    TokenBundleMetadata,
)
from rig_relay.identity.providers import IdentityProvider

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GOOGLE_MINIMAL_SCOPES = ["openid", "email", "profile"]

CLIENT_ID_ENV = "RIG_RELAY_GOOGLE_CLIENT_ID"
CLIENT_SECRET_ENV = "RIG_RELAY_GOOGLE_CLIENT_SECRET"


class GoogleIdentityProvider(IdentityProvider):
    """Google OAuth/OIDC identity provider.

    Requests identity-only scopes. Drive is deferred.
    Uses incremental authorization pattern.
    """

    def __init__(
        self, client_id: str | None = None, client_secret: str | None = None
    ) -> None:
        import os

        self._client_id = client_id or os.environ.get(CLIENT_ID_ENV, "")
        self._client_secret = client_secret or os.environ.get(CLIENT_SECRET_ENV, "")

    def kind(self) -> IdentityProviderKind:
        return IdentityProviderKind.GOOGLE

    def default_scopes(self) -> list[str]:
        return list(GOOGLE_MINIMAL_SCOPES)

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
            "access_type": "offline",
            "include_granted_scopes": "true",
        }
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        if not self._client_id or not self._client_secret:
            msg = (
                "Google identity provider not configured. "
                f"Set {CLIENT_ID_ENV} and {CLIENT_SECRET_ENV}."
            )
            raise RuntimeError(msg)

        import httpx

        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        token_data: dict[str, Any] = response.json()

        if "access_token" in token_data:
            user_info = self._fetch_user_info(token_data["access_token"])
            token_data["account_id"] = str(user_info.get("id", ""))
            token_data["display_name"] = user_info.get("name", "")
            token_data["email"] = user_info.get("email", "")

        return token_data

    def _fetch_user_info(self, access_token: str) -> dict[str, Any]:
        import httpx

        response = httpx.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
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
                "Google identity provider not configured. "
                f"Set {CLIENT_ID_ENV} and {CLIENT_SECRET_ENV}."
            )
            raise RuntimeError(msg)
        import httpx

        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": "",  # stored token needed; placeholder
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return dict(response.json())

    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)
