"""Fake Google Workspace auth endpoints for local testing. No real credentials. No real network."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import secrets
import time
from typing import Any

from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceTokenStorageAuthority,
)

_JWT_PART_COUNT = 3
_BASE64_PADDING_MOD = 4

MODULE_DOC = (
    "Fake Google Workspace auth endpoints for local testing."
    " No real credentials. No real network."
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class FakeGoogleJwtSigner:
    """Signs JWT claims for Google service account authentication.

    Produces a three-part JWT string with a deterministic fake signature.
    Not cryptographically valid — for local testing only.
    """

    @staticmethod
    def sign(claims: dict[str, Any]) -> str:
        header = {"alg": "RS256", "typ": "JWT"}
        header_b64 = _b64url(json.dumps(header, sort_keys=True).encode())
        payload_b64 = _b64url(json.dumps(claims, sort_keys=True).encode())
        signing_input = f"{header_b64}.{payload_b64}"
        fake_sig = _b64url(hashlib.sha256(signing_input.encode()).digest())
        return f"{signing_input}.{fake_sig}"

    @staticmethod
    def parse_jwt(jwt_str: str) -> dict[str, Any] | None:
        parts = jwt_str.split(".")
        if len(parts) != _JWT_PART_COUNT:
            return None
        try:
            payload_b64 = parts[1]
            padding = _BASE64_PADDING_MOD - len(payload_b64) % _BASE64_PADDING_MOD
            if padding != _BASE64_PADDING_MOD:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes)
        except Exception:
            return None


@dataclass
class _FakeTokenRecord:
    access_token: str
    token_type: str = "Bearer"
    scope: str = ""
    expires_at: float = 0.0
    subject: str = ""
    revoked: bool = False


class FakeGoogleTokenEndpoint:
    """Simulates Google's OAuth token endpoint for local testing.

    Supports:
    - JWT bearer assertion exchange
    - OAuth code exchange
    - Token info / validate
    """

    def __init__(self) -> None:
        self._tokens: dict[str, _FakeTokenRecord] = {}

    def exchange_jwt_bearer(
        self, assertion: str, *, scopes: str = "", expires_in: int = 3600
    ) -> dict[str, Any]:
        claims = FakeGoogleJwtSigner.parse_jwt(assertion)
        if claims is None:
            raise ValueError("Invalid JWT assertion")

        scope = scopes or claims.get("scope", "")
        access_token = f"ya29.test_{secrets.token_hex(32)}"
        expires_at = time.time() + expires_in

        self._tokens[access_token] = _FakeTokenRecord(
            access_token=access_token,
            scope=scope,
            expires_at=expires_at,
            subject=claims.get("sub", ""),
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": scope,
        }

    def exchange_oauth_code(
        self,
        code: str,
        *,
        code_verifier: str = "",
        redirect_uri: str = "",
        scopes: str = "",
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        access_token = f"ya29.test_{secrets.token_hex(32)}"
        expires_at = time.time() + expires_in

        self._tokens[access_token] = _FakeTokenRecord(
            access_token=access_token, scope=scopes, expires_at=expires_at
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": scopes,
            "refresh_token": f"1//test_{secrets.token_hex(16)}",
        }

    def token_info(self, access_token: str) -> dict[str, Any]:
        record = self._tokens.get(access_token)
        if record is None:
            return {"error": "invalid_token", "error_description": "Token not found"}

        if record.revoked:
            return {
                "error": "invalid_token",
                "error_description": "Token has been revoked",
            }

        if time.time() > record.expires_at:
            return {
                "error": "invalid_token",
                "error_description": "Token has expired",
                "expires_in": 0,
            }

        remaining = int(record.expires_at - time.time())
        result: dict[str, Any] = {
            "active": True,
            "scope": record.scope,
            "token_type": record.token_type,
            "expires_in": remaining,
        }
        if record.subject:
            result["sub"] = record.subject
        return result

    def revoke_token(self, access_token: str) -> None:
        record = self._tokens.get(access_token)
        if record is not None:
            record.revoked = True


class FakeGoogleDomainWideDelegation:
    """Models domain-wide delegation with super-admin authorization state.

    Produces fake delegated tokens with subject field and configurable scope.
    Tracks delegation authorization via _delegation_authorized flag.
    """

    def __init__(self) -> None:
        self._delegation_authorized: bool = False
        self._endpoint = FakeGoogleTokenEndpoint()
        self._signer = FakeGoogleJwtSigner()

    @property
    def is_authorized(self) -> bool:
        return self._delegation_authorized

    def authorize(self) -> None:
        self._delegation_authorized = True

    def revoke_delegation(self) -> None:
        self._delegation_authorized = False

    def create_delegated_token(
        self,
        subject: str,
        *,
        scopes: str = "",
        service_account: str = "fake@project.iam.gserviceaccount.com",
        expires_in: int = 3600,
    ) -> dict[str, Any]:
        if not self._delegation_authorized:
            raise PermissionError("Domain-wide delegation not authorized")

        now = int(time.time())
        claims = {
            "iss": service_account,
            "scope": scopes,
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + expires_in,
            "iat": now,
            "sub": subject,
        }
        assertion = self._signer.sign(claims)
        token_response = self._endpoint.exchange_jwt_bearer(
            assertion, scopes=scopes, expires_in=expires_in
        )
        token_response["sub"] = subject
        return token_response


class FakeGoogleServiceAccountAuth:
    """Builds a complete Google Workspace service account auth state.

    Uses SHA-256 hashing for all identifiers. Never stores raw tokens
    or private keys in auth state JSON.
    """

    @staticmethod
    def build_auth_state(
        *,
        service_account: str,
        private_key_id: str = "",
        key_hash: str = "",
        domain: str = "",
        scopes: list[str] | None = None,
        subject_hashes: list[str] | None = None,
    ) -> GoogleWorkspaceAuthState:
        scopes = scopes or [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        subject_hashes = subject_hashes or []

        account_hash = hashlib.sha256(service_account.encode()).hexdigest()

        if key_hash:
            identity_input = f"{account_hash}:{key_hash}"
        elif private_key_id:
            identity_input = (
                f"{account_hash}:{hashlib.sha256(private_key_id.encode()).hexdigest()}"
            )
        else:
            identity_input = f"{account_hash}:{hashlib.sha256(b'fake-key').hexdigest()}"
        composite_account_hash = hashlib.sha256(identity_input.encode()).hexdigest()

        domain_hash = hashlib.sha256(domain.encode()).hexdigest() if domain else ""

        has_domain = bool(domain)
        auth_mode = (
            GoogleWorkspaceAuthMode.SERVICE_ACCOUNT_DOMAIN_WIDE_DELEGATION
            if has_domain
            else GoogleWorkspaceAuthMode.SERVICE_ACCOUNT
        )

        grant_hash = hashlib.sha256("::".join(sorted(scopes)).encode()).hexdigest()
        scope_grants = [
            GoogleWorkspaceScopeGrant(
                scope_id=scope,
                scope_sensitivity="sensitive",
                grant_status="active",
                grant_hash=grant_hash,
            )
            for scope in scopes
        ]

        return GoogleWorkspaceAuthState(
            auth_mode=auth_mode,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash=composite_account_hash,
            domain_hash=domain_hash,
            subject_hashes=list(subject_hashes),
            domain_wide_delegation_authorized=has_domain,
            scope_grants=scope_grants,
            token_storage_authority=GoogleWorkspaceTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
            token_material_present=True,
            token_material_stored=False,
            redaction_status="clean",
        )

    @staticmethod
    def verify_auth_state(auth_state: GoogleWorkspaceAuthState) -> list[str]:
        issues: list[str] = []

        if auth_state.token_material_stored:
            issues.append("token_material_stored must be False")

        state_dict = auth_state.to_dict()
        forbidden = {
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
            "api_key",
        }
        for key in forbidden:
            if key in state_dict:
                issues.append(f"raw_credential_rejected: field '{key}'")

        return issues

    @staticmethod
    def build_delegated_auth_state(
        *,
        service_account: str,
        domain: str,
        scopes: list[str] | None = None,
        subject_hashes: list[str] | None = None,
    ) -> GoogleWorkspaceAuthState:
        return FakeGoogleServiceAccountAuth.build_auth_state(
            service_account=service_account,
            domain=domain,
            scopes=scopes,
            subject_hashes=subject_hashes,
        )


__all__ = [
    "MODULE_DOC",
    "FakeGoogleDomainWideDelegation",
    "FakeGoogleJwtSigner",
    "FakeGoogleServiceAccountAuth",
    "FakeGoogleTokenEndpoint",
]
