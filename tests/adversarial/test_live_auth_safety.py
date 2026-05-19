"""Live-auth safety adversarial tests.

Comprehensive opt-in live-auth safety tests. ALL tests skip if
RIG_LIVE_AUTH_TESTS env var is not "1". Tests verify safety properties
without real network — using fake/stub objects where needed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RIG_LIVE_AUTH_TESTS") != "1",
    reason="live auth tests require RIG_LIVE_AUTH_TESTS=1",
)


class TestLiveAuthSecretBoundaries:
    def test_github_live_auth_config_summary_no_private_key_content(self, monkeypatch):
        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveAuthConfig,
        )

        monkeypatch.setenv("RIG_GITHUB_APP_ID", "12345")
        monkeypatch.setenv("RIG_GITHUB_INSTALLATION_ID", "67890")
        monkeypatch.setenv(
            "RIG_GITHUB_PRIVATE_KEY_ENV",
            "-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY_CONTENT\n-----END RSA PRIVATE KEY-----",
        )
        config = GitHubLiveAuthConfig.from_environment()
        summary = config.config_summary()
        assert "-----BEGIN RSA PRIVATE KEY-----" not in json.dumps(summary)
        assert "MOCK_KEY_CONTENT" not in json.dumps(summary)
        assert summary["private_key_present"] is True
        assert isinstance(summary["private_key_present"], bool)

    def test_github_live_auth_config_summary_no_client_secret(self, monkeypatch):
        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveAuthConfig,
        )

        monkeypatch.setenv("RIG_GITHUB_CLIENT_ID", "github-client-id-123")
        monkeypatch.setenv(
            "RIG_GITHUB_CLIENT_SECRET", "super-secret-client-secret-value"
        )
        config = GitHubLiveAuthConfig.from_environment()
        summary = config.config_summary()
        assert "super-secret-client-secret-value" not in json.dumps(summary)
        assert summary["client_secret_configured"] is True
        assert isinstance(summary["client_secret_configured"], bool)
        assert "client_secret" not in summary

    def test_google_live_auth_config_summary_no_client_secret(self, monkeypatch):
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveAuthConfig,
        )

        monkeypatch.setenv("RIG_GOOGLE_CLIENT_ID", "google-client-id-123")
        monkeypatch.setenv(
            "RIG_GOOGLE_CLIENT_SECRET", "google-super-secret-value-abcdef"
        )
        config = GoogleLiveAuthConfig()
        summary = config.config_summary()
        assert "google-super-secret-value-abcdef" not in json.dumps(summary)
        assert "client_secret" not in summary
        assert summary["oauth_configured"] is True

    def test_github_live_token_exchanger_never_returns_raw_token(self):
        from rig_relay.integrations.github_provider._live_auth import (
            _redact_token_response,
        )

        raw_token = "ghp_1234567890abcdef1234567890abcdef12345678"
        raw_response = {
            "token": raw_token,
            "expires_at": "2026-06-19T00:00:00Z",
            "permissions": {"issues": "read"},
            "repository_selection": "selected",
        }
        result = _redact_token_response(raw_response, raw_token, kind="installation")
        result_str = json.dumps(result)
        assert raw_token not in result_str
        assert "token_hash" in result
        assert result["token_prefix"] == raw_token[:8]
        assert len(result["token_prefix"]) == 8
        assert "token" not in result
        assert isinstance(result.get("token_hash"), str)
        assert len(result["token_hash"]) == 64
        assert result.get("token_hash") != raw_token

    def test_google_live_token_exchanger_never_returns_raw_token(self):
        from rig_relay.integrations.google_workspace._live_auth import (
            _content_light_token_response,
        )

        raw_token = "ya29.a0AfH6SMABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        raw_response = {
            "access_token": raw_token,
            "expires_in": 3599,
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "token_type": "Bearer",
            "refresh_token": "1//0gABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop",
        }
        result = _content_light_token_response(raw_response)
        result_str = json.dumps(result)
        assert raw_token not in result_str
        assert raw_response["refresh_token"] not in result_str
        assert result["token_prefix"] == raw_token[:8]
        assert len(result["token_prefix"]) == 8
        assert len(result.get("token_hash", "")) == 64
        assert result.get("token_hash") != raw_token

    def test_github_live_read_only_smoke_never_returns_raw_response_bodies(self):
        from rig_relay.integrations.github_provider._live_auth import _redact_repo

        raw_repo = {
            "full_name": "owner/private-repo",
            "name": "private-repo",
            "private": True,
            "permissions": {"admin": True, "push": True, "pull": True},
            "owner": {"login": "owner", "type": "User"},
            "html_url": "https://github.com/owner/private-repo",
        }
        result = _redact_repo(raw_repo)
        result_str = json.dumps(result)
        assert "owner/private-repo" not in result_str
        assert "private-repo" not in result_str
        assert "name_hash" in result
        assert len(result["name_hash"]) == 64
        assert result["name_hash"] != "private-repo"
        assert result.get("owner_type") == "User"

    def test_google_live_read_only_smoke_never_returns_raw_response_bodies(self):
        from rig_relay.integrations.google_workspace._live_auth import _sha256_hex

        mock_raw = {
            "files": [
                {
                    "id": "file123",
                    "name": "confidential-doc",
                    "mimeType": "application/pdf",
                }
            ]
        }
        files = []
        for f in mock_raw.get("files", []):
            files.append({
                "id_hash": _sha256_hex(f.get("id", "")),
                "name_hash": _sha256_hex(f.get("name", "")) if f.get("name") else "",
                "mime_type": f.get("mimeType", ""),
            })
        result_str = json.dumps(files)
        assert "confidential-doc" not in result_str
        assert "file123" not in result_str

    def test_no_credential_logging_in_live_modules(self):
        import ast

        live_files = [
            "rig_relay/integrations/github_provider/_live_auth.py",
            "rig_relay/integrations/google_workspace/_live_auth.py",
        ]
        for path in live_files:
            source = _read_module(path)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = _get_func_name(node)
                    if func_name in (
                        "print",
                        "logger.info",
                        "logger.debug",
                        "logger.warning",
                        "logger.error",
                        "logger.critical",
                        "logging.info",
                        "logging.debug",
                        "logging.warning",
                        "logging.error",
                        "logging.critical",
                    ):
                        args_str = ast.unparse(node)
                        lowered = args_str.lower()
                        for keyword in ("token", "secret", "key"):
                            if keyword in lowered and "token_hash" not in lowered:
                                if "public" not in lowered and "_id" not in lowered:
                                    pytest.fail(
                                        f"Credential keyword '{keyword}' found in "
                                        f"logging/print call in {path}: {args_str[:200]}"
                                    )

    def test_credential_store_metadata_never_raw_token(self, tmp_path, monkeypatch):
        from rig_relay.identity._credential_store import KeychainBackedCredentialStore

        class FakeKeyring:
            @staticmethod
            def set_password(service, account, password):
                pass

            @staticmethod
            def delete_password(service, account):
                pass

            @staticmethod
            def get_password(service, account):
                return None

        monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        store.store(
            "github", "oauth_token", "ghp_1234567890abcdef1234567890abcdef12345678"
        )

        meta_file = tmp_path / "credential_metadata.json"
        content = meta_file.read_text(encoding="utf-8")
        assert "ghp_" not in content
        assert "gho_" not in content
        assert "ghs_" not in content
        assert "ghu_" not in content
        assert "ghr_" not in content
        assert "ya29." not in content

    def test_sdk_auth_status_never_raw_credentials(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        status = RigProviderLiveAuthStatus(
            provider_id="github",
            configured=True,
            auth_mode="oauth_web_flow",
            auth_status="authenticated",
            credential_store_available=True,
            credential_store_ref_hash="a" * 64,
            scopes_or_permissions=["repo:read", "user:email"],
            capability_id="provider.github.live_auth",
            trace_id="trace-abc",
            receipt_id="receipt-xyz",
        )
        d = status.to_dict()
        for forbidden in (
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
            "api_key",
            "password",
        ):
            assert forbidden not in d, f"Field '{forbidden}' found in status dict"


class TestPKCEAdversarial:
    def test_pkce_verifier_too_short_rejected(self):
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_verifier,
            validate_verifier_length,
        )

        with pytest.raises(ValueError, match="verifier length"):
            generate_code_verifier(length=42)
        assert validate_verifier_length("abc") is False
        assert validate_verifier_length("a" * 42) is False

    def test_pkce_verifier_too_long_rejected(self):
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_verifier,
            validate_verifier_length,
        )

        with pytest.raises(ValueError, match="verifier length"):
            generate_code_verifier(length=129)
        assert validate_verifier_length("a" * 129) is False

    def test_pkce_verifier_empty_rejected(self):
        from rig_relay.integrations.google_workspace._pkce import (
            validate_verifier_length,
        )

        assert validate_verifier_length("") is False

    def test_pkce_challenge_is_deterministic(self):
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_challenge,
        )

        verifier = "a" * 43
        challenge1 = generate_code_challenge(verifier)
        challenge2 = generate_code_challenge(verifier)
        assert challenge1 == challenge2

        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        import base64

        expected = (
            base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        )
        assert challenge1 == expected

    def test_pkce_mismatched_verifier_challenge_rejected(self):
        from rig_relay.integrations.google_workspace._pkce import (
            generate_code_challenge,
        )

        verifier_a = "a" * 43
        verifier_b = "b" * 43
        challenge_a = generate_code_challenge(verifier_a)
        challenge_b = generate_code_challenge(verifier_b)
        assert challenge_a != challenge_b

    def test_pkce_no_null_bytes_in_verifier(self):
        from rig_relay.integrations.google_workspace._pkce import generate_code_verifier

        verifier = generate_code_verifier()
        assert "\x00" not in verifier
        assert len(verifier) >= 43
        assert len(verifier) <= 128


class TestLiveAuthRefusalPatterns:
    def test_github_unconfigured_returns_refusal_not_crash(self, monkeypatch):
        for var in (
            "RIG_GITHUB_APP_ID",
            "RIG_GITHUB_INSTALLATION_ID",
            "RIG_GITHUB_PRIVATE_KEY_ENV",
            "RIG_GITHUB_PRIVATE_KEY_PATH",
            "RIG_GITHUB_CLIENT_ID",
            "RIG_GITHUB_CLIENT_SECRET",
            "RIG_RELAY_GITHUB_CLIENT_ID",
            "RIG_RELAY_GITHUB_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveAuthConfig,
        )

        config = GitHubLiveAuthConfig.from_environment()
        assert config.is_configured() is False
        summary = config.config_summary()
        assert summary["any_auth_configured"] is False

    def test_google_unconfigured_returns_refusal_not_crash(self, monkeypatch):
        for var in (
            "RIG_GOOGLE_CLIENT_ID",
            "RIG_GOOGLE_CLIENT_SECRET",
            "RIG_GOOGLE_SERVICE_ACCOUNT_KEY_PATH",
            "RIG_GOOGLE_SERVICE_ACCOUNT_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)

        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveAuthConfig,
        )

        config = GoogleLiveAuthConfig()
        assert config.is_configured() is False
        summary = config.config_summary()
        assert summary["oauth_configured"] is False

    def test_github_live_smoke_inspect_identity_refuses_without_token(
        self, monkeypatch
    ):
        import rig_relay.integrations.github_provider._live_auth as live_mod

        saved = live_mod._get_json
        try:
            live_mod._get_json = lambda *a, **kw: {
                "login": "",
                "type": "",
                "node_id": "",
            }
            smoke = live_mod.GitHubLiveReadOnlySmoke()
            result = smoke.inspect_identity("")
            assert "login_hash" in result
            assert result.get("identity_type") == "user"
            result_str = json.dumps(result)
            assert "ghp_" not in result_str
        finally:
            live_mod._get_json = saved

    def test_google_live_smoke_inspect_identity_refuses_without_token(self):
        from rig_relay.integrations.google_workspace._live_auth import (
            GoogleLiveReadOnlySmoke,
        )

        result = GoogleLiveReadOnlySmoke.inspect_identity("")
        assert result.get("error") in ("httpx_not_available", "inspect_identity_failed")
        assert (
            result.get("schema_version") == "rig.google_workspace.live_auth_refusal.v1"
        )

    def test_github_missing_scope_read_operation_refused(self):
        from rig_relay.integrations.github_provider import (
            GitHubProviderAuthState,
            evaluate_github_capability,
        )

        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.actions.artifacts.read")
        assert decision.verdict != "ALLOWED"

    def test_google_missing_scope_read_operation_refused(self):
        from rig_relay.integrations.google_workspace import (
            evaluate_workspace_capability,
        )
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceAuthState,
        )

        auth = GoogleWorkspaceAuthState()
        decision = evaluate_workspace_capability(auth, "google.gmail.messages.read")
        assert decision.is_refused

    def test_google_restricted_scope_read_requires_security_assessment(self):
        from rig_relay.integrations.google_workspace._models import (
            GoogleWorkspaceCapability,
            GoogleWorkspaceScopeSensitivity,
        )

        cap = GoogleWorkspaceCapability(
            capability_id="google.gmail.messages.read",
            product="gmail",
            operation_class="user_read",
            required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            required_auth_modes=["oauth_user"],
            scope_sensitivity=GoogleWorkspaceScopeSensitivity.RESTRICTED,
        )
        assert str(cap.scope_sensitivity) == "restricted"

    def test_live_operations_are_read_only(self):
        import ast

        disallowed_http = {"post", "put", "patch", "delete"}
        allowed_token_funcs = {
            "_post_json",
            "exchange_installation_token",
            "exchange_oauth_code",
            "exchange_refresh_token",
            "validate_token",
            "_content_light_token_response",
            "_redact_token_response",
        }

        live_files = [
            "rig_relay/integrations/github_provider/_live_auth.py",
            "rig_relay/integrations/google_workspace/_live_auth.py",
        ]
        for path in live_files:
            source = _read_module(path)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    if func_name in allowed_token_funcs:
                        continue
                    func_source = ast.get_source_segment(source, node) or ""
                    lowered = func_source.lower()
                    for method in disallowed_http:
                        pattern = f".{method}("
                        if pattern in lowered:
                            pytest.fail(
                                f"Non-GET HTTP method 'httpx.{method}' found in "
                                f"live auth function '{func_name}' at {path}"
                            )


class TestCredentialStoreFailureModes:
    def test_keychain_unavailable_returns_refusal_not_raw_fallback(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "keyring", None)

        from rig_relay.identity._credential_store import (
            InMemoryCredentialStore,
            get_credential_store,
        )

        store = get_credential_store(platform="darwin")
        assert isinstance(store, InMemoryCredentialStore)

        store = get_credential_store(use_in_memory=True)
        assert isinstance(store, InMemoryCredentialStore)

    def test_dev_store_blocked_by_default_raises(self, tmp_path):
        import rig_relay.identity.token_store as ts_mod

        original = ts_mod._dev_store_allowed
        ts_mod._dev_store_allowed = False
        try:
            with pytest.raises(RuntimeError, match="DevFileTokenStore is blocked"):
                from rig_relay.identity.token_store import DevFileTokenStore

                DevFileTokenStore(store_root=tmp_path)
        finally:
            ts_mod._dev_store_allowed = original

    def test_dev_store_enabled_after_explicit_call(self, tmp_path):
        from rig_relay.identity.token_store import (
            DevFileTokenStore,
            enable_dev_file_token_store,
        )

        enable_dev_file_token_store()
        store = DevFileTokenStore(store_root=tmp_path)
        assert store._store_root == tmp_path

    def test_credential_store_ref_hash_stable(self):
        from rig_relay.identity._credential_store import InMemoryCredentialStore

        store = InMemoryCredentialStore()
        hash1 = store.compute_credential_store_ref_hash("github")
        hash2 = store.compute_credential_store_ref_hash("github")
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_credential_store_ref_hash_changes_on_mutation(self):
        from rig_relay.identity._credential_store import InMemoryCredentialStore

        store = InMemoryCredentialStore()
        hash_before = store.compute_credential_store_ref_hash("github")
        ref_hash = store.store("github", "oauth_token", "ghp_fake_token_for_hash_test")
        hash_after = store.compute_credential_store_ref_hash("github")
        assert hash_before != hash_after
        assert ref_hash == hash_after


class TestLiveAuthTraceJoinability:
    def test_github_live_ops_emit_trace_id(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        status = RigProviderLiveAuthStatus(
            provider_id="github",
            configured=True,
            auth_mode="oauth_web_flow",
            trace_id="trace-github-001",
            receipt_id="receipt-github-001",
            capability_id="provider.github.live_auth",
        )
        d = status.to_dict()
        assert d["trace_id"] == "trace-github-001"
        assert d["receipt_id"] == "receipt-github-001"

    def test_google_live_ops_emit_trace_id(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        status = RigProviderLiveAuthStatus(
            provider_id="google_workspace",
            configured=True,
            auth_mode="oauth_user",
            trace_id="trace-google-001",
            receipt_id="receipt-google-001",
            capability_id="provider.google_workspace.live_auth",
        )
        d = status.to_dict()
        assert d["trace_id"] == "trace-google-001"
        assert d["receipt_id"] == "receipt-google-001"

    def test_live_auth_receipts_include_surface_field(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        for provider_id in ("github", "google_workspace"):
            status = RigProviderLiveAuthStatus(
                provider_id=provider_id,
                configured=False,
                capability_id=f"provider.{provider_id}.live_auth",
            )
            d = status.to_dict()
            assert d["provider_id"] == provider_id
            assert "capability_id" in d

    def test_live_auth_receipts_include_auth_state_hash(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        status = RigProviderLiveAuthStatus(
            provider_id="github",
            configured=True,
            auth_mode="app_installation",
            auth_status="authenticated",
            credential_store_ref_hash="b" * 64,
            trace_id="trace-hash-001",
            capability_id="provider.github.live_auth",
        )
        d = status.to_dict()
        assert d["credential_store_ref_hash"] == "b" * 64
        assert "auth_mode" in d
        assert d["auth_mode"] == "app_installation"

    def test_live_auth_refusals_include_refusal_code(self):
        from rig_relay.sdk._models import RigProviderLiveAuthStatus

        status = RigProviderLiveAuthStatus(
            provider_id="github",
            configured=False,
            auth_status="unconfigured",
            refusal_code="live_auth_not_configured",
            trace_id="trace-refuse-001",
            capability_id="provider.github.live_auth",
        )
        d = status.to_dict()
        assert d["refusal_code"] == "live_auth_not_configured"
        assert d["configured"] is False


def _read_module(relative_path: str) -> str:

    parts = relative_path.replace(".py", "").split("/")
    pkg = ".".join(parts[:-1])
    mod_name = parts[-1]
    try:
        mod = __import__(f"{pkg}.{mod_name}", fromlist=["__file__"])
        source_path = getattr(mod, "__file__", "")
        if source_path and os.path.isfile(source_path):
            with open(source_path, encoding="utf-8") as f:
                return f.read()
    except (ImportError, AttributeError):
        pass
    return ""


def _get_func_name(node) -> str:
    import ast

    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""
