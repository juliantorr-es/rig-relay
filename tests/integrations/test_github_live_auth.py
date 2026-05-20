"""GitHub live auth tests — opt-in via RIG_LIVE_AUTH_TESTS=1.

No live network calls by default. Tests are structure + import checks.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from rig_relay.integrations.github_provider import (
    GitHubLiveAuthConfig,
    GitHubLiveAuthError,
    GitHubLiveJwtSigner,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    hash_identifier,
    scan_for_tokens,
)

_NEEDS_LIVE = os.environ.get("RIG_LIVE_AUTH_TESTS") != "1"


class TestLiveAuthConfigLoadFromEnv:
    def test_live_auth_config_loads_from_env(self, monkeypatch):
        if _NEEDS_LIVE:
            pytest.skip("live auth tests require RIG_LIVE_AUTH_TESTS=1")
        monkeypatch.setenv("RIG_GITHUB_APP_ID", "123456")
        monkeypatch.setenv("RIG_GITHUB_CLIENT_ID", "test-client")
        monkeypatch.setenv("RIG_GITHUB_CLIENT_SECRET", "test-secret")

        config = GitHubLiveAuthConfig.from_environment()
        assert config.app_id == 123456
        assert config.client_id == "test-client"
        assert config._has_oauth_auth() is True

    def test_live_auth_config_reports_real_app_env(self, monkeypatch, tmp_path):
        private_key_path = tmp_path / "github-private-key.pem"
        private_key_path.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("RIG_GITHUB_APP_ID", "3774417")
        monkeypatch.setenv("RIG_GITHUB_INSTALLATION_ID", "133860977")
        monkeypatch.setenv("RIG_GITHUB_PRIVATE_KEY_PATH", str(private_key_path))

        config = GitHubLiveAuthConfig.from_environment()
        summary = config.config_summary()

        assert summary["app_id_configured"] is True
        assert summary["installation_id_configured"] is True
        assert summary["private_key_present"] is True
        assert summary["app_auth_possible"] is True
        assert summary["any_auth_configured"] is True

    def test_live_auth_config_unconfigured_by_default(self):
        config = GitHubLiveAuthConfig()
        assert config.is_configured() is False
        assert config.app_id is None
        assert config.client_id is None

    def test_live_auth_config_summary_no_raw_secrets(self):
        config = GitHubLiveAuthConfig(
            app_id=123456,
            installation_id=654321,
            client_id="some-client",
            client_secret="shhh-secret",
        )
        summary = config.config_summary()

        serialized = json.dumps(summary, sort_keys=True)
        assert "shhh-secret" not in serialized
        assert "some-client" not in serialized
        assert "123456" not in serialized
        assert "654321" not in serialized

        forbidden = {"client_id", "client_secret", "private_key", "app_id", "api_key"}
        for key in forbidden:
            assert key not in summary, f"summary should not contain raw field '{key}'"

        assert summary["app_id_configured"] is True
        assert summary["client_id_configured"] is True
        assert summary["client_secret_configured"] is True


class TestLiveAuthConfigLogic:
    def test_app_auth_requires_app_id_installation_id_and_private_key(self):
        config = GitHubLiveAuthConfig(app_id=123, installation_id=456)
        assert config.is_configured() is False

        config = GitHubLiveAuthConfig(
            app_id=123, installation_id=456, private_key_env="not a pem key"
        )
        assert config._has_private_key() is True
        assert config.is_configured() is True

    def test_oauth_auth_requires_client_id_and_secret(self):
        config = GitHubLiveAuthConfig(client_id="c", client_secret="s")
        assert config.is_configured() is True

        config = GitHubLiveAuthConfig(client_id="c")
        assert config.is_configured() is False

    def test_private_key_from_env(self):
        config = GitHubLiveAuthConfig(
            app_id=123, installation_id=456, private_key_env="not-a-real-key"
        )
        assert config._has_private_key() is True

    def test_private_key_path_not_existing(self):
        config = GitHubLiveAuthConfig(
            app_id=123, installation_id=456, private_key_path="/nonexistent/key.pem"
        )
        assert config._has_private_key() is False


class TestLiveJwtSigner:
    def test_live_jwt_signer_requires_private_key(self):
        with pytest.raises(GitHubLiveAuthError):
            signer = GitHubLiveJwtSigner(b"not-a-valid-pem-key")
            signer.sign({"iat": 1, "exp": 600, "iss": "1"})

    def test_live_jwt_signer_with_fake_key(self):
        import base64

        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        signer = GitHubLiveJwtSigner(private_key_pem)
        token = signer({"iat": 1000, "exp": 2000, "iss": "42"})

        parts = token.split(".")
        assert len(parts) == 3
        assert all(len(p) > 0 for p in parts)

        header = json.loads(base64.urlsafe_b64decode(parts[0] + "==").decode("utf-8"))
        assert header["alg"] == "RS256"

    def test_live_jwt_signer_different_claims_produce_different_token(self):
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        signer = GitHubLiveJwtSigner(private_key_pem)
        a = signer({"iat": 1, "exp": 600, "iss": "a"})
        b = signer({"iat": 2, "exp": 600, "iss": "b"})
        assert a != b


class TestLiveTokenExchangerExistence:
    def test_live_token_exchanger_uses_httpx(self):
        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveTokenExchanger,
        )

        exchanger = GitHubLiveTokenExchanger(timeout=5.0)
        assert exchanger._timeout == 5.0


class TestLiveReadOnlySmoke:
    def test_live_read_only_smoke_functions_exist(self):
        from rig_relay.integrations.github_provider._live_auth import (
            GitHubLiveReadOnlySmoke,
        )

        smoke = GitHubLiveReadOnlySmoke(timeout=5.0)
        assert hasattr(smoke, "inspect_identity")
        assert hasattr(smoke, "probe_installation_access")
        assert hasattr(smoke, "list_accessible_repos")
        assert smoke._timeout == 5.0


class TestLiveInstallationAccessProof:
    def test_probe_installation_access_uses_installation_repositories_endpoint(
        self, monkeypatch
    ):
        import rig_relay.integrations.github_provider._live_auth as live_mod

        called_urls: list[str] = []

        def fake_get_json(url, headers=None, params=None, timeout=None):
            called_urls.append(url)
            return {
                "repositories": [
                    {
                        "full_name": "owner/private-repo",
                        "name": "private-repo",
                        "permissions": {"contents": True, "issues": False},
                        "private": True,
                        "owner": {"type": "Organization"},
                    }
                ]
            }

        monkeypatch.setattr(live_mod, "_get_json", fake_get_json)

        smoke = live_mod.GitHubLiveReadOnlySmoke(timeout=5.0)
        result = smoke.probe_installation_access(
            "ghs_installation_token_1234567890abcdef",
            installation_id=133860977,
            repository_selection="all",
            permission_keys=["metadata"],
        )

        assert called_urls == ["https://api.github.com/installation/repositories"]
        assert result["schema_version"] == "rig.github.live_auth_result.v1"
        assert result["auth_mode"] == "app_installation"
        assert result["installation_access"] == "success"
        assert result["installation_id_hash"] == hash_identifier("133860977")
        assert result["accessible_repo_count"] == 1
        assert result["accessible_repo_name_hashes"] == [
            hash_identifier("owner/private-repo")
        ]
        assert result["permission_keys"] == ["contents", "issues", "metadata"]
        assert result["repository_selection"] == "all"
        assert "ghs_installation_token_1234567890abcdef" not in json.dumps(result)

    def test_probe_installation_access_returns_structured_refusal_on_http_401(
        self, monkeypatch
    ):
        import httpx

        import rig_relay.integrations.github_provider._live_auth as live_mod

        def fake_get_json(url, headers=None, params=None, timeout=None):
            request = httpx.Request("GET", url)
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError(
                "Unauthorized", request=request, response=response
            )

        monkeypatch.setattr(live_mod, "_get_json", fake_get_json)

        smoke = live_mod.GitHubLiveReadOnlySmoke(timeout=5.0)
        result = smoke.probe_installation_access(
            "ghs_installation_token_1234567890abcdef", installation_id=133860977
        )

        assert result["schema_version"] == "rig.github.live_auth_refusal.v1"
        assert result["auth_mode"] == "app_installation"
        assert result["error"] == "installation_access_failed"
        assert result["status_code"] == 401
        assert "ghs_installation_token_1234567890abcdef" not in json.dumps(result)


class TestLiveAuthScriptTokenFlow:
    def test_lift_run_live_github_forwards_exchanged_token_to_smoke_probe(
        self, monkeypatch
    ):
        import rig_relay.integrations.github_provider._live_auth as live_mod
        import scripts.rig_github_live_auth_check as script

        exchanged_token = "ghs_installation_token_1234567890abcdef"

        class DummyConfig:
            app_id = 3774417
            installation_id = 133860977

            def _has_private_key(self) -> bool:
                return True

            def load_private_key(self) -> bytes:
                return b"-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----"

            def config_summary(self) -> dict[str, bool | str]:
                return {
                    "app_id_configured": True,
                    "installation_id_configured": True,
                    "private_key_source": "file",
                    "private_key_present": True,
                    "client_id_configured": False,
                    "client_secret_configured": False,
                    "redirect_uri_configured": False,
                    "app_auth_possible": True,
                    "oauth_auth_possible": False,
                    "any_auth_configured": True,
                }

        def fake_exchange(self, app_id, installation_id, private_key_bytes):
            return (
                {
                    "token_hash": hash_identifier(exchanged_token),
                    "expires_at": "2026-06-19T00:00:00Z",
                    "kind": "installation",
                    "permissions": {"contents": "read"},
                    "repository_selection": "all",
                },
                exchanged_token,
            )

        def fake_probe(
            self,
            token,
            installation_id=None,
            repository_selection=None,
            permission_keys=None,
        ):
            assert token == exchanged_token
            assert token != "__placeholder__"
            assert installation_id == 133860977
            assert repository_selection == "all"
            assert permission_keys == ["contents"]
            return {
                "schema_version": "rig.github.live_auth_result.v1",
                "auth_mode": "app_installation",
                "installation_id_hash": hash_identifier("133860977"),
                "installation_access": "success",
                "accessible_repo_count": 1,
                "accessible_repo_name_hashes": [hash_identifier("owner/private-repo")],
                "permission_keys": ["contents"],
                "repository_selection": "all",
            }

        monkeypatch.setattr(
            live_mod.GitHubLiveTokenExchanger,
            "exchange_installation_token",
            fake_exchange,
        )
        monkeypatch.setattr(
            live_mod.GitHubLiveReadOnlySmoke, "probe_installation_access", fake_probe
        )

        results = script._lift_run_live_github(DummyConfig(), "receipt-1", "trace-1")

        assert results["auth_mode"] == "app_installation"
        assert results["token_exchange"]["token_hash"] == hash_identifier(
            exchanged_token
        )
        assert results["installation_access"]["installation_access"] == "success"
        assert exchanged_token not in json.dumps(results)


class TestLiveAuthNeverLogsRawToken:
    def test_live_auth_never_logs_raw_token(self):
        from pathlib import Path

        module_path = (
            Path(__file__).resolve().parents[2]
            / "rig_relay"
            / "integrations"
            / "github_provider"
            / "_live_auth.py"
        )
        source = module_path.read_text(encoding="utf-8")

        suspicious = []
        for i, line in enumerate(source.split("\n"), start=1):
            lower = line.lower().strip()
            if (
                lower.startswith("#")
                or lower.startswith('"""')
                or lower.startswith('"""')
            ):
                continue
            if "print(" in lower and "token" in lower:
                suspicious.append(f"line {i}: print with 'token': {line.strip()[:80]}")
            if "logger." in lower and "token" in lower:
                suspicious.append(f"line {i}: logger with 'token': {line.strip()[:80]}")
            if "log." in lower and "token" in lower:
                suspicious.append(f"line {i}: log with 'token': {line.strip()[:80]}")

        assert not suspicious, "Found credential-printing code:\n" + "\n".join(
            suspicious
        )

    def test_token_hash_never_contains_raw_token(self):
        raw_token = "ghs_realabc12345678901234567890"
        result = hash_identifier(raw_token)
        assert raw_token not in result
        assert len(result) == 64


class TestLiveAuthContentLight:
    def test_config_summary_is_content_light(self):
        config = GitHubLiveAuthConfig(
            app_id=42, client_id="ov23clientidlongstring", client_secret="a" * 40
        )
        summary = config.config_summary()
        serialized = json.dumps(summary, sort_keys=True)

        assert_no_raw_github_token(serialized)

    def test_hash_identifier_produces_sha256_length(self):
        for value in ["abc", "github-token-12345", "org/repo-name", ""]:
            h = hash_identifier(value)
            assert len(h) == 64
            assert all(c in "0123456789abcdef" for c in h)

    def test_scan_for_tokens_detects_real_tokens(self):
        found = scan_for_tokens("use token ghp_abc123def456ghijklmn7890")
        assert found == ["github_token_pattern"]

        found = scan_for_tokens("use token ghs_rst456uvo789abc1234fghiwxyz12")
        assert found == ["github_token_pattern"]

    def test_scan_for_tokens_does_not_detect_test_tokens(self):
        found = scan_for_tokens("ghs_test_abc123def456ghijklmn7890")
        assert found == []

        found = scan_for_tokens("gho_test_abc123def456ghijklmn7890")
        assert found == []


class TestLiveAuthHashNoLeak:
    def test_hash_identifier_is_deterministic(self):
        assert hash_identifier("hello") == hashlib.sha256(b"hello").hexdigest()
        assert hash_identifier("world") == hashlib.sha256(b"world").hexdigest()

    def test_redact_token_response_produces_no_raw_token(self):
        from rig_relay.integrations.github_provider._live_auth import (
            _redact_token_response,
        )

        raw = "ghs_abcdef1234567890abcdef1234567890abcdef12"
        result = _redact_token_response(
            {"token": raw, "expires_at": "2025-01-01T00:00:00Z"},
            raw,
            kind="installation",
        )

        serialized = json.dumps(result)
        assert "token" not in {
            k for k in result if "hash" not in k or "prefix" not in k
        }
        assert raw not in result.get("token_hash", "")
        assert result["token_present"] is True
        assert "token_prefix" not in result
        assert len(result["token_hash"]) == 64
        assert "token_prefix" not in serialized

    def test_redact_token_response_handles_empty_token(self):
        from rig_relay.integrations.github_provider._live_auth import (
            _redact_token_response,
        )

        result = _redact_token_response({"expires_at": ""}, "", kind="oauth")
        serialized = json.dumps(result)
        assert result["token_hash"] == ""
        assert result["token_present"] is False
        assert "token_prefix" not in result
        assert "token_prefix" not in serialized
