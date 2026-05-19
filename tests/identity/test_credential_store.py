from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rig_relay.identity._credential_store import (
    InMemoryCredentialStore,
    KeychainBackedCredentialStore,
    NoOpCredentialStore,
    _sha256,
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
