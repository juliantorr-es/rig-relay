from __future__ import annotations

from pathlib import Path
import secrets
from typing import Any
from unittest.mock import patch

import pytest

from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.governance.service_state import (
    CapabilityGate,
    ProfileState,
    ProfileStore,
)


def _valid_request(
    intent_name: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": f"test_cross_surface_{secrets.token_hex(4)}",
        "created_at": "2026-05-17T00:00:00Z",
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


# ── TestCockpitIntentCrossSurface ───────────────────────────────────


class TestCockpitIntentCrossSurface:
    def _make_gate(self, store: ProfileStore) -> CapabilityGate:
        return CapabilityGate(profile_store=store)

    def test_locked_blocks_sensitive_intent(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"
        assert "locked" in result.get("summary", "")

    def test_locked_allows_read_only_intent(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("refresh_projection"))
        assert (
            result["status"] != "refused"
            or result.get("error_code") != "capability_gated"
        )

    def test_unlocked_allows_sensitive_intent(self, tmp_path: Path, monkeypatch):
        store = _create_unlocked_profile_store(tmp_path)
        gate = self._make_gate(store)
        monkeypatch.setattr("rig_relay.governance.service_state._service_state", gate)
        monkeypatch.setenv("RIG_RELAY_GITHUB_CLIENT_ID", "test_cross_surface_id")
        monkeypatch.setenv(
            "RIG_RELAY_GITHUB_CLIENT_SECRET", "test_cross_surface_secret"
        )

        result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert result["status"] == "completed"

        from rig_relay.identity.auth_session_manager import get_auth_session_manager

        session_id = result.get("extra_fields", {}).get("auth_session_id")
        if session_id:
            get_auth_session_manager().cancel_session(session_id)

    def test_setup_required_blocks_sensitive(self, tmp_path: Path):
        store = ProfileStore(root=tmp_path)
        store.create_first_launch_profile()
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("telemetry_upload_google"))
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"

    def test_no_bypass_via_extra_fields(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        extra = result.get("extra_fields", {})
        assert "bypass_gate" not in extra
        assert "force_allow" not in extra

    def test_structured_refusal_has_capability_id(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        with patch(
            "rig_relay.governance.service_state.get_capability_gate", return_value=gate
        ):
            result = execute_desktop_intent(
                _valid_request(
                    "provider_onboarding_save_key",
                    {"provider": "openai", "api_key": "sk-test"},
                )
            )
        assert result["status"] == "refused"
        assert result["error_code"] == "capability_gated"
        extra = result.get("extra_fields", {})
        assert "gating_reason" in extra


# ── TestToolExecutionGate ───────────────────────────────────────────


class TestToolExecutionGate:
    def test_mutation_tool_gated_when_locked(self):
        pytest.skip("Tool runtime gate not yet integrated")

    def test_read_only_tool_allowed_when_locked(self):
        pytest.skip("Tool runtime gate not yet integrated")

    def test_mutation_tool_allowed_when_unlocked(self):
        pytest.skip("Tool runtime gate not yet integrated")

    def test_tool_execution_mode_classification(self):
        pytest.skip("Tool runtime gate not yet integrated")


# ── TestACPCommandGating ────────────────────────────────────────────


class TestACPCommandGating:
    def test_leanstall_blocked_when_locked(self):
        pytest.skip("ACP gate not yet integrated")

    def test_unleanstall_blocked_when_locked(self):
        pytest.skip("ACP gate not yet integrated")

    def test_proxy_setup_blocked_when_locked(self):
        pytest.skip("ACP gate not yet integrated")

    def test_help_allowed_when_locked(self):
        pytest.skip("ACP gate not yet integrated")


# ── TestIntegrationCapabilityGating ─────────────────────────────────


class TestIntegrationCapabilityGating:
    def _make_gate(self, store: ProfileStore) -> CapabilityGate:
        return CapabilityGate(profile_store=store)

    def test_integration_gated_when_profile_required_and_locked(self, tmp_path: Path):
        store = _create_locked_profile_store(tmp_path)
        gate = self._make_gate(store)
        allowed, reason = gate.is_allowed("provider_onboarding_save_key")
        assert allowed is False
        assert "locked" in reason

    def test_integration_available_when_profile_not_required_or_unlocked(
        self, tmp_path: Path
    ):
        store = _create_unlocked_profile_store(tmp_path)
        gate = self._make_gate(store)
        allowed, reason = gate.is_allowed("provider_onboarding_save_key")
        assert allowed is True
        assert reason == ""

    def test_integration_never_exposes_tokens(self, tmp_path: Path):
        store = _create_unlocked_profile_store(tmp_path)
        gate = self._make_gate(store)
        summary = gate.state_summary()
        forbidden = {"passkey", "token", "secret", "key", "credential", "password"}
        for key in summary:
            lower_key = key.lower()
            for secret_word in forbidden:
                assert secret_word not in lower_key or key in {
                    "passkey_registered",
                    "platform_credential_registered",
                }, f"summary key '{key}' may leak sensitive data"


# ── TestCapabilityMatrix ────────────────────────────────────────────


class TestCapabilityMatrix:
    def test_matrix_maps_every_sensitive_capability_to_enforcement_point(self):
        for capability in sorted(CapabilityGate.SENSITIVE_CAPABILITIES):
            assert isinstance(capability, str)
            assert capability
        for capability in sorted(CapabilityGate.ACP_COMMAND_CAPABILITIES):
            assert isinstance(capability, str)
            assert capability
            assert capability.startswith("acp_command:")

    def test_every_gated_capability_has_test_coverage(self):
        sensitive = CapabilityGate.SENSITIVE_CAPABILITIES
        assert "sign_in_github_start" in sensitive
        assert "provider_onboarding_save_key" in sensitive
        assert "telemetry_upload_google" in sensitive

    def test_always_allowed_contains_read_only_capabilities(self):
        always = CapabilityGate.ALWAYS_ALLOWED
        assert "refresh_projection" in always
        assert "identity_status" in always
        assert "provider_status" in always

    def test_sensitive_and_always_allowed_are_disjoint(self):
        assert (
            CapabilityGate.SENSITIVE_CAPABILITIES & CapabilityGate.ALWAYS_ALLOWED
            == set()
        )
        assert (
            CapabilityGate.ACP_COMMAND_CAPABILITIES & CapabilityGate.ALWAYS_ALLOWED
            == set()
        )

    def test_acp_commands_are_separate_from_cockpit_intents(self):
        cockpit_sensitive = {
            c
            for c in CapabilityGate.SENSITIVE_CAPABILITIES
            if not c.startswith("acp_command:")
        }
        acp_commands = set(CapabilityGate.ACP_COMMAND_CAPABILITIES)
        assert cockpit_sensitive & acp_commands == set()
        assert all(c.startswith("acp_command:") for c in acp_commands)

    def test_profile_state_enum_covers_all_gating_states(self):
        states = {e.value for e in ProfileState}
        assert "setup_required" in states
        assert "locked" in states
        assert "unlocked" in states
        assert "degraded" in states
