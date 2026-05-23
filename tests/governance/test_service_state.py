from __future__ import annotations

from pathlib import Path
import secrets
from typing import Any
from unittest.mock import patch

from rig_relay.core.telemetry.types import TelemetryMode
from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.governance.service_state import (
    CapabilityGate,
    ProfileState,
    ProfileStore,
    ServiceState,
    _profile_to_service_state,
)


def _valid_request(
    intent_name: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": f"test_service_state_{secrets.token_hex(4)}",
        "created_at": "2026-05-14T00:00:00Z",
        "intent_name": intent_name,
        "parameters": params or {},
        "dry_run": True,
    }


def _create_unlocked_profile_store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(root=tmp_path)
    store.create_first_launch_profile()
    store.unlock()
    return store


def _create_locked_profile_store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(root=tmp_path)
    store.create_first_launch_profile()
    store.unlock()
    store.lock()
    return store


def _create_degraded_profile_store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(root=tmp_path)
    store.create_first_launch_profile()
    store.unlock()
    store.mark_degraded(reason="test degradation")
    return store


# ── TestProfileStore ─────────────────────────────────────────────────


class TestProfileStore:
    def test_load_returns_none_when_no_profile(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        assert store.load() is None

    def test_create_first_launch_profile_creates_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        profile = store.create_first_launch_profile()
        assert profile.profile_state == ProfileState.SETUP_REQUIRED
        assert profile.profile_id
        assert profile.schema_version == "rig.relay.profile.v1"
        assert profile.local_auth_enabled is False
        assert profile.passkey_registered is False
        assert profile.platform_credential_registered is False
        assert profile.telemetry_mode == TelemetryMode.ENABLED_FIRST_PARTY.value
        assert store.exists()

    def test_save_and_load_roundtrips(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        profile = store.create_first_launch_profile()
        loaded = store.load()
        assert loaded is not None
        assert loaded.profile_id == profile.profile_id
        assert loaded.profile_state == ProfileState.SETUP_REQUIRED

    def test_unlock_transitions_setup_required_to_unlocked(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        result = store.unlock()
        assert result is not None
        assert result.profile_state == ProfileState.UNLOCKED
        assert result.local_auth_enabled is True
        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.profile_state == ProfileState.UNLOCKED

    def test_unlock_unlocked_profile_returns_same(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        result = store.unlock()
        assert result is not None
        assert result.profile_state == ProfileState.UNLOCKED

    def test_lock_transitions_unlocked_to_locked(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        result = store.lock()
        assert result is not None
        assert result.profile_state == ProfileState.LOCKED
        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.profile_state == ProfileState.LOCKED

    def test_lock_returns_none_when_no_profile(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        assert store.lock() is None

    def test_mark_degraded_transitions_unlocked_to_degraded(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        result = store.mark_degraded(reason="telemetry disabled")
        assert result is not None
        assert result.profile_state == ProfileState.DEGRADED
        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.profile_state == ProfileState.DEGRADED

    def test_mark_degraded_does_not_transition_locked(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        store.lock()
        result = store.mark_degraded()
        assert result is not None
        assert result.profile_state == ProfileState.LOCKED

    def test_mark_degraded_keeps_degraded_state(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        store.mark_degraded()
        result = store.mark_degraded(reason="another reason")
        assert result is not None
        assert result.profile_state == ProfileState.DEGRADED

    def test_profile_summary_no_profile(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        summary = store.profile_summary()
        assert summary == {"exists": False, "profile_state": "setup_required"}

    def test_profile_summary_no_raw_secrets(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        summary = store.profile_summary()
        forbidden = {"passkey", "token", "secret", "key", "credential", "password"}
        for key in summary:
            lower_key = key.lower()
            for secret_word in forbidden:
                assert secret_word not in lower_key or key in {
                    "passkey_registered",
                    "platform_credential_registered",
                }, f"summary key '{key}' may leak sensitive data"

    def test_profile_summary_includes_expected_fields(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        summary = store.profile_summary()
        expected_keys = {
            "exists",
            "profile_id",
            "schema_version",
            "created_at",
            "local_auth_enabled",
            "passkey_registered",
            "platform_credential_registered",
            "telemetry_mode",
            "profile_state",
            "updated_at",
        }
        for key in expected_keys:
            assert key in summary, f"missing key '{key}' in summary"

    def test_profile_store_with_explicit_root(self, tmp_path: Path):
        custom_root = tmp_path / "custom" / "profile"
        store = ProfileStore(root=custom_root)
        assert store._root == custom_root
        assert store.exists() is False
        profile = store.create_first_launch_profile()
        assert profile.profile_state == ProfileState.SETUP_REQUIRED
        assert store.exists()
        assert (custom_root / "profile.json").is_file()

    def test_is_unlocked_returns_true_for_unlocked(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        profile = store.load()
        assert profile is not None
        assert profile.is_unlocked() is True

    def test_is_unlocked_returns_true_for_degraded(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        store.mark_degraded()
        profile = store.load()
        assert profile is not None
        assert profile.is_unlocked() is True

    def test_is_unlocked_returns_false_for_locked(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        store.lock()
        profile = store.load()
        assert profile is not None
        assert profile.is_unlocked() is False

    def test_unlock_no_profile_returns_none(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        assert store.unlock() is None

    def test_unlock_with_passkey_ok_when_local_auth_disabled(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        profile = store.create_first_launch_profile()
        store.unlock()
        store.lock()
        profile = store.load()
        assert profile is not None
        assert profile.local_auth_enabled is True
        result = store.unlock(passkey_ok=True)
        assert result is not None
        assert result.profile_state == ProfileState.UNLOCKED

    def test_unlock_without_passkey_stays_locked_when_local_auth(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        store.unlock()
        store.lock()
        result = store.unlock(passkey_ok=False)
        assert result is not None
        assert result.profile_state == ProfileState.LOCKED

    def test_create_first_launch_profile_idempotent(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        first = store.create_first_launch_profile()
        second = store.create_first_launch_profile()
        assert first.profile_id == second.profile_id


# ── TestCapabilityGate ──────────────────────────────────────────────


class TestCapabilityGate:
    def test_no_profile_allows_read_only_intents(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("refresh_projection")
        assert allowed is True
        assert reason == ""

    def test_no_profile_blocks_sensitive_intents(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("sign_in_github_start")
        assert allowed is False
        assert "setup_required" in reason

    def test_unlocked_profile_allows_sensitive_intents(self, tmp_path: Path):
        store = _create_unlocked_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("sign_in_github_start")
        assert allowed is True
        assert reason == ""

    def test_locked_profile_blocks_sensitive_intents(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("provider_onboarding_save_key")
        assert allowed is False
        assert "locked" in reason

    def test_setup_required_blocks_sensitive_intents(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("telemetry_upload_google")
        assert allowed is False
        assert "setup_required" in reason

    def test_degraded_profile_allows_sensitive_intents(self, tmp_path: Path):
        store = _create_degraded_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("sign_in_github_start")
        assert allowed is True
        assert reason == ""

    def test_always_allowed_does_not_contain_sensitive_capabilities(self):
        assert (
            CapabilityGate.ALWAYS_ALLOWED & CapabilityGate.SENSITIVE_CAPABILITIES
            == set()
        )

    def test_state_summary_no_profile_returns_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = CapabilityGate(profile_store=store)
        summary = gate.state_summary()
        assert summary["service_state"] == ServiceState.SETUP_REQUIRED.value
        assert summary["profile_exists"] is False
        assert summary["profile_state"] == ProfileState.SETUP_REQUIRED.value

    def test_state_summary_with_profile_returns_correct_state(self, tmp_path: Path):
        store = _create_unlocked_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        summary = gate.state_summary()
        assert summary["service_state"] == ServiceState.READY.value
        assert summary["profile_exists"] is True
        assert summary["profile_state"] == ProfileState.UNLOCKED.value
        assert summary["local_auth_enabled"] is True

    def test_state_summary_locked_profile(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        summary = gate.state_summary()
        assert summary["service_state"] == ServiceState.LOCKED.value
        assert summary["profile_state"] == ProfileState.LOCKED.value

    def test_state_summary_degraded_profile(self, tmp_path: Path):
        store = _create_degraded_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        summary = gate.state_summary()
        assert summary["service_state"] == ServiceState.DEGRADED.value
        assert summary["profile_state"] == ProfileState.DEGRADED.value

    def test_unknown_intent_allowed_when_unlocked(self, tmp_path: Path):
        store = _create_unlocked_profile_store(tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("some_unknown_intent")
        assert allowed is True

    def test_unknown_intent_allowed_when_no_profile(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = CapabilityGate(profile_store=store)
        allowed, reason = gate.is_allowed("some_unknown_intent")
        assert allowed is True


# ── TestServiceState ────────────────────────────────────────────────


class TestServiceState:
    def test_service_state_enum_values(self):
        assert ServiceState.STARTING.value == "starting"
        assert ServiceState.SETUP_REQUIRED.value == "setup_required"
        assert ServiceState.LOCKED.value == "locked"
        assert ServiceState.UNLOCKING.value == "unlocking"
        assert ServiceState.READY.value == "ready"
        assert ServiceState.DEGRADED.value == "degraded"
        assert ServiceState.STOPPING.value == "stopping"
        assert ServiceState.STOPPED.value == "stopped"
        assert ServiceState.FAILED.value == "failed"

    def test_profile_to_service_state_mapping(self):
        assert (
            _profile_to_service_state(ProfileState.SETUP_REQUIRED)
            == ServiceState.SETUP_REQUIRED
        )
        assert _profile_to_service_state(ProfileState.LOCKED) == ServiceState.LOCKED
        assert _profile_to_service_state(ProfileState.UNLOCKED) == ServiceState.READY
        assert _profile_to_service_state(ProfileState.DEGRADED) == ServiceState.DEGRADED

    def test_profile_state_enum_values(self):
        assert ProfileState.SETUP_REQUIRED.value == "setup_required"
        assert ProfileState.LOCKED.value == "locked"
        assert ProfileState.UNLOCKED.value == "unlocked"
        assert ProfileState.DEGRADED.value == "degraded"


# ── TestDesktopIntentGating ─────────────────────────────────────────


class TestDesktopIntentGating:
    def _make_gate(self, store: ProfileStore) -> CapabilityGate:
        return CapabilityGate(profile_store=store)

    def test_sign_in_start_refused_when_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"
        assert "setup_required" in result.get("summary", "")

    def test_sign_in_start_allowed_when_unlocked(self, tmp_path: Path, monkeypatch):
        store = _create_unlocked_profile_store(tmp_path)
        gate = self._make_gate(store)
        monkeypatch.setattr("rig_relay.governance.service_state._service_state", gate)
        monkeypatch.setenv("RIG_RELAY_GITHUB_CLIENT_ID", "test_service_state_id")
        monkeypatch.setenv(
            "RIG_RELAY_GITHUB_CLIENT_SECRET", "test_service_state_secret"
        )

        result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert result["status"] == "completed"

        # Clean up the auth session listener
        from rig_relay.identity.auth_session_manager import get_auth_session_manager

        session_id = result.get("extra_fields", {}).get("auth_session_id")
        if session_id:
            get_auth_session_manager().cancel_session(session_id)

    def test_refresh_projection_allowed_when_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("refresh_projection"))
        assert (
            result["status"] != "refused"
            or result.get("error_code") != "capability_gated"
        )

    def test_provider_onboarding_save_key_refused_when_locked(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(
                _valid_request(
                    "provider_onboarding_save_key",
                    {"provider": "openai", "api_key": "sk-test-key"},
                )
            )
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"
        assert "locked" in result.get("summary", "")

    def test_identity_status_allowed_when_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("identity_status"))
        assert (
            result["status"] != "refused"
            or result.get("error_code") != "capability_gated"
        )

    def test_sign_in_github_poll_allowed_when_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(
                _valid_request(
                    "sign_in_github_poll", {"auth_session_id": "nonexistent"}
                )
            )
        assert (
            result["status"] != "refused"
            or result.get("error_code") != "capability_gated"
        )

    def test_provider_status_allowed_when_setup_required(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("provider_status"))
        assert (
            result["status"] != "refused"
            or result.get("error_code") != "capability_gated"
        )

    def test_fleet_orchestrate_refused_when_no_profile(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("fleet_orchestrate"))
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"
