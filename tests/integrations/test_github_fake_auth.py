"""GitHub Provider fake auth — unit tests for fake JWT signer, token endpoint,
and app auth builder. No network calls. No real credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

from rig_relay.integrations.github_provider import (
    FakeGitHubAppAuth,
    FakeGitHubJwtSigner,
    FakeGitHubTokenEndpoint,
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubProviderAuthState,
    assert_no_raw_github_token,
    hash_identifier,
    is_test_token,
    scan_for_tokens,
)

_SCHEMA_FIELDS_REQUIRED = frozenset({
    "schema_version",
    "provider_id",
    "auth_mode",
    "auth_status",
    "account_hash",
    "installation_id_hash",
    "scopes_or_permissions",
    "token_storage_authority",
    "token_material_present",
    "token_material_stored",
    "expires_at",
    "generated_at",
    "redaction_status",
})


class TestFakeJwtSigner:
    def test_fake_jwt_signer_produces_three_part_token(self):
        signer = FakeGitHubJwtSigner()
        claims = {"iat": 1715000000, "exp": 1715000600, "iss": "fake-app-1"}
        token = signer.sign(claims)

        parts = token.split(".")
        assert len(parts) == 3
        assert all(len(p) > 0 for p in parts)

    def test_fake_jwt_different_claims_produce_different_token(self):
        signer = FakeGitHubJwtSigner()
        a = signer.sign({"iat": 1, "iss": "app-a"})
        b = signer.sign({"iat": 2, "iss": "app-b"})
        assert a != b


class TestFakeInstallationTokenEndpoint:
    def test_fake_installation_token_endpoint_returns_test_token(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_installation_token("fake.jwt.assertion")

        assert "token" in result
        assert "expires_at" in result
        assert result["token_type"] == "installation"

    def test_fake_installation_token_has_ghs_test_prefix(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_installation_token("fake.jwt.assertion")

        assert result["token"].startswith("ghs_test_")
        assert "_test_" in result["token"]

    def test_fake_installation_token_expiry_configurable(self):
        short = FakeGitHubTokenEndpoint(token_expiry_seconds=60)
        long = FakeGitHubTokenEndpoint(token_expiry_seconds=7200)

        result_short = short.exchange_installation_token("jwt")
        result_long = long.exchange_installation_token("jwt")

        expires_short = datetime.strptime(
            result_short["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        expires_long = datetime.strptime(
            result_long["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)

        now = datetime.now(UTC)
        assert (expires_short - now).total_seconds() <= 120
        assert (expires_long - now).total_seconds() >= 6000
        assert expires_long > expires_short

    def test_fake_installation_token_expired_after_expiry(self):
        endpoint = FakeGitHubTokenEndpoint(token_expiry_seconds=0)
        result = endpoint.exchange_installation_token("jwt")
        token = result["token"]

        assert not endpoint.is_token_valid(token)

    def test_fake_installation_token_unknown_token_invalid(self):
        endpoint = FakeGitHubTokenEndpoint()
        assert not endpoint.is_token_valid("ghs_test_nonexistent")

    def test_fake_installation_token_not_matched_as_real_token(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_installation_token("jwt")

        found = scan_for_tokens(result["token"])
        assert len(found) == 0


class TestFakeOauthTokenEndpoint:
    def test_fake_oauth_token_endpoint_returns_test_token(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_oauth_token("fake-code-123")

        assert "token" in result
        assert "expires_at" in result
        assert result["token_type"] == "oauth"

    def test_fake_oauth_token_has_gho_test_prefix(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_oauth_token("fake-code-123")

        assert result["token"].startswith("gho_test_")
        assert "_test_" in result["token"]

    def test_fake_oauth_token_not_matched_as_real_token(self):
        endpoint = FakeGitHubTokenEndpoint()
        result = endpoint.exchange_oauth_token("fake-code-123")

        found = scan_for_tokens(result["token"])
        assert len(found) == 0


class TestFakeGitHubAppAuth:
    def test_fake_github_app_auth_creates_valid_auth_state(self):
        fauth = FakeGitHubAppAuth(
            app_id="fake-app-1", installation_id="fake-inst-1", account="test-user"
        )
        auth_state, cred_lookup = fauth.build_auth_state(
            scopes_or_permissions=["issues:read"], repository_names=["owner/repo"]
        )

        assert isinstance(auth_state, GitHubProviderAuthState)
        assert auth_state.auth_mode == GitHubAuthMode.GITHUB_APP_INSTALLATION
        assert auth_state.auth_status == GitHubAuthStatus.AUTHENTICATED
        assert auth_state.installation_id_hash is not None
        assert len(auth_state.installation_id_hash) == 64
        assert len(auth_state.repository_permission_grants) == 1

    def test_fake_github_app_auth_no_raw_token_in_state(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state(
            scopes_or_permissions=["issues:read"], repository_names=["owner/repo"]
        )

        d = auth_state.to_dict()
        assert "access_token" not in d
        assert "token" not in d
        assert "client_secret" not in d
        assert "refresh_token" not in d
        assert "api_key" not in d

        assert_no_raw_github_token(json.dumps(d, sort_keys=True))

    def test_fake_github_app_auth_no_raw_token_in_state_json(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state(
            scopes_or_permissions=["issues:read"], repository_names=["owner/repo"]
        )

        serialized = json.dumps(auth_state.to_dict(), sort_keys=True)
        assert "ghs_test_" not in serialized
        assert "gho_test_" not in serialized

    def test_fake_github_app_auth_uses_credential_store_abstraction(self):
        fauth = FakeGitHubAppAuth()
        auth_state, cred_lookup = fauth.build_auth_state(
            scopes_or_permissions=["issues:read"], repository_names=["owner/repo"]
        )

        assert len(cred_lookup) >= 1
        for key in cred_lookup:
            assert len(key) == 64
            assert all(c in "0123456789abcdef" for c in key)
            assert cred_lookup[key].startswith("ghs_test_")

        d = auth_state.to_dict()
        for v in cred_lookup.values():
            assert v not in json.dumps(d, sort_keys=True)

    def test_fake_github_app_auth_uses_hash_identifier(self):
        fauth = FakeGitHubAppAuth(
            app_id="app-id-abc", installation_id="inst-id-xyz", account="my-account"
        )
        auth_state, _ = fauth.build_auth_state()

        expected_account = hash_identifier("my-account")
        assert auth_state.account_hash == expected_account
        assert len(auth_state.account_hash) == 64

    def test_fake_github_app_auth_state_validates_against_schema(self):
        from pathlib import Path

        import jsonschema

        schema_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "schemas"
            / "rig.github_provider.auth_state.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)

        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state(
            scopes_or_permissions=["issues:read"], repository_names=["owner/repo"]
        )

        d = auth_state.to_dict()
        errors = [e.message for e in validator.iter_errors(d)]
        assert not errors, f"Schema validation errors: {errors}"

    def test_fake_github_app_auth_state_has_installation_id_hash(self):
        fauth = FakeGitHubAppAuth(installation_id="inst-42")
        auth_state, _ = fauth.build_auth_state()

        expected_inst = hash_identifier("inst-42")
        assert auth_state.installation_id_hash is not None
        assert auth_state.installation_id_hash == expected_inst
        assert len(auth_state.installation_id_hash) == 64

    def test_fake_github_app_auth_state_token_stored_is_false(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state()

        assert auth_state.token_material_stored is False
        assert auth_state.token_material_present is True

    def test_fake_github_app_auth_state_account_hash_set(self):
        fauth = FakeGitHubAppAuth(account="my-org-account")
        auth_state, _ = fauth.build_auth_state()

        assert auth_state.account_hash == hash_identifier("my-org-account")
        assert len(auth_state.account_hash) == 64


class TestFakeOauthAppAuth:
    def test_fake_oauth_auth_state_has_correct_mode(self):
        fauth = FakeGitHubAppAuth(account="oauth-user")
        auth_state, _ = fauth.build_oauth_auth_state(scopes=["repo", "read:user"])

        assert auth_state.auth_mode == GitHubAuthMode.OAUTH_WEB_FLOW
        assert auth_state.auth_status == GitHubAuthStatus.AUTHENTICATED
        assert "repo" in auth_state.scopes_or_permissions
        assert auth_state.installation_id_hash is None

    def test_fake_oauth_auth_state_no_raw_token(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_oauth_auth_state()

        serialized = json.dumps(auth_state.to_dict(), sort_keys=True)
        assert "gho_test_" not in serialized
        assert "ghs_test_" not in serialized


class TestFakeTokenNotMistakenForReal:
    def test_fake_token_not_mistaken_for_real_token(self):
        assert is_test_token("ghs_test_abc123")
        assert is_test_token("gho_test_xyz789")
        assert not is_test_token("ghs_abc123def456")
        assert not is_test_token("gho_xyz789abc123")
        assert not is_test_token("ghp_abc123def456")

    def test_test_token_prefix_is_distinct(self):
        endpoint = FakeGitHubTokenEndpoint()
        inst = endpoint.exchange_installation_token("jwt")
        oauth = endpoint.exchange_oauth_token("code")

        assert "test" in inst["token"]
        assert "test" in oauth["token"]
        assert inst["token"].startswith("ghs_test_")
        assert oauth["token"].startswith("gho_test_")

    def test_real_token_prefixes_dont_contain_test(self):
        real_prefixes = ["ghp_", "gho_", "ghs_", "ghu_", "ghr_", "github_pat_"]
        for prefix in real_prefixes:
            assert not is_test_token(f"{prefix}abc123")

    def test_fake_oauth_token_not_mistaken_for_real(self):
        assert is_test_token("gho_test_abc")
        assert not is_test_token("gho_abc123")
        assert not scan_for_tokens("gho_test_abc")

    def test_fake_installation_token_not_mistaken_for_real(self):
        assert is_test_token("ghs_test_abc")
        assert not is_test_token("ghs_abc123")
        assert not scan_for_tokens("ghs_test_abc")

    def test_redaction_detects_real_tokens_not_fake_test_tokens(self):
        assert not scan_for_tokens("gho_test_abc123def45678901234567890")
        assert not scan_for_tokens("ghs_test_abc123def45678901234567890")
        assert scan_for_tokens("gho_abc123def45678901234567890")
        assert scan_for_tokens("ghp_abc123def45678901234567890")


class TestFakeGitHubAppAuthEdgeCases:
    def test_auth_state_no_repositories_has_empty_grants(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state(scopes_or_permissions=["issues:read"])

        assert auth_state.repository_permission_grants == []
        assert auth_state.repository_access_hashes == []

    def test_auth_state_multiple_repositories(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state(
            scopes_or_permissions=["issues:read", "contents:read"],
            repository_names=["owner/repo-a", "owner/repo-b"],
        )

        assert len(auth_state.repository_permission_grants) == 4
        assert len(auth_state.repository_access_hashes) == 2
        assert len(auth_state.scopes_or_permissions) == 2

    def test_auth_state_token_expiry_is_future(self):
        fauth = FakeGitHubAppAuth(token_expiry_seconds=3600)
        auth_state, _ = fauth.build_auth_state()

        expires_at = datetime.strptime(
            auth_state.expires_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        assert expires_at > datetime.now(UTC)
        assert (expires_at - datetime.now(UTC)).total_seconds() > 3000

    def test_auth_state_schema_has_required_fields(self):
        fauth = FakeGitHubAppAuth()
        auth_state, _ = fauth.build_auth_state()
        d = auth_state.to_dict()

        missing = _SCHEMA_FIELDS_REQUIRED - set(d.keys())
        assert not missing, f"Missing required fields: {missing}"
