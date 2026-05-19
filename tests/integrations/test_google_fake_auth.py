"""Google Workspace fake auth — implementation tests.

No network. No credentials. No live APIs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import pytest

from rig_relay.integrations.google_workspace import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthStatus,
    read_workspace_auth_state,
    write_workspace_auth_state,
)
from rig_relay.integrations.google_workspace._fake_auth import (
    FakeGoogleDomainWideDelegation,
    FakeGoogleJwtSigner,
    FakeGoogleServiceAccountAuth,
    FakeGoogleTokenEndpoint,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceTokenStorageAuthority,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def _load_auth_schema() -> dict:
    return json.loads(
        (SCHEMAS_DIR / "rig.google_workspace.auth_state.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )


class TestFakeGoogleJwtSigner:
    @pytest.mark.contract
    def test_fake_jwt_signer_produces_three_part_token(self):
        claims = {
            "iss": "sa@project.iam.gserviceaccount.com",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        jwt = FakeGoogleJwtSigner.sign(claims)
        parts = jwt.split(".")
        assert len(parts) == 3
        assert all(p for p in parts)

    @pytest.mark.contract
    def test_fake_jwt_signer_includes_correct_claims(self):
        claims = {
            "iss": "sa@project.iam.gserviceaccount.com",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        jwt = FakeGoogleJwtSigner.sign(claims)
        parsed = FakeGoogleJwtSigner.parse_jwt(jwt)
        assert parsed is not None
        assert parsed["iss"] == claims["iss"]
        assert parsed["scope"] == claims["scope"]
        assert parsed["aud"] == claims["aud"]

    @pytest.mark.adversarial
    def test_fake_jwt_signer_parse_invalid_returns_none(self):
        assert FakeGoogleJwtSigner.parse_jwt("not.a.jwt") is None
        assert FakeGoogleJwtSigner.parse_jwt("") is None
        assert FakeGoogleJwtSigner.parse_jwt("only.two") is None


class TestFakeGoogleTokenEndpoint:
    @pytest.mark.contract
    def test_fake_token_endpoint_returns_service_account_token(self):
        claims = {
            "iss": "sa@project.iam.gserviceaccount.com",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        assertion = FakeGoogleJwtSigner.sign(claims)
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_jwt_bearer(assertion)
        assert "access_token" in response
        assert response["token_type"] == "Bearer"
        assert "expires_in" in response

    @pytest.mark.contract
    def test_fake_service_account_token_has_ya29_test_prefix(self):
        claims = {
            "iss": "sa@project.iam.gserviceaccount.com",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        assertion = FakeGoogleJwtSigner.sign(claims)
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_jwt_bearer(assertion)
        assert response["access_token"].startswith("ya29.test_")

    @pytest.mark.contract
    def test_fake_token_endpoint_returns_oauth_token(self):
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_oauth_code(
            "fake-auth-code", scopes="gmail.readonly"
        )
        assert response["access_token"].startswith("ya29.test_")
        assert response["token_type"] == "Bearer"
        assert "refresh_token" in response
        assert response["scope"] == "gmail.readonly"

    @pytest.mark.contract
    def test_fake_token_expiry_configurable(self):
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_oauth_code("code", expires_in=10)
        token = response["access_token"]
        info = endpoint.token_info(token)
        assert info["active"] is True
        assert info["expires_in"] <= 10

    @pytest.mark.integration
    def test_fake_token_expired_after_expiry(self):
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_oauth_code("code", expires_in=-1)
        token = response["access_token"]
        info = endpoint.token_info(token)
        assert "error" in info
        assert "expired" in info["error_description"].lower()

    @pytest.mark.adversarial
    def test_fake_token_revoked_returns_error(self):
        endpoint = FakeGoogleTokenEndpoint()
        response = endpoint.exchange_oauth_code("code", expires_in=3600)
        token = response["access_token"]
        endpoint.revoke_token(token)
        info = endpoint.token_info(token)
        assert "error" in info
        assert "revoked" in info["error_description"].lower()

    @pytest.mark.adversarial
    def test_fake_token_endpoint_rejects_invalid_assertion(self):
        endpoint = FakeGoogleTokenEndpoint()
        with pytest.raises(ValueError, match="Invalid"):
            endpoint.exchange_jwt_bearer("not-a-valid-jwt")

    @pytest.mark.contract
    def test_fake_token_info_unknown_token_returns_error(self):
        endpoint = FakeGoogleTokenEndpoint()
        info = endpoint.token_info("ya29.test_nonexistent")
        assert "error" in info
        assert "not found" in info["error_description"].lower()


class TestFakeGoogleDomainWideDelegation:
    @pytest.mark.contract
    def test_fake_domain_wide_delegation_produces_delegated_token(self):
        delegation = FakeGoogleDomainWideDelegation()
        delegation.authorize()
        response = delegation.create_delegated_token(
            "user@example.com", scopes="https://www.googleapis.com/auth/gmail.readonly"
        )
        assert response["access_token"].startswith("ya29.test_")
        assert response.get("sub") == "user@example.com"

    @pytest.mark.adversarial
    def test_fake_domain_wide_delegation_refused_when_not_authorized(self):
        delegation = FakeGoogleDomainWideDelegation()
        with pytest.raises(PermissionError, match="not authorized"):
            delegation.create_delegated_token("user@example.com")

    @pytest.mark.contract
    def test_fake_domain_wide_delegation_authorize_then_revoke(self):
        delegation = FakeGoogleDomainWideDelegation()
        assert not delegation.is_authorized
        delegation.authorize()
        assert delegation.is_authorized
        delegation.revoke_delegation()
        assert not delegation.is_authorized
        with pytest.raises(PermissionError, match="not authorized"):
            delegation.create_delegated_token("user@example.com")


class TestFakeGoogleServiceAccountAuth:
    @pytest.mark.contract
    def test_fake_service_account_auth_creates_valid_auth_state(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="test-sa@project.iam.gserviceaccount.com",
            private_key_id="abc123",
        )
        assert auth_state.auth_mode == str(GoogleWorkspaceAuthMode.SERVICE_ACCOUNT)
        assert auth_state.auth_status == str(GoogleWorkspaceAuthStatus.AUTHENTICATED)
        assert len(auth_state.account_hash) == 64
        assert auth_state.account_hash != ""
        assert "test-sa@" not in auth_state.account_hash
        assert auth_state.token_material_present is True
        assert auth_state.token_material_stored is False
        assert len(auth_state.scope_grants) >= 1
        assert all(str(g.grant_status) == "active" for g in auth_state.scope_grants)

    @pytest.mark.adversarial
    def test_fake_service_account_auth_no_raw_token_in_state(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="test-sa@project.iam.gserviceaccount.com"
        )
        state_dict = auth_state.to_dict()
        for forbidden in ["access_token", "refresh_token", "client_secret"]:
            assert forbidden not in state_dict, f"raw field '{forbidden}' in state"

    @pytest.mark.adversarial
    def test_fake_service_account_auth_no_raw_private_key_in_state(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="test-sa@project.iam.gserviceaccount.com",
            private_key_id="my-key-id-123",
        )
        state_dict = auth_state.to_dict()
        for forbidden in [
            "private_key",
            "private_key_id",
            "-----BEGIN PRIVATE KEY-----",
        ]:
            assert forbidden not in state_dict, f"raw key field '{forbidden}' in state"

    @pytest.mark.substrate
    def test_fake_service_account_auth_state_validates_against_schema(
        self, tmp_path: Path
    ):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="test-sa@project.iam.gserviceaccount.com",
            private_key_id="abc123",
        )
        p = write_workspace_auth_state(auth_state, tmp_path / "auth.json")
        loaded = read_workspace_auth_state(p)
        assert loaded.is_authenticated()
        assert loaded.auth_mode == str(GoogleWorkspaceAuthMode.SERVICE_ACCOUNT)

    @pytest.mark.contract
    def test_fake_scopes_tracked_in_auth_state(self):
        custom_scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com", scopes=custom_scopes
        )
        scope_ids = {g.scope_id for g in auth_state.scope_grants}
        for s in custom_scopes:
            assert s in scope_ids, f"Scope {s} missing from auth state"
        assert len(auth_state.active_grants()) == len(custom_scopes)

    @pytest.mark.adversarial
    def test_restricted_scope_posture_enforced(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com"
        )
        restricted_grants = [
            g
            for g in auth_state.scope_grants
            if str(g.scope_sensitivity) == "restricted"
        ]
        assert len(restricted_grants) == 0, (
            "Service account auth should not default to restricted scope sensitivity"
        )

    @pytest.mark.contract
    def test_fake_service_account_domain_wide_auth_state(self):
        subject_hash = hashlib.sha256(b"user@example.com").hexdigest()
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com",
            domain="example.com",
            subject_hashes=[subject_hash],
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        assert auth_state.auth_mode == str(
            GoogleWorkspaceAuthMode.SERVICE_ACCOUNT_DOMAIN_WIDE_DELEGATION
        )
        assert auth_state.domain_wide_delegation_authorized is True
        assert auth_state.domain_hash == hashlib.sha256(b"example.com").hexdigest()
        assert subject_hash in auth_state.subject_hashes

    @pytest.mark.contract
    def test_fake_service_account_auth_verify_clean(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com"
        )
        issues = FakeGoogleServiceAccountAuth.verify_auth_state(auth_state)
        assert issues == []

    @pytest.mark.adversarial
    def test_fake_service_account_auth_verify_catches_stored_token(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com"
        )
        auth_state.token_material_stored = True
        issues = FakeGoogleServiceAccountAuth.verify_auth_state(auth_state)
        assert len(issues) > 0
        assert any("token_material_stored" in i for i in issues)

    @pytest.mark.contract
    def test_fake_service_account_token_storage_authority(self):
        auth_state = FakeGoogleServiceAccountAuth.build_auth_state(
            service_account="sa@project.iam.gserviceaccount.com"
        )
        assert auth_state.token_storage_authority == str(
            GoogleWorkspaceTokenStorageAuthority.USER_SUPPLIED_RUNTIME
        )
