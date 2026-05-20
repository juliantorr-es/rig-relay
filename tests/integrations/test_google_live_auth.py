"""Google Live Auth — opt-in tests.

All tests require RIG_LIVE_AUTH_TESTS=1 to run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest


def _require_live_auth() -> None:
    if os.environ.get("RIG_LIVE_AUTH_TESTS") != "1":
        pytest.skip("RIG_LIVE_AUTH_TESTS not set to 1")


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestPKCE:
    def test_pkce_verifier_length_128_default(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import generate_code_verifier

        _require_live_auth()
        verifier = generate_code_verifier()
        assert len(verifier) == 128

    def test_pkce_verifier_min_length_43(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import generate_code_verifier

        _require_live_auth()
        verifier = generate_code_verifier(length=43)
        assert len(verifier) == 43

    def test_pkce_verifier_max_length_128(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import generate_code_verifier

        _require_live_auth()
        verifier = generate_code_verifier(length=128)
        assert len(verifier) == 128

    def test_pkce_verifier_rejects_less_than_43(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_verifier,
            validate_verifier_length,
        )

        _require_live_auth()
        short_verifier = "a" * 42
        assert not validate_verifier_length(short_verifier)
        with pytest.raises(ValueError):
            generate_code_verifier(length=42)

    def test_pkce_verifier_rejects_more_than_128(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_verifier,
            validate_verifier_length,
        )

        _require_live_auth()
        long_verifier = "a" * 129
        assert not validate_verifier_length(long_verifier)
        with pytest.raises(ValueError):
            generate_code_verifier(length=129)

    def test_pkce_challenge_is_base64url_no_padding(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_challenge,
            generate_code_verifier,
        )

        _require_live_auth()
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        assert "=" not in challenge
        assert len(challenge) == 43

    def test_pkce_challenge_is_sha256_of_verifier(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_challenge,
        )

        _require_live_auth()
        verifier = "test-verifier-value-for-pkce-testing-12345"
        challenge = generate_code_challenge(verifier)
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = (
            base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        )
        assert challenge == expected

    def test_pkce_different_each_time(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import generate_code_verifier

        _require_live_auth()
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        assert v1 != v2

    def test_pkce_create_params_returns_valid_both(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            PKCEParams,
            create_pkce_params,
            generate_code_challenge,
            validate_code_challenge,
            validate_verifier_length,
        )

        _require_live_auth()
        params = create_pkce_params()
        assert isinstance(params, PKCEParams)
        assert validate_verifier_length(params.verifier)
        assert validate_code_challenge(params.challenge)
        assert params.challenge == generate_code_challenge(params.verifier)

    def test_pkce_validate_code_challenge_rejects_invalid(self) -> None:
        from rig_relay.integrations.google_workspace._pkce import (
            validate_code_challenge,
        )

        _require_live_auth()
        assert not validate_code_challenge("")
        assert not validate_code_challenge("abc")
        assert not validate_code_challenge("a" * 44)


class TestLiveAuthConfig:
    def test_live_auth_config_loads_from_env(self) -> None:
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveAuthConfig,
        )

        _require_live_auth()
        config = GoogleLiveAuthConfig()
        assert isinstance(config.client_id, str)
        assert isinstance(config.client_secret, str)
        assert isinstance(config.redirect_uri, str)

    def test_live_auth_config_summary_no_raw_secrets(self) -> None:
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveAuthConfig,
        )

        _require_live_auth()
        os.environ["RIG_GOOGLE_CLIENT_ID"] = "test-client-id.example.com"
        os.environ["RIG_GOOGLE_CLIENT_SECRET"] = "super-secret-value"
        try:
            config = GoogleLiveAuthConfig()
            summary = config.config_summary()
            assert "client_secret" not in summary
            assert "super-secret" not in json.dumps(summary)
            assert "client_id_hash" in summary
        finally:
            del os.environ["RIG_GOOGLE_CLIENT_ID"]
            del os.environ["RIG_GOOGLE_CLIENT_SECRET"]

    def test_live_auth_config_unconfigured_by_default(self) -> None:
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveAuthConfig,
        )

        _require_live_auth()
        for var in (
            "RIG_GOOGLE_CLIENT_ID",
            "RIG_GOOGLE_CLIENT_SECRET",
            "RIG_GOOGLE_REDIRECT_URI",
            "RIG_GOOGLE_SERVICE_ACCOUNT_KEY_PATH",
            "RIG_GOOGLE_SERVICE_ACCOUNT_EMAIL",
        ):
            os.environ.pop(var, None)
        config = GoogleLiveAuthConfig()
        assert not config.is_configured()


class TestLiveTokenExchanger:
    def test_live_token_exchanger_imports_cleanly(self) -> None:
        _require_live_auth()
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveTokenExchanger,
        )

        assert hasattr(GoogleLiveTokenExchanger, "exchange_oauth_code")
        assert hasattr(GoogleLiveTokenExchanger, "exchange_refresh_token")
        assert hasattr(GoogleLiveTokenExchanger, "validate_token")

    def test_live_token_exchanger_httpx_available_returns_module(self) -> None:
        _require_live_auth()
        from rig_relay.integrations.google_workspace._live_auth import _get_httpx

        result = _get_httpx()
        assert result is not None
        assert hasattr(result, "post")

    def test_content_light_token_response_hashes_tokens(self) -> None:
        _require_live_auth()
        from rig_relay.integrations.google_workspace._live_auth import (
            _content_light_token_response,
        )

        raw = {
            "access_token": "ya29.a0AfH6SMB-test-token-value",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": "openid email profile",
            "refresh_token": "1//0gRefreshTokenValue",
        }
        result = _content_light_token_response(raw)
        serialized = json.dumps(result)
        assert "access_token" not in result
        assert "refresh_token" not in result
        assert "token_hash" in result
        assert "refresh_token_hash" in result
        assert "token_prefix" not in result
        assert "refresh_token_prefix" not in result
        assert "token_prefix" not in serialized
        assert "refresh_token_prefix" not in serialized
        assert result["expires_in"] == 3599
        assert result["scope"] == "openid email profile"


class TestLiveReadOnlySmoke:
    def test_live_read_only_smoke_functions_exist(self) -> None:
        _require_live_auth()
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveReadOnlySmoke,
        )

        assert hasattr(GoogleLiveReadOnlySmoke, "inspect_identity")
        assert hasattr(GoogleLiveReadOnlySmoke, "list_gmail_profile")
        assert hasattr(GoogleLiveReadOnlySmoke, "list_calendar_list")
        assert hasattr(GoogleLiveReadOnlySmoke, "list_drive_metadata")

    def test_read_only_smoke_scope_refusal(self) -> None:
        _require_live_auth()
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveReadOnlySmoke,
        )

        result = GoogleLiveReadOnlySmoke.list_gmail_profile(
            token="fake-token",
            token_scope="https://www.googleapis.com/auth/calendar.readonly",
        )
        assert "error" in result


class TestScopeManifest:
    def test_scope_manifest_loads_and_validates(self) -> None:
        _require_live_auth()
        manifest_path = (
            REPO_ROOT
            / "docs"
            / "json"
            / "integrations"
            / "google_workspace_scope_manifest_v1.v1.json"
        )
        assert manifest_path.is_file()
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == "rig.google_workspace.scope_manifest.v1"
        assert raw["provider_id"] == "google_workspace"
        scopes = raw["scopes"]
        assert isinstance(scopes, list)
        assert len(scopes) >= 12
        required_fields = {
            "scope_id",
            "human_label",
            "sensitivity",
            "risk_level",
            "requires_security_assessment",
            "minimum_verification_level",
        }
        for scope in scopes:
            missing = required_fields - set(scope.keys())
            assert not missing, f"Scope {scope.get('scope_id', '?')} missing: {missing}"
            assert scope["sensitivity"] in {
                "non_sensitive",
                "sensitive",
                "restricted",
                "admin_restricted",
            }
