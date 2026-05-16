"""Tests for the Identity Provider scaffold — GitHub and Google sign-in.

Tests cover:
- Auth URL construction with minimal scopes
- Content-light result guarantees
- Token store behavior
- Desktop intent execution for identity intents
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.identity.github import GitHubIdentityProvider
from rig_relay.identity.google import GoogleIdentityProvider
from rig_relay.identity.models import (
    IdentityAccountSummary,
    IdentityProviderKind,
    IdentitySessionStatus,
    OAuthCallbackReceipt,
    OAuthStartResult,
    TokenBundleMetadata,
)
from rig_relay.identity.token_store import DevFileTokenStore

# ── Helpers ──


def _valid_request(intent_name: str = "identity_status") -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": "test_identity_001",
        "created_at": "2026-05-14T00:00:00Z",
        "intent_name": intent_name,
        "parameters": {},
        "dry_run": True,
    }


# ── GitHub Provider ──


class TestGitHubIdentityProvider:
    def test_default_scopes_are_minimal(self):
        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        assert provider.default_scopes() == ["read:user", "user:email"]
        for scope in provider.default_scopes():
            assert "repo" not in scope
            assert "admin" not in scope
            assert "workflow" not in scope

    def test_build_auth_url_includes_minimal_scopes(self):
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="test_state_123"
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["test_id"]
        assert params["redirect_uri"] == ["http://127.0.0.1:18080/callback"]
        assert params["state"] == ["test_state_123"]
        assert "read:user" in params["scope"][0]
        assert "user:email" in params["scope"][0]
        assert "repo" not in params["scope"][0]

    def test_no_repo_scope(self):
        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="s"
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "repo" not in params.get("scope", [""])[0]

    def test_auth_url_does_not_contain_secret(self):
        provider = GitHubIdentityProvider(client_id="test_id", client_secret="s3cret!")
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="s"
        )
        assert "s3cret" not in url
        assert "client_secret" not in url

    def test_exchange_code_raises_without_credentials(self):
        provider = GitHubIdentityProvider()  # no credentials
        with pytest.raises(RuntimeError, match="not configured"):
            provider.exchange_code("code", "http://127.0.0.1:18080/callback")

    def test_build_account_summary_content_light(self):
        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        metadata = TokenBundleMetadata(
            provider=IdentityProviderKind.GITHUB,
            status=IdentitySessionStatus.SIGNED_IN,
            display_name="testuser",
            scopes=["read:user", "user:email"],
            warnings=["dev-only"],
        )
        summary = provider.build_account_summary(metadata)
        assert summary.provider == IdentityProviderKind.GITHUB
        assert summary.status == IdentitySessionStatus.SIGNED_IN
        assert summary.display_name == "testuser"
        assert summary.scopes == ["read:user", "user:email"]
        # No token fields exposed
        summary_dict = summary.model_dump()
        assert "access_token" not in summary_dict
        assert "refresh_token" not in summary_dict
        assert "client_secret" not in summary_dict


# ── Google Provider ──


class TestGoogleIdentityProvider:
    def test_default_scopes_are_minimal(self):
        provider = GoogleIdentityProvider(client_id="test", client_secret="test")
        assert provider.default_scopes() == ["openid", "email", "profile"]
        for scope in provider.default_scopes():
            assert "drive" not in scope

    def test_build_auth_url_includes_minimal_scopes(self):
        provider = GoogleIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="test_state_123"
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["test_id"]
        assert params["redirect_uri"] == ["http://127.0.0.1:18080/callback"]
        assert params["state"] == ["test_state_123"]
        assert "openid" in params["scope"][0]
        assert "email" in params["scope"][0]
        assert "profile" in params["scope"][0]

    def test_no_drive_scope(self):
        provider = GoogleIdentityProvider(client_id="test", client_secret="test")
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="s"
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "drive" not in params.get("scope", [""])[0]

    def test_auth_url_does_not_contain_secret(self):
        provider = GoogleIdentityProvider(client_id="test_id", client_secret="s3cret!")
        url = provider.build_auth_url(
            redirect_uri="http://127.0.0.1:18080/callback", state="s"
        )
        assert "s3cret" not in url
        assert "client_secret" not in url

    def test_exchange_code_raises_without_credentials(self):
        provider = GoogleIdentityProvider()
        with pytest.raises(RuntimeError, match="not configured"):
            provider.exchange_code("code", "http://127.0.0.1:18080/callback")

    def test_build_account_summary_content_light(self):
        provider = GoogleIdentityProvider(client_id="test", client_secret="test")
        metadata = TokenBundleMetadata(
            provider=IdentityProviderKind.GOOGLE,
            status=IdentitySessionStatus.SIGNED_IN,
            display_name="Test User",
            scopes=["openid", "email", "profile"],
            warnings=[],
        )
        summary = provider.build_account_summary(metadata)
        assert summary.provider == IdentityProviderKind.GOOGLE
        assert summary.status == IdentitySessionStatus.SIGNED_IN
        assert summary.display_name == "Test User"
        summary_dict = summary.model_dump()
        assert "access_token" not in summary_dict
        assert "refresh_token" not in summary_dict


# ── Token Store ──


class TestDevFileTokenStore:
    def test_store_put_and_get(self, tmp_path: Path):
        store = DevFileTokenStore(store_root=tmp_path)
        meta = store.put(
            IdentityProviderKind.GITHUB,
            {
                "access_token": "gh_test_token",
                "account_id": "12345",
                "display_name": "testuser",
            },
            scopes=["read:user", "user:email"],
        )
        assert meta.provider == IdentityProviderKind.GITHUB
        assert meta.status == IdentitySessionStatus.SIGNED_IN
        assert meta.account_id_hash
        assert meta.account_id_hash != "12345"  # should be hashed
        assert meta.scopes == ["read:user", "user:email"]
        assert DevFileTokenStore.DEV_STORE_WARNING in meta.warnings

        # Verify retrieval
        retrieved = store.get(IdentityProviderKind.GITHUB)
        assert retrieved is not None
        assert retrieved.provider == IdentityProviderKind.GITHUB
        assert retrieved.account_id_hash == meta.account_id_hash
        # No raw token in metadata
        assert not hasattr(retrieved, "access_token")

    def test_store_delete_clears(self, tmp_path: Path):
        store = DevFileTokenStore(store_root=tmp_path)
        store.put(
            IdentityProviderKind.GOOGLE, {"access_token": "test"}, scopes=["openid"]
        )
        assert (
            store.status(IdentityProviderKind.GOOGLE) == IdentitySessionStatus.SIGNED_IN
        )
        deleted = store.delete(IdentityProviderKind.GOOGLE)
        assert deleted
        assert (
            store.status(IdentityProviderKind.GOOGLE)
            == IdentitySessionStatus.SIGNED_OUT
        )

    def test_content_light_metadata(self, tmp_path: Path):
        store = DevFileTokenStore(store_root=tmp_path)
        meta = store.put(
            IdentityProviderKind.GITHUB,
            {
                "access_token": "ghp_test_token_12345",
                "account_id": "42",
                "email": "user@example.com",
            },
        )
        # Email is hashed
        assert meta.email_hash
        assert "user@example.com" != meta.email_hash
        # Dump should not contain raw token
        dumped = meta.model_dump(mode="json")
        assert "email" not in dumped or dumped["email"] != "user@example.com"
        assert "access_token" not in dumped

    def test_all_statuses(self, tmp_path: Path):
        store = DevFileTokenStore(store_root=tmp_path)
        store.put(
            IdentityProviderKind.GITHUB, {"access_token": "t"}, scopes=["read:user"]
        )
        statuses = store.all_statuses()
        assert "github" in statuses
        assert statuses["github"]["status"] == "signed_in"
        assert "google" in statuses
        assert statuses["google"]["status"] == "signed_out"

    def test_store_file_has_dev_warning(self, tmp_path: Path):
        store = DevFileTokenStore(store_root=tmp_path)
        store.put(IdentityProviderKind.GITHUB, {"access_token": "test"})
        store_file = tmp_path / "github.json"
        assert store_file.is_file()
        content = store_file.read_text(encoding="utf-8")
        assert "dev_file" in content
        assert "DevFileTokenStore" in content


# ── Models: Content-Light Guarantees ──


class TestContentLightModels:
    def test_o_auth_start_result_no_tokens(self):
        result = OAuthStartResult(
            auth_url="https://github.com/login/oauth/authorize?client_id=test",
            loopback_port=18080,
            state_hash="abc123",
            provider=IdentityProviderKind.GITHUB,
        )
        d = result.model_dump()
        assert "access_token" not in d
        assert "refresh_token" not in d
        assert "client_secret" not in d
        assert d["auth_url"].startswith("https://")

    def test_o_auth_callback_receipt_content_light(self):
        receipt = OAuthCallbackReceipt(
            provider=IdentityProviderKind.GITHUB,
            state_hash="abc123",
            status=IdentitySessionStatus.SIGNED_IN,
            account_id_hash="sha256hash",
            email_hash="sha256hash",
            display_name="testuser",
            scopes=["read:user"],
        )
        d = receipt.model_dump_content_light()
        assert "access_token" not in d
        assert "refresh_token" not in d
        assert "authorization_code" not in d
        assert "client_secret" not in d
        assert d["provider"] == "github"
        assert d["status"] == "signed_in"

    def test_token_bundle_metadata_no_raw_token(self):
        meta = TokenBundleMetadata(
            provider=IdentityProviderKind.GOOGLE,
            status=IdentitySessionStatus.SIGNED_IN,
            display_name="Test",
        )
        d = meta.model_dump()
        assert "access_token" not in d
        assert "account_id_hash" in d

    def test_identity_account_summary_content_light(self):
        summary = IdentityAccountSummary(
            provider=IdentityProviderKind.GITHUB,
            status=IdentitySessionStatus.SIGNED_IN,
            display_name="user",
            scopes=["read:user"],
        )
        d = summary.model_dump()
        assert "access_token" not in d
        assert "refresh_token" not in d


# ── Desktop Intents: Identity ──


class TestIdentityIntents:
    def test_identity_status_returns_content_light(self):
        result = execute_desktop_intent(_valid_request("identity_status"))
        assert result["status"] in {"completed", "failed"}
        if result["status"] == "completed":
            extra = result.get("extra_fields", {})
            assert "providers" in extra
            assert "any_signed_in" in extra
            # No tokens in result
            assert "access_token" not in str(result)
            assert "refresh_token" not in str(result)

    def test_sign_in_github_start_does_not_return_tokens(self):
        result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert result["status"] in {"completed", "failed"}
        if result["status"] == "completed":
            extra = result.get("extra_fields", {})
            # May have auth_url or configured=false
            assert "provider" in extra
            assert extra.get("provider") == "github"
            # No tokens in result
            assert "access_token" not in str(result)
            assert "refresh_token" not in str(result)
            assert "client_secret" not in str(result)

    def test_sign_in_google_start_does_not_return_tokens(self):
        result = execute_desktop_intent(_valid_request("sign_in_google_start"))
        assert result["status"] in {"completed", "failed"}
        if result["status"] == "completed":
            extra = result.get("extra_fields", {})
            assert "provider" in extra
            assert extra.get("provider") == "google"
            # No tokens in result
            assert "access_token" not in str(result)

    def test_sign_out_provider_without_parameter_fails(self):
        result = execute_desktop_intent(_valid_request("sign_out_provider"))
        assert result["status"] == "failed"
        assert result.get("error_code") == "missing_parameter"

    def test_sign_out_provider_clears_if_present(self):
        # Store something first
        from rig_relay.identity.token_store import DevFileTokenStore

        store = DevFileTokenStore()
        store.put(IdentityProviderKind.GITHUB, {"access_token": "test"})
        assert (
            store.status(IdentityProviderKind.GITHUB) == IdentitySessionStatus.SIGNED_IN
        )

        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_sign_out_001",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "sign_out_provider",
            "parameters": {"provider": "github"},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("signed_out") is True
        # Verify cleared
        assert (
            store.status(IdentityProviderKind.GITHUB)
            == IdentitySessionStatus.SIGNED_OUT
        )

    def test_identity_intents_not_in_protected_list(self):
        from rig_relay.desktop.intents import PROTECTED_INTENTS

        for name in (
            "identity_status",
            "sign_in_github_start",
            "sign_in_google_start",
            "sign_out_provider",
        ):
            assert name not in PROTECTED_INTENTS

    def test_identity_intents_in_allowed_list(self):
        from rig_relay.desktop.intents import ALLOWED_INTENTS

        for name in (
            "identity_status",
            "sign_in_github_start",
            "sign_in_google_start",
            "sign_out_provider",
        ):
            assert name in ALLOWED_INTENTS


# ── Audit Content-Light Rules ──


class TestIdentityAuditContentLight:
    def test_identity_status_audit_artifact_no_tokens(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import emit_result

        result = execute_desktop_intent(_valid_request("identity_status"))
        if result["status"] != "completed":
            pytest.skip("Identity status not available")

        build_root = tmp_path / "intent_audit"
        build_root.mkdir(parents=True)

        emit_result(result, build_root=build_root)

        # Check written artifact
        artifacts = list((build_root / "intent_results").glob("*.json"))
        assert artifacts
        for art in artifacts:
            content = art.read_text(encoding="utf-8")
            assert "access_token" not in content
            assert "refresh_token" not in content
            assert "authorization_code" not in content
            assert "client_secret" not in content

    def test_sign_in_start_audit_artifact_no_tokens(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import emit_result

        for intent_name in ("sign_in_github_start", "sign_in_google_start"):
            result = execute_desktop_intent(_valid_request(intent_name))
            build_root = tmp_path / f"intent_audit_{intent_name}"
            build_root.mkdir(parents=True)
            emit_result(result, build_root=build_root)

            artifacts = list((build_root / "intent_results").glob("*.json"))
            if artifacts:
                for art in artifacts:
                    content = art.read_text(encoding="utf-8")
                    assert "access_token" not in content
                    assert "refresh_token" not in content

    def test_sign_out_audit_artifact_no_tokens(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import emit_result

        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_audit_sign_out",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "sign_out_provider",
            "parameters": {"provider": "github"},
            "dry_run": True,
        })
        build_root = tmp_path / "intent_audit_sign_out"
        build_root.mkdir(parents=True)
        emit_result(result, build_root=build_root)

        artifacts = list((build_root / "intent_results").glob("*.json"))
        if artifacts:
            for art in artifacts:
                content = art.read_text(encoding="utf-8")
                assert "access_token" not in content
                assert "refresh_token" not in content


# ── Telemetry Consent Tests ──


class TestTelemetryConsent:
    def test_telemetry_consent_status_returns_content_light(self):
        result = execute_desktop_intent(_valid_request("telemetry_consent_status"))
        assert result["status"] == "completed"
        assert result["result_kind"] == "telemetry_consent"
        extra = result.get("extra_fields", {})
        assert "status" in extra
        assert "scopes" in extra
        assert "access_token" not in str(result.get("extra_fields", {}))
        assert "raw_prompt" not in str(result)

    def test_telemetry_consent_grant_records_content_light(self):
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_consent_grant",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {
                "scopes": ["usage_metrics", "content_light_bundles"],
                "subject_hash": "sha256:abc123",
                "provider": "local",
            },
            "dry_run": True,
        })
        assert result["status"] == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("status") == "granted"
        assert "usage_metrics" in extra.get("scopes", [])
        assert "content_light_bundles" in extra.get("scopes", [])
        assert result["result_kind"] == "telemetry_consent"
        # Verify no raw tokens in result
        assert "access_token" not in str(result)
        assert "refresh_token" not in str(result)

    def test_telemetry_consent_revoke_records_revoked(self):
        # First grant
        execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_consent_pre",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {"scopes": ["usage_metrics"]},
            "dry_run": True,
        })
        # Then revoke
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_consent_revoke",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_revoke",
            "parameters": {},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("status") == "revoked"
        assert extra.get("revoked_at", "") != ""

    def test_consent_audit_artifact_no_tokens(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import emit_result

        for intent_name in (
            "telemetry_consent_status",
            "telemetry_consent_grant",
            "telemetry_consent_revoke",
        ):
            params = {}
            if intent_name == "telemetry_consent_grant":
                params = {"scopes": ["usage_metrics"]}
            result = execute_desktop_intent({
                "schema_version": "rig.relay.desktop_intent_request.v1",
                "intent_id": f"test_audit_{intent_name}",
                "created_at": "2026-05-14T00:00:00Z",
                "intent_name": intent_name,
                "parameters": params,
                "dry_run": True,
            })
            build_root = tmp_path / f"intent_audit_{intent_name}"
            build_root.mkdir(parents=True)
            emit_result(result, build_root=build_root)
            artifacts = list((build_root / "intent_results").glob("*.json"))
            if artifacts:
                for art in artifacts:
                    content = art.read_text(encoding="utf-8")
                    assert "access_token" not in content
                    assert "refresh_token" not in content

    def test_identity_intents_not_in_phase_1_protected(self):
        from rig_relay.desktop.intents import PHASE_1_ENABLED

        identity_intents = [
            "identity_status",
            "sign_in_github_start",
            "sign_in_google_start",
            "sign_out_provider",
            "telemetry_consent_status",
            "telemetry_consent_grant",
            "telemetry_consent_revoke",
        ]
        for intent in identity_intents:
            assert intent not in PHASE_1_ENABLED, (
                f"{intent} must not be in PHASE_1_ENABLED"
            )


# ── Scope Enforcement Tests ──


class TestScopeEnforcement:
    def test_github_scopes_are_identity_only(self):
        from rig_relay.identity.github import GitHubIdentityProvider

        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        assert provider.default_scopes() == ["read:user", "user:email"]
        for scope in provider.default_scopes():
            assert "repo" not in scope
            assert "admin" not in scope
            assert "workflow" not in scope

    def test_github_repo_scope_warned(self):
        from rig_relay.identity.github import GitHubIdentityProvider

        warnings = GitHubIdentityProvider.validate_scopes(["repo", "read:user"])
        assert any("repo" in w for w in warnings)

    def test_google_scopes_are_identity_only(self):
        from rig_relay.identity.google import GoogleIdentityProvider

        provider = GoogleIdentityProvider(client_id="test", client_secret="test")
        assert provider.default_scopes() == ["openid", "email", "profile"]
        for scope in provider.default_scopes():
            assert "drive" not in scope

    def test_google_drive_scope_warned(self):
        from rig_relay.identity.google import GoogleIdentityProvider

        warnings = GoogleIdentityProvider.validate_scopes([
            "openid",
            "email",
            "https://www.googleapis.com/auth/drive.file",
        ])
        assert any("drive" in w.lower() for w in warnings)

    def test_identity_intent_does_not_alter_authorization(self):
        """Sign-in does not alter protected intent authorization."""
        result = execute_desktop_intent(_valid_request("identity_status"))
        assert result["status"] == "completed"
        # Authorization should not be implied
        assert result.get("authorization_required", False) is False

    def test_consent_grant_does_not_imply_protected_authority(self):
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_consent_no_auth",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {"scopes": ["usage_metrics"]},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        assert result.get("authorization_required", False) is False


# ── State Root Isolation Tests ──


class TestStateRootIsolation:
    def test_consent_store_tmp_path_does_not_touch_home(self, tmp_path: Path):
        """ConsentStore with explicit store_root writes only to tmp_path."""
        from rig_relay.identity.consent_store import ConsentStore
        from rig_relay.identity.telemetry_consent import grant_consent

        store = ConsentStore(store_root=tmp_path / "consent")
        record = grant_consent(subject_hash="sha256:test", provider="test")
        store.save(record)

        # Verify file is under tmp_path
        consent_file = tmp_path / "consent" / "telemetry_consent.json"
        assert consent_file.is_file()
        # Verify NOT in home
        assert str(consent_file).startswith(str(tmp_path))

    def test_token_store_tmp_path_does_not_touch_home(self, tmp_path: Path):
        """DevFileTokenStore with explicit store_root writes only to tmp_path."""
        from rig_relay.identity.models import IdentityProviderKind
        from rig_relay.identity.token_store import DevFileTokenStore

        store = DevFileTokenStore(store_root=tmp_path / "identity")
        bundle = {
            "access_token": "test_token",
            "account_id": "123",
            "email": "test@test.com",
        }
        store.put(IdentityProviderKind.GITHUB, bundle)

        token_file = tmp_path / "identity" / "github.json"
        assert token_file.is_file()
        assert str(token_file).startswith(str(tmp_path))

    def test_telemetry_consent_grant_with_state_root(self, tmp_path: Path):
        """telemetry_consent_grant with explicit state_root writes to tmp_path."""
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_state_root_grant",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {"scopes": ["usage_metrics"], "state_root": str(tmp_path)},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        # Verify consent was written to tmp_path
        consent_file = tmp_path / "consent" / "telemetry_consent.json"
        assert consent_file.is_file(), f"Consent file not at {consent_file}"

    def test_telemetry_consent_status_with_state_root(self, tmp_path: Path):
        """telemetry_consent_status from explicit state_root."""
        # First grant with state_root
        execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_state_root_status_pre",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {"scopes": ["usage_metrics"], "state_root": str(tmp_path)},
            "dry_run": True,
        })
        # Then read status from same state_root
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_state_root_status",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_status",
            "parameters": {"state_root": str(tmp_path)},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("status") == "granted", (
            f"Expected granted, got {extra.get('status')}"
        )

    def test_telemetry_consent_revoke_with_state_root(self, tmp_path: Path):
        """telemetry_consent_revoke from explicit state_root."""
        # Grant
        execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_revoke_grant",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_grant",
            "parameters": {"scopes": ["usage_metrics"], "state_root": str(tmp_path)},
            "dry_run": True,
        })
        # Revoke
        result = execute_desktop_intent({
            "schema_version": "rig.relay.desktop_intent_request.v1",
            "intent_id": "test_revoke",
            "created_at": "2026-05-14T00:00:00Z",
            "intent_name": "telemetry_consent_revoke",
            "parameters": {"state_root": str(tmp_path)},
            "dry_run": True,
        })
        assert result["status"] == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("status") == "revoked"

    def test_default_state_root_is_home_relay(self):
        """default_relay_state_root() returns ~/.rig/relay/."""
        from rig_relay.identity.state_paths import default_relay_state_root

        expected = Path.home() / ".rig" / "relay"
        assert default_relay_state_root() == expected

    def test_identity_state_root_with_explicit_root(self, tmp_path: Path):
        """identity_state_root with explicit root."""
        from rig_relay.identity.state_paths import identity_state_root

        assert identity_state_root(root=tmp_path) == tmp_path / "identity"

    def test_consent_state_root_with_explicit_root(self, tmp_path: Path):
        """consent_state_root with explicit root."""
        from rig_relay.identity.state_paths import consent_state_root

        assert consent_state_root(root=tmp_path) == tmp_path / "consent"
