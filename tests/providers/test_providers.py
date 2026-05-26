"""Tests for the provider onboarding package."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.providers import (
    PROVIDER_REGISTRY,
    Provider,
    check_provider_status,
    provider_health_check,
    provider_onboarding_remove_key,
    provider_onboarding_save_key,
    provider_status,
)
from rig_relay.providers.key_store import (
    DevFileProviderKeyStore,
    EnvProviderKeyStore,
    MacKeychainProviderKeyStore,
)
from rig_relay.providers.models import KeySource
from rig_relay.providers.registry import is_supported_provider


class TestRegistry:
    def test_contains_all_providers(self):
        providers = {p.provider for p in PROVIDER_REGISTRY}
        assert providers == {
            Provider.OPENAI,
            Provider.ANTHROPIC,
            Provider.GOOGLE,
            Provider.OPENROUTER,
            Provider.DEEPSEEK,
            Provider.LOCAL_INFERENCE,
        }

    def test_env_var_names_correct(self):
        env_map = {p.provider: p.env_var for p in PROVIDER_REGISTRY}
        assert env_map[Provider.OPENAI] == "OPENAI_API_KEY"
        assert env_map[Provider.ANTHROPIC] == "ANTHROPIC_API_KEY"
        assert env_map[Provider.GOOGLE] == "GEMINI_API_KEY"
        assert env_map[Provider.OPENROUTER] == "OPENROUTER_API_KEY"
        assert env_map[Provider.DEEPSEEK] == "DEEPSEEK_API_KEY"

    def test_google_alt_env_var(self):
        google_info = next(
            p for p in PROVIDER_REGISTRY if p.provider == Provider.GOOGLE
        )
        assert google_info.alt_env_var == "GOOGLE_API_KEY"

    def test_is_supported_provider(self):
        assert is_supported_provider("openai") is True
        assert is_supported_provider("anthropic") is True
        assert is_supported_provider("google") is True
        assert is_supported_provider("openrouter") is True
        assert is_supported_provider("deepseek") is True
        assert is_supported_provider("unknown") is False


class TestKeyFingerprint:
    def test_fingerprint_deterministic(self):
        from rig_relay.providers.key_store import _fingerprint_key

        fp1 = _fingerprint_key("sk-test-key-12345")
        fp2 = _fingerprint_key("sk-test-key-12345")
        assert fp1 == fp2
        assert fp1.startswith("sha256:")

    def test_fingerprint_does_not_expose_raw_key(self):
        from rig_relay.providers.key_store import _fingerprint_key

        fp = _fingerprint_key("sk-test-secret-key-99999")
        assert "sk-test" not in fp
        assert "secret" not in fp

    def test_different_keys_different_fingerprints(self):
        from rig_relay.providers.key_store import _fingerprint_key

        fp1 = _fingerprint_key("key-a")
        fp2 = _fingerprint_key("key-b")
        assert fp1 != fp2


class TestEnvProviderKeyStore:
    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")
        store = EnvProviderKeyStore()
        key = store.get_key(Provider.OPENAI)
        assert key == "sk-test-openai-key"

    def test_google_prefers_gemini(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        store = EnvProviderKeyStore()
        key = store.get_key(Provider.GOOGLE)
        assert key == "gemini-key"

    def test_google_fallsback_to_google_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        store = EnvProviderKeyStore()
        key = store.get_key(Provider.GOOGLE)
        assert key == "google-key"

    def test_google_warns_if_both_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        store = EnvProviderKeyStore()
        warnings = store.get_google_warnings()
        assert len(warnings) == 1
        assert "GEMINI_API_KEY takes precedence" in warnings[0]

    def test_no_warnings_if_only_one_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        store = EnvProviderKeyStore()
        warnings = store.get_google_warnings()
        assert len(warnings) == 0

    def test_set_key_raises(self):
        store = EnvProviderKeyStore()
        with pytest.raises(RuntimeError):
            store.set_key(Provider.OPENAI, "key")

    def test_remove_key_returns_false(self):
        store = EnvProviderKeyStore()
        assert store.remove_key(Provider.OPENAI) is False

    def test_has_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-key")
        store = EnvProviderKeyStore()
        assert store.has_key(Provider.ANTHROPIC) is True
        assert store.has_key(Provider.OPENAI) is False

    def test_fingerprint(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fp")
        store = EnvProviderKeyStore()
        fp = store.fingerprint(Provider.OPENAI)
        assert fp.startswith("sha256:")

    def test_missing_key_fingerprint(self):
        store = EnvProviderKeyStore()
        assert store.fingerprint(Provider.OPENAI) == ""


class TestDevFileProviderKeyStore:
    def test_save_and_read_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        store.set_key(Provider.OPENAI, "sk-dev-key")
        assert store.get_key(Provider.OPENAI) == "sk-dev-key"
        assert store.has_key(Provider.OPENAI) is True

    def test_remove_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        store.set_key(Provider.OPENAI, "sk-dev-key")
        assert store.remove_key(Provider.OPENAI) is True
        assert store.has_key(Provider.OPENAI) is False

    def test_remove_nonexistent_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        assert store.remove_key(Provider.OPENAI) is False

    def test_not_exposed_in_repo(self, tmp_path: Path):
        """Verify key file goes to tmp_path, not real home dir."""
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        store.set_key(Provider.ANTHROPIC, "sk-ant-key")
        key_file = tmp_path / "anthropic.key"
        assert key_file.is_file()
        content = key_file.read_text(encoding="utf-8").strip()
        assert content == "sk-ant-key"
        assert content.startswith("sk-ant")

    def test_fingerprint(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        store.set_key(Provider.OPENAI, "sk-fp-key")
        fp = store.fingerprint(Provider.OPENAI)
        assert fp.startswith("sha256:")

    def test_missing_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        assert store.get_key(Provider.OPENAI) is None
        assert store.key_source(Provider.OPENAI) == KeySource.MISSING


class TestProviderStatus:
    def test_status_no_raw_keys(self, monkeypatch: pytest.MonkeyPatch):
        """provider_status returns no raw keys in response."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-raw-key-should-not-appear")
        result = provider_status(key_store=EnvProviderKeyStore())
        for p in result.get("providers", []):
            assert "api_key" not in p
            assert "sk-" not in str(p)

    def test_all_providers_listed(self):
        result = provider_status()
        providers = result.get("providers", [])
        assert len(providers) >= 6  # 5 cloud + 1 local_inference

    def test_configured_count(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        result = provider_status(key_store=EnvProviderKeyStore())
        assert result.get("configured", 0) == 2

    def test_env_detected(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        result = provider_status(key_store=EnvProviderKeyStore())
        deepseek = next(
            p for p in result.get("providers", []) if p["provider"] == "deepseek"
        )
        assert deepseek["configured"] is True
        assert deepseek["key_source"] == "env"


class TestSaveKey:
    def test_save_key_returns_no_raw_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        result = provider_onboarding_save_key("openai", "sk-raw-key", key_store=store)
        # Response must not contain raw key
        assert "sk-raw-key" not in str(result)
        assert result.get("status") == "completed"
        assert result.get("key_fingerprint", "").startswith("sha256:")

    def test_save_key_stores_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        provider_onboarding_save_key("anthropic", "sk-ant-key", key_store=store)
        assert store.get_key(Provider.ANTHROPIC) == "sk-ant-key"

    def test_unsupported_provider(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        result = provider_onboarding_save_key("unknown", "key", key_store=store)
        assert result.get("status") == "failed"

    def test_remove_key_removes(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        store.set_key(Provider.OPENAI, "sk-key")
        result = provider_onboarding_remove_key("openai", key_store=store)
        assert result.get("status") == "completed"
        assert store.has_key(Provider.OPENAI) is False

    def test_remove_nonexistent_key(self, tmp_path: Path):
        store = DevFileProviderKeyStore(providers_dir=tmp_path)
        result = provider_onboarding_remove_key("openai", key_store=store)
        assert result.get("status") == "completed"


class TestHealthCheck:
    def test_no_network_by_default(self, monkeypatch: pytest.MonkeyPatch):
        """health_check with network_allowed=False does not call network."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        result = provider_health_check(network_allowed=False)
        providers = result.get("providers", [])
        openai = next(p for p in providers if p["provider"] == "openai")
        assert openai["status"] == "skipped"

    def test_no_network_skips_missing(self):
        result = provider_health_check(network_allowed=False)
        providers = result.get("providers", [])
        for p in providers:
            if not p.get("configured"):
                assert p["status"] == "skipped"

    def test_check_provider_status_no_network_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """network_allowed=False returns skipped, never valid."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        status = check_provider_status(
            Provider.OPENAI, EnvProviderKeyStore(), network_allowed=False
        )
        assert status.status == "skipped"
        assert status.configured is True
        assert status.key_fingerprint.startswith("sha256:")

    def test_check_provider_status_missing_key(self):
        status = check_provider_status(
            Provider.OPENAI, EnvProviderKeyStore(), network_allowed=False
        )
        assert status.status == "skipped"
        assert status.configured is False


class TestNetworkCheckTrust:
    def test_network_allowed_returns_unknown_for_unimplemented(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """network_allowed=True with no implementation must not return valid."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        status = check_provider_status(
            Provider.OPENAI, EnvProviderKeyStore(), network_allowed=True
        )
        assert status.status == "unknown"
        assert "network_check_not_implemented" in (status.warnings or [])

    def test_network_allowed_returns_skipped_if_no_key(self):
        """Without key, network_allowed=True still returns skipped."""
        status = check_provider_status(
            Provider.OPENAI, EnvProviderKeyStore(), network_allowed=True
        )
        assert status.status == "skipped"
        assert status.configured is False

    def test_network_allowed_false_returns_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """network_allowed=False returns skipped for configured providers."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        status = check_provider_status(
            Provider.OPENAI, EnvProviderKeyStore(), network_allowed=False
        )
        assert status.status == "skipped"
        assert status.configured is True


class TestDevFileProviderKeyStoreStateRoot:
    """DevFileProviderKeyStore default uses provider_state_root()."""

    def test_default_uses_provider_state_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default providers_dir comes from provider_state_root()."""
        from rig_relay.identity.state_paths import provider_state_root

        store = DevFileProviderKeyStore()
        expected = provider_state_root()
        assert store._providers_dir == expected

    def test_explicit_providers_dir_overrides_default(self, tmp_path: Path) -> None:
        """Explicit providers_dir takes precedence over default."""
        custom = tmp_path / "custom" / "providers"
        store = DevFileProviderKeyStore(providers_dir=custom)
        assert store._providers_dir == custom

    def test_state_root_determines_providers_dir(self, tmp_path: Path) -> None:
        """Passing a state root should derive the providers directory."""
        from rig_relay.identity.state_paths import provider_state_root

        state_root = tmp_path / "custom-state"
        expected = provider_state_root(root=state_root)
        store = DevFileProviderKeyStore(providers_dir=expected)
        assert store._providers_dir == expected
        # Verify keys written to this directory
        store.set_key(Provider.OPENAI, "sk-state-root-test")
        assert (expected / "openai.key").is_file()


class TestMacKeychainProviderKeyStore:
    def test_unavailable_when_keyring_missing(self, monkeypatch: pytest.MonkeyPatch):
        """If keyring cannot be imported, store is unavailable."""
        monkeypatch.setattr(
            "builtins.__import__",
            lambda name, *a, **kw: (
                (_ for _ in ()).throw(ImportError())
                if name == "keyring"
                else __import__(name, *a, **kw)
            ),
        )
        store = MacKeychainProviderKeyStore()
        assert store.has_key(Provider.OPENAI) is False
        assert store.key_source(Provider.OPENAI) == KeySource.MISSING
        with pytest.raises(RuntimeError, match="Keychain backend unavailable"):
            store.set_key(Provider.OPENAI, "key")

    def test_no_raw_key_exposed(self, monkeypatch: pytest.MonkeyPatch):
        """Fingerprint and status should not expose raw key."""
        monkeypatch.setattr(
            "builtins.__import__",
            lambda name, *a, **kw: (
                (_ for _ in ()).throw(ImportError())
                if name == "keyring"
                else __import__(name, *a, **kw)
            ),
        )
        store = MacKeychainProviderKeyStore()
        fp = store.fingerprint(Provider.OPENAI)
        assert fp == ""
        assert store.key_source(Provider.OPENAI) == KeySource.MISSING

    def test_get_key_store_factory(self):
        """get_key_store(KEYCHAIN) returns MacKeychainProviderKeyStore."""
        from rig_relay.providers.key_store import get_key_store

        store = get_key_store(KeySource.KEYCHAIN)
        from rig_relay.providers.key_store import MacKeychainProviderKeyStore

        assert isinstance(store, MacKeychainProviderKeyStore)


class TestMacKeychainWithMockedKeyring:
    """MacKeychainProviderKeyStore with a working mocked keyring backend."""

    @pytest.fixture
    def mock_keyring(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
        """Create a fake in-memory keyring and inject it."""
        storage: dict[str, dict[str, str]] = {}

        class FakeKeyring:
            @staticmethod
            def set_password(service: str, username: str, password: str) -> None:
                storage.setdefault(service, {})[username] = password

            @staticmethod
            def get_password(service: str, username: str) -> str | None:
                return storage.get(service, {}).get(username)

            @staticmethod
            def delete_password(service: str, username: str) -> None:
                if service in storage and username in storage[service]:
                    del storage[service][username]
                else:
                    msg = f"Password not found for {service}:{username}"
                    raise Exception(msg)

        monkeypatch.setattr(
            "rig_relay.providers.key_store.MacKeychainProviderKeyStore.__init__",
            lambda self: (
                setattr(self, "_available", True)
                or setattr(self, "_keyring", FakeKeyring())
                or None
            ),
        )
        return storage  # type: ignore[return-value]

    def test_set_and_get_key(self, tmp_path: Path, mock_keyring) -> None:
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.OPENAI, "sk-keychain-test-key")
        assert store.get_key(Provider.OPENAI) == "sk-keychain-test-key"

    def test_remove_key(self, tmp_path: Path, mock_keyring) -> None:
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.ANTHROPIC, "sk-ant-keychain")
        assert store.remove_key(Provider.ANTHROPIC) is True
        assert store.get_key(Provider.ANTHROPIC) is None

    def test_has_key(self, tmp_path: Path, mock_keyring) -> None:
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.OPENAI, "sk-has-key")
        assert store.has_key(Provider.OPENAI) is True
        assert store.has_key(Provider.DEEPSEEK) is False

    def test_key_source(self, tmp_path: Path, mock_keyring) -> None:
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.OPENAI, "sk-source-test")
        assert store.key_source(Provider.OPENAI) == KeySource.KEYCHAIN

    def test_fingerprint_no_raw_key(self, tmp_path: Path, mock_keyring) -> None:
        """Fingerprint does not contain the raw key."""
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.OPENAI, "sk-secret-key-99999")
        fp = store.fingerprint(Provider.OPENAI)
        assert fp.startswith("sha256:")
        assert "sk-secret" not in fp
        assert "99999" not in fp

    def test_set_key_preserves_strip(self, tmp_path: Path, mock_keyring) -> None:
        store = MacKeychainProviderKeyStore()
        store.set_key(Provider.OPENAI, "  sk-with-whitespace  ")
        assert store.get_key(Provider.OPENAI) == "sk-with-whitespace"


class TestProviderStatusHonestSemantics:
    """provider_status never returns 'valid' without network check."""

    def test_status_is_skipped_for_configured(self, monkeypatch: pytest.MonkeyPatch):
        """Configured providers show status='skipped', not 'valid'."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        result = provider_status(key_store=EnvProviderKeyStore())
        openai = next(
            p for p in result.get("providers", []) if p["provider"] == "openai"
        )
        assert openai["status"] == "skipped"
        assert openai["configured"] is True

    def test_status_is_skipped_for_missing(self):
        """Missing-key providers show status='skipped'."""
        result = provider_status(key_store=EnvProviderKeyStore())
        for p in result.get("providers", []):
            assert p["status"] == "skipped"

    def test_no_valid_status_without_network(self, monkeypatch: pytest.MonkeyPatch):
        """No provider shows 'valid' when no network checks were run."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        result = provider_status(key_store=EnvProviderKeyStore())
        for p in result.get("providers", []):
            assert p["status"] != "valid"


class TestRedactionIntegration:
    def test_redaction_refuses_api_key_field(self):
        from rig_relay.evidence.redaction import classify_shareable_field

        assert classify_shareable_field("api_key", "sk-test") == "forbid"
        assert classify_shareable_field("provider_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("openai_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("anthropic_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("gemini_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("google_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("openrouter_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("deepseek_api_key", "sk-test") == "forbid"
        assert classify_shareable_field("authorization", "Bearer token") == "forbid"
        assert classify_shareable_field("bearer_token", "tok") == "forbid"

    def test_audit_artifact_contains_no_raw_keys(self, tmp_path: Path):
        """Simulate an intent result artifact going through audit redaction."""
        from rig_relay.evidence.redaction import assert_remote_safe

        result = {
            "intent_name": "provider_onboarding_save_key",
            "status": "completed",
            "provider": "openai",
            "key_source": "dev_file",
            "key_fingerprint": "sha256:abc123",
            "api_key": "sk-should-be-redacted",
        }
        safe = assert_remote_safe(result)
        assert safe.get("api_key") == "[REDACTED]"
        assert safe.get("key_fingerprint") == "sha256:abc123"
        assert "sk-should-be-redacted" not in str(safe)


class TestProviderClassification:
    """ProviderClass distinguishes provider architectural role from API style."""

    def test_all_known_providers_have_class(self):
        from rig_relay.providers.models import (
            Provider,
            ProviderClass,
            provider_class_for,
        )

        for provider in Provider:
            pv_class = provider_class_for(provider)
            assert isinstance(pv_class, ProviderClass)
            assert pv_class.value != ""

    def test_direct_providers_are_not_gateways(self):
        from rig_relay.providers.models import (
            Provider,
            ProviderClass,
            provider_class_for,
        )

        direct_providers = {
            Provider.OPENAI,
            Provider.ANTHROPIC,
            Provider.GOOGLE,
            Provider.DEEPSEEK,
        }
        for provider in direct_providers:
            assert provider_class_for(provider) == ProviderClass.DIRECT_INFERENCE

    def test_openrouter_is_gateway_not_direct(self):
        from rig_relay.providers.models import (
            Provider,
            ProviderClass,
            provider_class_for,
        )

        assert provider_class_for(Provider.OPENROUTER) == ProviderClass.ROUTED_GATEWAY
        assert provider_class_for(Provider.OPENROUTER) != ProviderClass.DIRECT_INFERENCE

    def test_local_inference_is_local_server(self):
        from rig_relay.providers.models import (
            Provider,
            ProviderClass,
            provider_class_for,
        )

        assert (
            provider_class_for(Provider.LOCAL_INFERENCE) == ProviderClass.LOCAL_SERVER
        )

    def test_provider_class_via_registry(self):
        from rig_relay.providers.registry import get_provider_class

        assert get_provider_class("openai") is not None
        assert get_provider_class("google") is not None
        assert get_provider_class("openrouter") is not None
        assert get_provider_class("nonexistent") is None


class TestProviderCapabilityReadSurface:
    """The read-only capability surface returns honest, typed data without secrets."""

    def test_compute_returns_all_providers(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps = compute_provider_capabilities()
        assert len(caps) >= 6
        provider_ids = {c.provider_id for c in caps}
        assert "openai" in provider_ids
        assert "anthropic" in provider_ids
        assert "google" in provider_ids
        assert "openrouter" in provider_ids
        assert "deepseek" in provider_ids
        assert "local_inference" in provider_ids

    def test_compute_returns_typed_data(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps = compute_provider_capabilities()
        for cap in caps:
            assert isinstance(cap.provider_id, str)
            assert isinstance(cap.provider_class.value, str)
            assert isinstance(cap.api_style, str)
            assert isinstance(cap.network_egress, bool)
            assert isinstance(cap.executable, bool)

    def test_all_cloud_providers_have_network_egress(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps = compute_provider_capabilities()
        for cap in caps:
            if cap.provider_id in {
                "openai",
                "anthropic",
                "google",
                "openrouter",
                "deepseek",
            }:
                assert cap.network_egress is True

    def test_local_inference_no_network_egress(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps = compute_provider_capabilities()
        local = next(c for c in caps if c.provider_id == "local_inference")
        assert local.network_egress is False
        assert local.requires_credential is False

    def test_capability_records_contain_no_secrets(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps = compute_provider_capabilities()
        for cap in caps:
            d = cap.to_dict()
            for v in d.values():
                if isinstance(v, str):
                    assert "sk-" not in v
                    assert "Bearer" not in v
                    assert "api_key" not in v.lower() or v == "api_key"

    def test_openrouter_distinct_from_openai(self):
        from rig_relay.providers.registry import get_provider_capability

        openai_cap = get_provider_capability("openai")
        openrouter_cap = get_provider_capability("openrouter")
        assert openai_cap is not None
        assert openrouter_cap is not None
        assert openai_cap.provider_class.value != openrouter_cap.provider_class.value

    def test_deepseek_uses_openai_style_but_is_direct(self):
        from rig_relay.providers.registry import get_provider_capability

        cap = get_provider_capability("deepseek")
        assert cap is not None
        assert cap.api_style == "openai"
        assert cap.provider_class.value == "direct_inference"
        assert cap.verified_thinking is True

    def test_gemini_does_not_claim_unsupported_caps(self):
        from rig_relay.providers.registry import get_provider_capability

        cap = get_provider_capability("google")
        assert cap is not None
        assert cap.verified_tool_use is False
        assert cap.verified_structured_output is False
        assert cap.verified_thinking is False

    def test_gemini_capability_has_honest_notes(self):
        from rig_relay.providers.registry import get_provider_capability

        cap = get_provider_capability("google")
        assert cap is not None
        assert len(cap.notes) > 0
        joined = " ".join(cap.notes).lower()
        assert "not yet implemented" in joined

    def test_read_surface_performs_no_network_calls(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        # This must complete without any HTTP activity.
        caps = compute_provider_capabilities()
        assert len(caps) > 0
        # Calling again must produce identical results.
        caps2 = compute_provider_capabilities()
        for a, b in zip(caps, caps2, strict=True):
            assert a.to_dict() == b.to_dict()

    def test_get_provider_capability_lookup(self):
        from rig_relay.providers.registry import get_provider_capability

        assert get_provider_capability("openai") is not None
        assert get_provider_capability("google") is not None
        assert get_provider_capability("nonexistent") is None

    def test_default_model_present(self):
        from rig_relay.providers.registry import get_provider_capability

        gemini = get_provider_capability("google")
        assert gemini is not None
        assert gemini.default_model == "gemini-2.0-flash"

    def test_configured_and_executable_flags(self):
        from rig_relay.providers.registry import compute_provider_capabilities

        caps_default = compute_provider_capabilities(configured=False)
        for cap in caps_default:
            assert cap.configured is False
            assert cap.executable is False

        caps_configured = compute_provider_capabilities(configured=True)
        for cap in caps_configured:
            assert cap.configured is True
            if cap.adapter_available:
                assert cap.executable is True
