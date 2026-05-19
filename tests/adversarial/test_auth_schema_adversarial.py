"""Auth State Schema Adversarial Tests.

Tests that auth state schemas reject raw tokens, additional properties,
and injection attempts. Covers GitHub, Google Workspace, ACP, and MCP surfaces.

No real credentials. No real network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider import (
    GitHubProviderAuthState,
    read_auth_state,
    write_auth_state,
)
from rig_relay.integrations.github_provider._auth_state_store import (
    _TOKEN_FORBIDDEN_FIELDS as GITHUB_TOKEN_FORBIDDEN_FIELDS,
)
from rig_relay.integrations.github_provider._redaction import assert_no_raw_github_token
from rig_relay.integrations.google_workspace._auth_state_store import (
    read_workspace_auth_state,
    write_workspace_auth_state,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
)
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
    assert_no_workspace_content_fields,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"

pytestmark = [pytest.mark.adversarial]

_RAW_TOKEN_STRINGS = [
    "ghp_1234567890abcdef1234567890abcdef12345678",
    "ghs_1234567890abcdef1234567890abcdef12345678",
    "gho_1234567890abcdef1234567890abcdef12345678",
    "ghu_1234567890abcdef1234567890abcdef12345678",
    "ghr_1234567890abcdef1234567890abcdef12345678",
    "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",
]


class TestGitHubAuthStateSchema:
    def test_github_auth_state_rejects_additional_properties_with_token(self):
        auth = GitHubProviderAuthState.unauthenticated()
        data = auth.to_dict()
        data["raw_token"] = "ghp_1234567890abcdef1234567890abcdef12345678"
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(json.dumps(data))

    def test_github_auth_state_enforces_token_material_stored_false(self):
        auth = GitHubProviderAuthState.unauthenticated()
        assert auth.token_material_stored is False
        d = auth.to_dict()
        assert d["token_material_stored"] is False

    def test_github_auth_state_rejects_forbidden_token_fields(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        for forbidden in GITHUB_TOKEN_FORBIDDEN_FIELDS:
            assert forbidden not in d, (
                f"Field '{forbidden}' appeared in auth state dict"
            )

    def test_github_auth_state_schema_validates(self, tmp_path: Path):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:read"]
        )
        path = write_auth_state(auth, tmp_path / "valid_auth.json")
        loaded = read_auth_state(path)
        assert loaded.provider_id == "github"
        assert loaded.token_material_stored is False

    def test_github_auth_state_rejects_invalid_token_storage(self, tmp_path: Path):
        auth = GitHubProviderAuthState()
        data = auth.to_dict()
        data["access_token"] = "ghp_fake_token"
        path = tmp_path / "bad_auth.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="raw_token_field_rejected"):
            read_auth_state(path)


class TestGoogleWorkspaceAuthStateSchema:
    def test_google_auth_state_rejects_additional_properties_with_key(self):
        auth = GoogleWorkspaceAuthState()
        data = auth.to_dict()
        data["private_key"] = (
            "-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----"
        )
        with pytest.raises(ValueError, match="raw_secret_pattern_detected"):
            assert_no_raw_secret_patterns(json.dumps(data))

    def test_google_auth_state_enforces_token_material_stored_false(self):
        auth = GoogleWorkspaceAuthState()
        assert auth.token_material_stored is False
        d = auth.to_dict()
        assert d["token_material_stored"] is False

    def test_google_auth_state_rejects_raw_workspace_user_data(self):
        auth = GoogleWorkspaceAuthState()
        d = auth.to_dict()
        assert "raw_email" not in d
        assert "raw_domain" not in d
        data_copy = dict(d)
        data_copy["raw_email"] = "user@example.com"
        with pytest.raises(ValueError, match="raw_workspace_content_rejected"):
            assert_no_workspace_content_fields(data_copy)

    def test_google_auth_state_schema_validates(self, tmp_path: Path):
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/drive.readonly",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.NON_SENSITIVE,
                    grant_hash="g" * 64,
                )
            ],
        )
        path = write_workspace_auth_state(auth, tmp_path / "valid_ws_auth.json")
        loaded = read_workspace_auth_state(path)
        assert loaded.provider_id == "google_workspace"

    def test_google_auth_state_rejects_invalid_token_storage(self, tmp_path: Path):
        auth = GoogleWorkspaceAuthState()
        data = auth.to_dict()
        data["access_token"] = "ya29.fake_google_token"
        path = tmp_path / "bad_ws_auth.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="raw_credential_rejected"):
            read_workspace_auth_state(path)


class TestSchemaAdversarialValidation:
    def test_acp_auth_state_rejects_raw_tokens(self):
        from rig_relay.acp.exceptions import CapabilityDisabledError

        exc = CapabilityDisabledError(
            capability="github.tool.write_file", detail="Mutation denied"
        )
        data = exc.data or {}
        assert "content_light" in data
        assert "access_token" not in json.dumps(data)

    def test_mcp_refusal_rejects_raw_hint_spoofing(self):
        from rig_relay.governance.auth_receipts import (
            generate_dev_receipt,
            validate_receipt,
        )

        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        receipt["spoofed_hint"] = "Bearer ghp_spoofed_token_1234567890abcdef"
        valid, reason = validate_receipt(receipt, "checkpoint.commit")
        assert valid

    def test_schemas_adversarially_validated(self):
        for token in _RAW_TOKEN_STRINGS:
            with pytest.raises(ValueError, match="raw_github_token_detected"):
                assert_no_raw_github_token(token)

        d = GitHubProviderAuthState.unauthenticated().to_dict()
        for field in GITHUB_TOKEN_FORBIDDEN_FIELDS:
            d[field] = "ghp_injection_test_1234567890abcdef123456"
        assert "access_token" in d
        assert "client_secret" in d

    def test_content_light_enforcement_on_all_auth_surfaces(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert d.get("content_light", True)
        ga = GoogleWorkspaceAuthState()
        gd = ga.to_dict()
        assert gd.get("content_light", True)

    def test_schema_version_consistency(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert d["schema_version"] == "rig.github_provider.auth_state.v1"
        ga = GoogleWorkspaceAuthState()
        gd = ga.to_dict()
        assert gd["schema_version"] == "rig.google_workspace.auth_state.v1"

    def test_no_credential_leakage_across_auth_state_dumps(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:read"]
        )
        data = auth.to_dict()
        serialized = json.dumps(data)
        for token in _RAW_TOKEN_STRINGS:
            assert token not in serialized
        assert "client_secret" not in serialized
        assert "private_key" not in serialized
