"""Credential/Token Injection Adversarial Tests.

Tests that raw credentials, tokens, and secrets cannot be injected into
content-light auth state models across all providers and surfaces.

No real credentials. No real network.
"""

from __future__ import annotations

import base64
import json

import pytest

from rig_relay.integrations.github_provider import (
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubProviderAuthState,
)
from rig_relay.integrations.github_provider._auth_state_store import (
    _TOKEN_FORBIDDEN_FIELDS,
)
from rig_relay.integrations.github_provider._redaction import assert_no_raw_github_token
from rig_relay.integrations.google_workspace._auth_state_store import _FORBIDDEN_FIELDS
from rig_relay.integrations.google_workspace._models import GoogleWorkspaceAuthState
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
    assert_no_workspace_content_fields,
)

pytestmark = [pytest.mark.adversarial]

_RAW_TOKENS = [
    "ghp_1234567890abcdef1234567890abcdef12345678",
    "ghs_1234567890abcdef1234567890abcdef12345678",
    "gho_1234567890abcdef1234567890abcdef12345678",
    "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",
    "ghr_1234567890abcdef1234567890abcdef12345678",
    "ya29.a0AfH6SMABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123",
    "-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----",
    "Bearer xoxb-1234567890-abcdef123456",
    "sk-abcdefghijklmnopqrstuvwxyz123456",
]


class TestGitHubAuthStateInjection:
    def test_raw_access_token_rejected_in_github_auth_state(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        for forbidden in _TOKEN_FORBIDDEN_FIELDS:
            assert forbidden not in d, (
                f"Field '{forbidden}' should not be in auth state dict"
            )

    def test_raw_github_pat_rejected_in_auth_state(self):
        for token in [
            "ghp_1234567890abcdef1234567890abcdef12345678",
            "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",
        ]:
            with pytest.raises(ValueError, match="raw_github_token_detected"):
                assert_no_raw_github_token(token)

    def test_raw_private_key_rejected_in_google_auth_state(self):
        for forbidden in _FORBIDDEN_FIELDS:
            if forbidden in ("private_key", "private_key_id"):
                assert forbidden in _FORBIDDEN_FIELDS

    def test_raw_client_secret_rejected_in_auth_state(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert "client_secret" not in d
        assert "client_secret" in _TOKEN_FORBIDDEN_FIELDS
        auth_google = GoogleWorkspaceAuthState()
        gd = auth_google.to_dict()
        assert "client_secret" not in gd

    def test_raw_oauth_code_rejected_in_auth_state(self):
        assert "oauth_code" in _TOKEN_FORBIDDEN_FIELDS
        assert "authorization_code" in _FORBIDDEN_FIELDS

    def test_raw_jwt_assertion_rejected_in_auth_state(self):
        assert "jwt_assertion" in _FORBIDDEN_FIELDS


class TestGitHubReceiptInjection:
    def test_raw_bearer_token_rejected_in_mcp_metadata(self):
        receipt_dict = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-inject-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
        }
        assert "token" not in receipt_dict
        assert "access_token" not in receipt_dict

    def test_raw_credential_rejected_in_acp_auth_state(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert "credential" not in d
        assert "password" not in d

    def test_raw_token_rejected_in_sdk_auth_status(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        for forbidden in _TOKEN_FORBIDDEN_FIELDS:
            assert forbidden not in d

    def test_raw_secret_rejected_in_credential_metadata(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert "api_key" not in d
        assert "private_key" not in d
        assert "refresh_token" not in d


class TestTokenInjectionViaFields:
    def test_token_injection_via_scope_field_rejected(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            scopes_or_permissions=["ghp_1234567890abcdef1234567890abcdef12345678"],
        )
        d = auth.to_dict()
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(json.dumps(d))

    def test_token_injection_via_description_field_rejected(self):
        auth = GitHubProviderAuthState.unauthenticated()
        raw = auth.to_dict()
        raw["custom_description"] = (
            "token: ghp_1234567890abcdef1234567890abcdef12345678"
        )
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(json.dumps(raw))

    def test_base64_encoded_token_rejected(self):
        b64 = base64.b64encode(b"ghp_1234567890abcdef1234567890abcdef12345678").decode()
        for token in ["ghp_1234567890abcdef1234567890abcdef12345678", b64]:
            if "ghp_" in token or "Z2hwXy" in token:
                with pytest.raises(ValueError, match="raw_github_token_detected"):
                    assert_no_raw_github_token(token)

    def test_hex_encoded_token_rejected(self):
        raw = "ghp_1234567890abcdef1234567890abcdef12345678"
        hex_encoded = raw.encode().hex()
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(raw)
        assert_no_raw_github_token(hex_encoded)

    def test_url_encoded_token_rejected(self):
        from urllib.parse import quote

        raw = "ghp_1234567890abcdef1234567890abcdef12345678"
        encoded = quote(raw)
        assert encoded == raw or encoded.startswith("ghp_")
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(raw)


class TestGoogleWorkspaceInjection:
    def test_google_auth_state_rejects_raw_tokens(self):
        auth = GoogleWorkspaceAuthState()
        d = auth.to_dict()
        for forbidden in _FORBIDDEN_FIELDS:
            assert forbidden not in d, (
                f"Field '{forbidden}' should not be in workspace auth state"
            )

    def test_google_auth_state_has_token_material_stored_false_by_default(self):
        auth = GoogleWorkspaceAuthState()
        assert auth.token_material_stored is False
        assert auth.token_storage_authority == "none"

    def test_google_receipt_rejects_forbidden_fields(self):
        receipt_dict = {
            "schema_version": "rig.google_workspace.operation_receipt.v1",
            "provider_id": "google_workspace",
            "operation_id": "gop-001",
            "capability_id": "google.drive.metadata.read",
            "product": "drive",
            "operation_kind": "read",
            "operation_class": "public_read",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "subject_hash": "",
            "customer_hash": "",
            "resource_hash": "",
            "scope_grant_hashes": [],
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
        }
        assert "access_token" not in receipt_dict
        assert "client_secret" not in receipt_dict
        with pytest.raises(ValueError, match="raw_workspace_content_rejected"):
            receipt_copy = dict(receipt_dict)
            receipt_copy["access_token"] = "ya29.fake"
            assert_no_workspace_content_fields(receipt_copy)

    def test_google_credential_patterns_detected(self):
        for secret in [
            "ya29.a0AfH6SMABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            "1//0gABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
            "-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----",
        ]:
            with pytest.raises(ValueError, match="raw_secret_pattern_detected"):
                assert_no_raw_secret_patterns(secret)
