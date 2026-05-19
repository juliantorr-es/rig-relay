"""Cross-Provider Fake Auth Tests — adversarial coverage for fake endpoints.

No real credentials. No real network.
"""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider import (
    FakeGitHubAppAuth,
    FakeGitHubJwtSigner,
    FakeGitHubTokenEndpoint,
    GitHubAuthMode,
    GitHubAuthStatus,
)
from rig_relay.integrations.github_provider._fake_auth import is_test_token
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
)

pytestmark = [pytest.mark.adversarial]

_SECRET_PATTERNS = [
    "ghp_1234567890abcdef1234567890abcdef12345678",
    "ghs_1234567890abcdef1234567890abcdef12345678",
    "gho_1234567890abcdef1234567890abcdef12345678",
    "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",
    "ya29.a0AfH6SM...real-google-token-pattern",
    "1//0gABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
    "-----BEGIN PRIVATE KEY-----\nmock\n-----END PRIVATE KEY-----",
    "Bearer eyJhbGciOiJSUzI1NiJ9.mock.payload",
]


class TestGitHubFakeJwtSigner:
    def test_github_fake_jwt_signer_rejects_empty_claims(self):
        signer = FakeGitHubJwtSigner()
        token = signer.sign({})
        assert "." in token
        header_b64, payload_b64, sig = token.split(".")
        decoded_payload = json.loads(
            __import__("base64").urlsafe_b64decode(payload_b64 + "==")
        )
        assert decoded_payload == {}

    def test_github_fake_jwt_signer_preserves_iss_field(self):
        signer = FakeGitHubJwtSigner()
        claims = {"iss": "12345", "iat": 1234567890, "exp": 1234568490}
        token = signer.sign(claims)
        header_b64, payload_b64, sig = token.split(".")
        decoded_payload = json.loads(
            __import__("base64").urlsafe_b64decode(payload_b64 + "==")
        )
        assert decoded_payload["iss"] == "12345"
        assert decoded_payload["iat"] == 1234567890
        assert decoded_payload["exp"] == 1234568490

    def test_github_fake_jwt_signer_produces_deterministic_but_varied_output(self):
        signer = FakeGitHubJwtSigner()
        t1 = signer.sign({"a": 1})
        t2 = signer.sign({"a": 1})
        t3 = signer.sign({"b": 2})
        assert t1 == t2
        assert t1 != t3


class TestGitHubFakeTokenEndpoint:
    def test_github_fake_token_endpoint_rejects_missing_jwt(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_installation_token("")
        assert "token" in result
        assert result["token_type"] == "installation"

    def test_github_fake_installation_token_has_expiry_field(self):
        endpoint = FakeGitHubTokenEndpoint(token_expiry_seconds=3600)
        result = endpoint.exchange_installation_token("fake.jwt.token")
        assert "token" in result
        assert "expires_at" in result
        assert "token_type" in result
        assert result["token_type"] == "installation"
        assert result["token"].startswith("ghs_test_")
        assert len(result["token"]) > 20

    def test_github_fake_oauth_rejects_missing_code(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_oauth_token("")
        assert result["token_type"] == "oauth"

    def test_github_fake_installation_token_is_valid_immediately(self):
        endpoint = FakeGitHubTokenEndpoint(token_expiry_seconds=3600)
        result = endpoint.exchange_installation_token("fake.jwt.token")
        assert endpoint.is_token_valid(result["token"]) is True

    def test_is_test_token_detects_test_tokens(self):
        assert is_test_token("ghs_test_abcdef123456") is True
        assert is_test_token("gho_test_abcdef123456") is True
        assert is_test_token("ghp_real_token_pattern") is False


class TestGitHubFakeAppAuth:
    def test_build_auth_state_has_token_material_stored_false(self):
        app = FakeGitHubAppAuth()
        auth_state, cred_lookup = app.build_auth_state()
        assert auth_state.token_material_stored is False
        assert auth_state.token_material_present is True
        assert auth_state.auth_mode == GitHubAuthMode.GITHUB_APP_INSTALLATION
        assert auth_state.auth_status == GitHubAuthStatus.AUTHENTICATED

    def test_credential_lookup_separates_tokens_from_auth_state(self):
        app = FakeGitHubAppAuth()
        auth_state, cred_lookup = app.build_auth_state()
        state_dict = auth_state.to_dict()
        for raw_token in cred_lookup.values():
            assert raw_token not in json.dumps(state_dict)

    def test_installation_token_not_valid_for_oauth_flow(self):
        endpoint = FakeGitHubTokenEndpoint()
        inst_result = endpoint.exchange_installation_token("fake.jwt.token")
        oauth_result = endpoint.exchange_oauth_token("some-code")
        assert inst_result["token_type"] == "installation"
        assert oauth_result["token_type"] == "oauth"
        assert inst_result["token"] != oauth_result["token"]

    def test_oauth_token_not_valid_for_installation_flow(self):
        endpoint = FakeGitHubTokenEndpoint()
        inst_result = endpoint.exchange_installation_token("fake.jwt.token")
        oauth_result = endpoint.exchange_oauth_token("some-code")
        assert inst_result["token_type"] != oauth_result["token_type"]


class TestGoogleWorkspaceAuthState:
    def test_google_fake_jwt_signer_rejects_empty_scope(self):
        auth = GoogleWorkspaceAuthState()
        assert auth.scope_grants == []
        grant = GoogleWorkspaceScopeGrant(
            scope_id="", scope_sensitivity=GoogleWorkspaceScopeSensitivity.NON_SENSITIVE
        )
        assert grant.scope_id == ""

    def test_google_fake_token_endpoint_rejects_non_jwt_grant_type(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode="none", auth_status=GoogleWorkspaceAuthStatus.UNAUTHENTICATED
        )
        assert not auth.is_authenticated()

    def test_google_fake_token_info_returns_status_for_valid_token(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode="oauth_user",
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            token_material_present=True,
            token_material_stored=False,
        )
        assert auth.is_authenticated()
        assert auth.is_usable()

    def test_google_fake_token_info_returns_expired_for_expired_token(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode="oauth_user",
            auth_status=GoogleWorkspaceAuthStatus.EXPIRED,
            account_hash="a" * 64,
        )
        assert not auth.is_authenticated()

    def test_google_fake_token_info_returns_revoked_for_revoked_token(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode="oauth_user",
            auth_status=GoogleWorkspaceAuthStatus.REVOKED,
            account_hash="a" * 64,
        )
        assert not auth.is_authenticated()


class TestFakeEndpointInjectionRejection:
    def test_fake_endpoints_reject_injection_attempts(self):
        signer = FakeGitHubJwtSigner()
        for secret in _SECRET_PATTERNS:
            token = signer.sign({"injected": secret})
            assert "." in token
            decoded = json.loads(
                __import__("base64").urlsafe_b64decode(token.split(".")[1] + "==")
            )
            assert decoded["injected"] == secret

    def test_fake_endpoints_never_log_credentials(self):
        signer = FakeGitHubJwtSigner()
        token = signer.sign({"secret": "ghp_sensitive_value_12345"})
        assert (
            "ghp_"
            not in __import__("base64")
            .urlsafe_b64decode(token.split(".")[0] + "==")
            .decode()
        )
        payload_raw = (
            __import__("base64").urlsafe_b64decode(token.split(".")[1] + "==").decode()
        )
        assert "ghp_sensitive_value_12345" in payload_raw
