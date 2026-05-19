"""Fake GitHub auth endpoints for local testing. No real credentials. No real network."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
import time
from typing import Any

from rig_relay.integrations.github_provider._models import (
    GitHubAccessLevel,
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubGrantStatus,
    GitHubPermissionKind,
    GitHubProviderAuthState,
    GitHubRedactionStatus,
    GitHubRepositoryPermissionGrant,
    GitHubTokenStorageAuthority,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier

MODULE_DOC = "Fake GitHub auth endpoints for local testing. No real credentials. No real network."

_FAKE_JWT_HEADER = {"alg": "RS256", "typ": "JWT"}


class FakeGitHubJwtSigner:
    """Signs JWT claims with a fake key for GitHub App token requests.

    Produces a three-part header.payload.signature token. The signature is
    a SHA-256 hash of hardcoded salt + payload — NOT cryptographically valid.
    """

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def sign(self, claims: dict[str, Any]) -> str:
        header_b64 = self._b64(
            json.dumps(_FAKE_JWT_HEADER, separators=(",", ":")).encode()
        )
        payload_b64 = self._b64(json.dumps(claims, separators=(",", ":")).encode())
        signature = hashlib.sha256(
            f"fake-github-jwt-signing-key:{payload_b64}".encode()
        ).hexdigest()
        return f"{header_b64}.{payload_b64}.{signature}"

    def __call__(self, claims: dict[str, Any]) -> str:
        return self.sign(claims)


def _make_test_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


class FakeGitHubTokenEndpoint:
    """Simulates GitHub's token endpoint for installation and OAuth exchange."""

    def __init__(
        self,
        token_expiry_seconds: int = 3600,
        installation_id: str = "fake-installation-12345",
    ) -> None:
        self._token_expiry_seconds = token_expiry_seconds
        self._installation_id = installation_id
        self._issued_tokens: dict[str, dict[str, Any]] = {}
        self._issued_at: dict[str, datetime] = {}

    def exchange_installation_token(self, jwt_assertion: str) -> dict[str, Any]:
        token = _make_test_token("ghs_test")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._token_expiry_seconds)
        expires_str = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        result = {
            "token": token,
            "expires_at": expires_str,
            "token_type": "installation",
            "installation_id": self._installation_id,
        }
        self._issued_tokens[token] = result
        self._issued_at[token] = now
        return result

    def exchange_oauth_token(
        self, code: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        token = _make_test_token("gho_test")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._token_expiry_seconds)
        expires_str = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        result = {
            "token": token,
            "expires_at": expires_str,
            "token_type": "oauth",
            "scope": "repo,read:user",
        }
        self._issued_tokens[token] = result
        self._issued_at[token] = now
        return result

    def is_token_valid(self, token: str) -> bool:
        info = self._issued_tokens.get(token)
        if info is None:
            return False
        try:
            expires_at = datetime.strptime(
                info["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except (ValueError, KeyError):
            return False
        return datetime.now(UTC) < expires_at

    @property
    def token_expiry_seconds(self) -> int:
        return self._token_expiry_seconds


class FakeGitHubAppAuth:
    """Builds a complete GitHub App installation auth state with fake tokens.

    Uses hash_identifier() for all hashes. Returns content-light auth state
    and a separate credential-lookup dict — the credential store abstraction.
    Raw tokens live only in the lookup dict, never in the auth state JSON.
    """

    def __init__(
        self,
        app_id: str = "fake-app-67890",
        installation_id: str = "fake-installation-12345",
        account: str = "fake-github-account",
        token_expiry_seconds: int = 3600,
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._account = account
        self._token_expiry_seconds = token_expiry_seconds
        self._signer = FakeGitHubJwtSigner()
        self._token_endpoint = FakeGitHubTokenEndpoint(
            token_expiry_seconds=token_expiry_seconds, installation_id=installation_id
        )

    @property
    def token_endpoint(self) -> FakeGitHubTokenEndpoint:
        return self._token_endpoint

    def build_jwt_claims(self) -> dict[str, Any]:
        now = int(time.time())
        return {"iat": now, "exp": now + 600, "iss": self._app_id}

    def build_auth_state(
        self,
        scopes_or_permissions: list[str] | None = None,
        repository_names: list[str] | None = None,
    ) -> tuple[GitHubProviderAuthState, dict[str, str]]:
        jwt_claims = self.build_jwt_claims()
        jwt_assertion = self._signer(jwt_claims)
        token_response = self._token_endpoint.exchange_installation_token(jwt_assertion)

        token = token_response["token"]
        account_hash = hash_identifier(self._account)
        installation_id_hash = hash_identifier(self._installation_id)

        credential_lookup: dict[str, str] = {hash_identifier(token): token}

        scopes = scopes_or_permissions or ["issues:read"]
        repo_hashes: list[str] = []
        grants: list[GitHubRepositoryPermissionGrant] = []
        if repository_names:
            for repo_name in repository_names:
                repo_hash = hash_identifier(repo_name)
                repo_hashes.append(repo_hash)
                for perm in scopes:
                    level = "write" if perm.endswith(":write") else "read"
                    grants.append(
                        GitHubRepositoryPermissionGrant(
                            repository_hash=repo_hash,
                            permission_id=perm,
                            permission_kind=GitHubPermissionKind.GITHUB_APP_PERMISSION,
                            access_level=GitHubAccessLevel.WRITE
                            if level == "write"
                            else GitHubAccessLevel.READ,
                            source_auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION.value,
                            grant_hash=hash_identifier(f"{repo_hash}:{perm}"),
                            expires_at=token_response["expires_at"],
                            grant_status=GitHubGrantStatus.ACTIVE,
                        )
                    )

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._token_expiry_seconds)

        auth_state = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash=account_hash,
            installation_id_hash=installation_id_hash,
            scopes_or_permissions=scopes,
            repository_access_hashes=repo_hashes,
            repository_permission_grants=grants,
            token_storage_authority=GitHubTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
            token_material_present=True,
            token_material_stored=False,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            redaction_status=GitHubRedactionStatus.CLEAN,
        )

        return auth_state, credential_lookup

    def build_oauth_auth_state(
        self, scopes: list[str] | None = None
    ) -> tuple[GitHubProviderAuthState, dict[str, str]]:
        code = f"fake-code-{hash_identifier('oauth')[:8]}"
        token_response = self._token_endpoint.exchange_oauth_token(code)

        token = token_response["token"]
        account_hash = hash_identifier(self._account)

        credential_lookup: dict[str, str] = {hash_identifier(token): token}

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._token_expiry_seconds)

        auth_state = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash=account_hash,
            scopes_or_permissions=scopes or ["repo"],
            token_storage_authority=GitHubTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
            token_material_present=True,
            token_material_stored=False,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            redaction_status=GitHubRedactionStatus.CLEAN,
        )

        return auth_state, credential_lookup


def is_test_token(token: str) -> bool:
    return "_test_" in token


__all__ = [
    "FakeGitHubAppAuth",
    "FakeGitHubJwtSigner",
    "FakeGitHubTokenEndpoint",
    "is_test_token",
]
