"""Live secret boundary adversarial tests.

Tests that credential store metadata and dev token store boundaries
never allow raw tokens, secrets, or private keys to be stored in JSON.
"""

from __future__ import annotations

import json
import sys

import pytest

from rig_relay.identity._credential_store import (
    KeychainBackedCredentialStore,
    assert_no_secrets_in_json,
    scan_raw_json_for_secrets,
)
from rig_relay.identity.token_store import (
    DevFileTokenStore,
    enable_dev_file_token_store,
)

enable_dev_file_token_store()


class TestKeychainMetadataNeverContainsRawToken:
    def test_keychain_metadata_never_contains_raw_token(self, tmp_path, monkeypatch):
        class FakeKeyring:
            @staticmethod
            def set_password(service, account, password):
                pass

            @staticmethod
            def delete_password(service, account):
                pass

            @staticmethod
            def get_password(service, account):
                return "ghp_raw_test_token"

        monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        assert store._available

        store.store("github", "oauth_token", "ghp_raw_test_token")

        meta_file = tmp_path / "credential_metadata.json"
        content = meta_file.read_text(encoding="utf-8")
        assert "ghp_raw_test_token" not in content
        assert "Ya29" not in content


class TestDevStoreBlockedByDefault:
    def test_dev_store_blocked_by_default_in_tests(self, tmp_path, monkeypatch):
        import rig_relay.identity.token_store as ts_mod

        original = ts_mod._dev_store_allowed
        ts_mod._dev_store_allowed = False
        try:
            with pytest.raises(RuntimeError, match="DevFileTokenStore is blocked"):
                DevFileTokenStore(store_root=tmp_path)
        finally:
            ts_mod._dev_store_allowed = original


class TestSecretBoundaryAssertNoSecrets:
    def test_raw_access_token_in_metadata_rejected(self):
        data = {
            "schema_version": "v1",
            "entries": [
                {
                    "provider": "github",
                    "credential_hash": "abc",
                    "status": "active",
                    "access_token": "ghp_abcdef1234567890abcdef1234567890123456",
                }
            ],
        }
        with pytest.raises(ValueError, match="Secrets detected"):
            assert_no_secrets_in_json(data, context="metadata")

    def test_raw_refresh_token_in_metadata_rejected(self):
        data = {
            "schema_version": "v1",
            "entries": [
                {
                    "provider": "google",
                    "credential_hash": "abc",
                    "status": "active",
                    "refresh_token": "ya29.a0AfH6SMBx1234567890abcdef1234567890abcdef",
                }
            ],
        }
        with pytest.raises(ValueError, match="Secrets detected"):
            assert_no_secrets_in_json(data, context="metadata")

    def test_raw_private_key_in_metadata_rejected(self):
        data = {
            "schema_version": "v1",
            "config": {
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3"
            },
        }
        with pytest.raises(ValueError, match="Secrets detected"):
            assert_no_secrets_in_json(data, context="metadata")

    def test_scan_secrets_paths_never_leak_values(self):
        data = {
            "nested": {
                "deep": {"token": "ghp_this_is_a_secret_token_value_do_not_leak"}
            }
        }
        findings = scan_raw_json_for_secrets(data)
        result_str = json.dumps(findings)
        assert "ghp_this_is_a_secret_token_value_do_not_leak" not in result_str
        for f in findings:
            assert f == "nested.deep.token"
