from __future__ import annotations

import json

from rig_relay.core.telemetry import (
    compute_degradation_mode,
    get_telemetry_degradation_state,
)


def test_full_mode_when_both_enabled() -> None:
    settings = {
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
        "mode": "beta_orchestration",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == "full"
    assert result["degraded_capabilities"] == []
    assert "enabled" in result["degradation_reason"].lower()


def test_degraded_mode_when_remote_disabled() -> None:
    settings = {
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "derived_only",
        "mode": "governed_local",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == "degraded"
    assert "remote_upload" in result["degraded_capabilities"]


def test_disabled_mode_when_local_disabled() -> None:
    settings = {
        "local_operational_enabled": False,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
        "mode": "beta_orchestration",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == "disabled"
    assert "governed_mode" in result["degraded_capabilities"]


def test_degraded_capabilities_list_non_empty_when_degraded() -> None:
    settings = {
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
        "mode": "governed_local",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == "degraded"
    assert len(result["degraded_capabilities"]) > 0


def test_degradation_state_json_serializable() -> None:
    settings = {
        "local_operational_enabled": False,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
        "mode": "basic_local",
    }
    state = get_telemetry_degradation_state(settings)
    serialized = json.dumps(state, sort_keys=True)
    assert isinstance(json.loads(serialized), dict)


def test_degradation_state_has_required_fields() -> None:
    settings = {
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
        "mode": "beta_orchestration",
    }
    state = get_telemetry_degradation_state(settings)
    required = {
        "degradation_mode",
        "degraded_capabilities",
        "degradation_reason",
        "effective_at",
        "local_observability_enabled",
        "remote_export_enabled",
        "share_level",
        "mode",
    }
    assert set(state.keys()) == required
