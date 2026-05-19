from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from rig_relay.identity._credential_store import (
    InMemoryCredentialStore,
    KeychainBackedCredentialStore,
    NoOpCredentialStore,
    _sha256,
    assert_no_secrets_in_json,
    scan_raw_json_for_secrets,
)


class TestInMemoryCredentialStore:
    def test_in_memory_store_roundtrip(self):
        store = InMemoryCredentialStore()
        ref_hash = store.store("github", "oauth_token", "ghp_test123")
        assert ref_hash

        retrieved = store.retrieve("github", "oauth_token")
        assert retrieved == "ghp_test123"

        assert store.exists("github", "oauth_token")

    def test_in_memory_store_never_persists_to_disk(self, tmp_path):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")

        json_files = list(Path(tmp_path).glob("*.json"))
        assert not json_files

    def test_credential_metadata_is_content_light(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")

        metas = store.list_metadata("github")
        assert len(metas) == 1
        meta = metas[0]
        assert meta.provider == "github"
        assert meta.credential_kind == "oauth_token"
        assert meta.credential_hash
        assert meta.status == "active"

        meta_dict = meta.to_dict()
        assert "access_token" not in meta_dict
        assert "refresh_token" not in meta_dict
        assert "credential" not in meta_dict
        assert "token" not in meta_dict
        assert "secret" not in meta_dict

    def test_metadata_credential_hash_is_sha256(self):
        store = InMemoryCredentialStore()
        store.store("google", "oauth_token", "ya29.test.token")

        metas = store.list_metadata("google")
        assert len(metas) == 1
        cred_hash = metas[0].credential_hash
        expected = hashlib.sha256(b"ya29.test.token").hexdigest()
        assert cred_hash == expected

    def test_metadata_no_raw_credential_in_json(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_raw_secret_value")

        meta = store.list_metadata("github")[0]
        d = meta.to_dict()

        cred_hash = d.get("credential_hash") or ""
        assert "ghp_raw_secret_value" not in cred_hash
        assert cred_hash != "ghp_raw_secret_value"

    def test_credential_store_ref_hash_stable_for_same_state(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")
        store.store("github", "identity", "ghp_id456")

        h1 = store.compute_credential_store_ref_hash("github")
        h2 = store.compute_credential_store_ref_hash("github")
        assert h1 == h2

    def test_credential_store_ref_hash_changes_on_new_credential(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")
        h1 = store.compute_credential_store_ref_hash("github")

        store.store("github", "identity", "ghp_id456")
        h2 = store.compute_credential_store_ref_hash("github")

        assert h1 != h2

    def test_delete_removes_credential(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")
        assert store.exists("github", "oauth_token")

        deleted = store.delete("github", "oauth_token")
        assert deleted
        assert not store.exists("github", "oauth_token")
        assert store.retrieve("github", "oauth_token") is None

    def test_delete_nonexistent_returns_false(self):
        store = InMemoryCredentialStore()
        assert not store.delete("github", "nonexistent")

    def test_store_rejects_empty_credential(self):
        store = InMemoryCredentialStore()
        with pytest.raises(ValueError, match="Empty credential"):
            store.store("github", "oauth_token", "")

    def test_list_metadata_no_raw_values(self):
        store = InMemoryCredentialStore()
        store.store("github", "oauth_token", "ghp_raw_secret_12345")

        metas = store.list_metadata("github")
        for meta in metas:
            d = meta.to_dict()
            assert "ghp_raw_secret_12345" not in str(d)

    def test_list_metadata_empty_for_unknown_provider(self):
        store = InMemoryCredentialStore()
        metas = store.list_metadata("unknown")
        assert metas == []

    def test_compute_ref_hash_empty_provider(self):
        store = InMemoryCredentialStore()
        h = store.compute_credential_store_ref_hash("empty")
        assert h == _sha256("")


class TestNoOpCredentialStore:
    def test_noop_store_always_returns_none(self):
        store = NoOpCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")

        assert store.retrieve("github", "oauth_token") is None
        assert not store.exists("github", "oauth_token")
        assert not store.delete("github", "oauth_token")

    def test_noop_store_list_metadata_empty(self):
        store = NoOpCredentialStore()
        store.store("github", "oauth_token", "ghp_test123")
        assert store.list_metadata("github") == []

    def test_noop_compute_ref_hash(self):
        store = NoOpCredentialStore()
        h = store.compute_credential_store_ref_hash("any")
        assert h == _sha256("")


class TestKeychainBackedCredentialStore:
    @staticmethod
    def _safe_store(store: KeychainBackedCredentialStore, *args, **kwargs) -> None:
        if not store._available:
            pytest.skip("keychain store not available")
        try:
            store.store(*args, **kwargs)
        except RuntimeError as e:
            if "Keychain" in str(e):
                pytest.skip(f"keychain write rejected by OS: {e}")
            raise

    def test_keychain_store_metadata_persists_content_light_only(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(store, "github", "oauth_token", "ghp_test123")

        meta_file = tmp_path / "credential_metadata.json"
        assert meta_file.is_file()
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        assert raw["schema_version"] == "rig.relay.credential_store.metadata.v1"
        for entry in raw["entries"]:
            assert "access_token" not in entry
            assert "refresh_token" not in entry
            assert "credential" not in entry
            assert "token" not in entry

    def test_keychain_store_never_puts_raw_credential_in_metadata_json(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(store, "github", "oauth_token", "ghp_super_secret_value")

        meta_file = tmp_path / "credential_metadata.json"
        content = meta_file.read_text(encoding="utf-8")
        assert "ghp_super_secret_value" not in content

        raw = json.loads(content)
        for entry in raw["entries"]:
            for v in entry.values():
                if isinstance(v, str):
                    assert v != "ghp_super_secret_value"

    def test_keychain_store_roundtrip(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(store, "github", "oauth_token", "ghp_test_value")

        assert store.exists("github", "oauth_token")
        retrieved = store.retrieve("github", "oauth_token")
        assert retrieved == "ghp_test_value"

    def test_keychain_store_rejects_empty_credential(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        if not store._available:
            pytest.skip("keychain store not available")
        with pytest.raises(ValueError, match="Empty credential"):
            store.store("github", "oauth_token", "")

    def test_keychain_store_delete(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(store, "github", "oauth_token", "ghp_test_value")
        assert store.exists("github", "oauth_token")

        assert store.delete("github", "oauth_token")
        assert not store.exists("github", "oauth_token")
        assert store.retrieve("github", "oauth_token") is None

    def test_keychain_store_list_metadata(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(store, "github", "oauth_token", "ghp_test123")
        self._safe_store(store, "google", "oauth_token", "ya29.test")

        github_metas = store.list_metadata("github")
        assert len(github_metas) == 1
        assert github_metas[0].provider == "github"

        google_metas = store.list_metadata("google")
        assert len(google_metas) == 1
        assert google_metas[0].provider == "google"

    def test_keychain_store_metadata_expires_at(self, tmp_path):
        store = KeychainBackedCredentialStore(store_root=tmp_path)
        self._safe_store(
            store,
            "github",
            "oauth_token",
            "ghp_test123",
            metadata={"expires_at": "2027-01-01T00:00:00+00:00", "status": "active"},
        )

        metas = store.list_metadata("github")
        assert metas[0].expires_at == "2027-01-01T00:00:00+00:00"
        assert metas[0].status == "active"


class TestKeychainConstructorClean:
    def test_keychain_constructor_does_not_do_redundant_imports(
        self, tmp_path, monkeypatch
    ):
        import_count = 0

        class FakeKeyring:
            @staticmethod
            def set_password(service, account, password):
                pass

            @staticmethod
            def delete_password(service, account):
                pass

        def _fake_import(name, *args, **kwargs):
            nonlocal import_count
            if name == "keyring":
                import_count += 1
                return FakeKeyring
            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        assert import_count == 1
        assert store._available

    def test_keychain_probe_sets_available_correctly_when_working(
        self, tmp_path, monkeypatch
    ):
        class FakeKeyring:
            @staticmethod
            def set_password(service, account, password):
                pass

            @staticmethod
            def delete_password(service, account):
                pass

        monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        assert store._available
        assert store._keyring is not None

    def test_keychain_probe_sets_available_false_when_probe_fails(
        self, tmp_path, monkeypatch
    ):
        class BrokenKeyring:
            @staticmethod
            def set_password(service, account, password):
                raise OSError("keychain unavailable")

            @staticmethod
            def delete_password(service, account):
                pass

        monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        assert not store._available
        assert store._keyring is None

    def test_keychain_import_failure_sets_available_false(self, tmp_path, monkeypatch):
        def _fake_import(name, *args, **kwargs):
            if name == "keyring":
                raise ImportError("no keyring")
            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

        store = KeychainBackedCredentialStore(store_root=tmp_path)
        assert not store._available
        assert store._keyring is None


class TestDevFileTokenStoreGate:
    def test_dev_file_token_store_blocked_by_default(self, tmp_path, monkeypatch):
        import rig_relay.identity.token_store as ts_mod
        from rig_relay.identity.token_store import DevFileTokenStore

        monkeypatch.setattr(ts_mod, "_dev_store_allowed", False)
        with pytest.raises(RuntimeError, match="DevFileTokenStore is blocked"):
            DevFileTokenStore(store_root=tmp_path)

    def test_dev_file_token_store_allowed_after_enable(self, tmp_path, monkeypatch):
        import rig_relay.identity.token_store as ts_mod
        from rig_relay.identity.token_store import (
            DevFileTokenStore,
            enable_dev_file_token_store,
        )

        monkeypatch.setattr(ts_mod, "_dev_store_allowed", False)
        enable_dev_file_token_store()
        store = DevFileTokenStore(store_root=tmp_path)
        assert store is not None

    def test_is_dev_store_enabled_defaults_false(self, monkeypatch):
        import rig_relay.identity.token_store as ts_mod

        monkeypatch.setattr(ts_mod, "_dev_store_allowed", False)
        assert not ts_mod.is_dev_store_enabled()


class TestSecretScanner:
    def test_scan_raw_json_for_secrets_finds_github_token(self):
        data = {
            "token_bundle": {"access_token": "ghp_abc123def456ghi789jkl012mno345pqr"}
        }
        findings = scan_raw_json_for_secrets(data)
        assert findings

    def test_scan_raw_json_for_secrets_finds_google_token(self):
        data = {"token_bundle": {"access_token": "ya29.a0AfH6SMBx1234567890abcdef"}}
        findings = scan_raw_json_for_secrets(data)
        assert findings

    def test_scan_raw_json_for_secrets_finds_pem(self):
        data = {
            "config": {
                "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC"
            }
        }
        findings = scan_raw_json_for_secrets(data)
        assert findings

    def test_scan_raw_json_for_secrets_returns_field_paths_not_values(self):
        data = {
            "token_bundle": {"access_token": "ghp_abc123def456ghi789jkl012mno345pqr"}
        }
        findings = scan_raw_json_for_secrets(data)
        for path in findings:
            assert "ghp_" not in path

    def test_assert_no_secrets_in_json_raises_on_find(self):
        data = {
            "token_bundle": {"access_token": "ghp_abc123def456ghi789jkl012mno345pqr"}
        }
        with pytest.raises(ValueError, match="Secrets detected"):
            assert_no_secrets_in_json(data, context="test_data")

    def test_assert_no_secrets_in_json_passes_on_clean_data(self):
        data = {
            "schema_version": "v1",
            "entries": [
                {"provider": "github", "credential_hash": "abc123", "status": "active"}
            ],
        }
        assert_no_secrets_in_json(data, context="clean_data")
