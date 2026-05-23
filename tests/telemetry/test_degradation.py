from __future__ import annotations

import json
import os
from pathlib import Path

from rig_relay.core.telemetry import (
    TelemetryMode,
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
    assert result["degradation_mode"] == TelemetryMode.FULL.value
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
    assert result["degradation_mode"] == TelemetryMode.ENABLED_FIRST_PARTY.value
    assert "remote_upload" in result["degraded_capabilities"]


def test_disabled_mode_when_local_disabled() -> None:
    settings = {
        "local_operational_enabled": False,
        "remote_beta_sharing_enabled": True,
        "share_level": "derived_only",
        "mode": "beta_orchestration",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == TelemetryMode.DISABLED_BY_USER.value
    assert "governed_mode" in result["degraded_capabilities"]


def test_degraded_capabilities_list_non_empty_when_degraded() -> None:
    settings = {
        "local_operational_enabled": True,
        "remote_beta_sharing_enabled": False,
        "share_level": "off",
        "mode": "governed_local",
    }
    result = compute_degradation_mode(settings)
    assert result["degradation_mode"] == TelemetryMode.ENABLED_FIRST_PARTY.value
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


# ── Harness survival tests ─────────────────────────────────────────────


def test_log_local_event_no_crash_when_disabled(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(False)
        session_id = "ds-harness-1"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})
        log_local_event(session_id, "rig.relay.tool.call_completed", {"tool": "x"})
        log_local_event(session_id, "rig.relay.session.closed", {})
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_log_local_event_no_observability_when_disabled(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(False)
        session_id = "ds-nolog-1"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})
        observability_file = sessions_dir / session_id / "observability.jsonl"
        assert not observability_file.exists()
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_degradation_marker_written_when_disabled(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        read_degradation_marker,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(False)
        session_id = "ds-marker-1"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})
        marker = read_degradation_marker(session_id)
        assert marker is not None
        assert marker["degradation_mode"] == TelemetryMode.DISABLED_BY_USER.value
        assert marker["session_id"] == session_id
        assert "preserved_capabilities" in marker
        assert "degraded_capabilities" in marker
        assert "disabled_capabilities" in marker
        assert marker["export_allowed"] is False
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_observability_written_when_enabled(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(True)
        session_id = "ds-log-1"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})
        observability_file = sessions_dir / session_id / "observability.jsonl"
        assert observability_file.exists()
        lines = observability_file.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_name"] == "rig.relay.session.started"
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


# ── Visible degradation behavior tests ──────────────────────────────────


def test_disabled_mode_degradation_marker_available(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        read_degradation_marker,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(False)
        session_id = "ds-vis-1"
        log_local_event(session_id, "rig.relay.session.started", {"v": 1})
        marker = read_degradation_marker(session_id)
        assert marker is not None
        assert marker["degradation_mode"] == TelemetryMode.DISABLED_BY_USER.value
        assert marker["export_allowed"] is False
        assert "core_harness_execution" in marker["preserved_capabilities"]
        assert "adaptive_diagnostics" in marker["degraded_capabilities"]
        assert "ralph_refinement" in marker["degraded_capabilities"]
        assert "telemetry_bundle_export" in marker["disabled_capabilities"]
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_disabled_mode_no_events_in_observability(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(False)
        session_id = "ds-vis-2"
        for i in range(5):
            log_local_event(session_id, f"rig.relay.event.{i}", {"n": i})
        obs_file = sessions_dir / session_id / "observability.jsonl"
        assert not obs_file.exists(), "no events should be written when disabled"
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_enabled_vs_disabled_behavior_difference(tmp_path: Path) -> None:
    import rig_relay.core.paths._vibe_home as vh
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        log_local_event,
        read_degradation_marker,
        set_telemetry_enabled,
    )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    original_resolver = vh.SESSIONS_ROOT._resolver
    vh.SESSIONS_ROOT._resolver = lambda: sessions_dir
    original_state = is_telemetry_enabled()

    try:
        set_telemetry_enabled(True)
        session_enabled = "ds-vs-enabled"
        log_local_event(session_enabled, "rig.relay.session.started", {"v": 1})
        obs_enabled = sessions_dir / session_enabled / "observability.jsonl"
        marker_enabled = read_degradation_marker(session_enabled)

        set_telemetry_enabled(False)
        session_disabled = "ds-vs-disabled"
        log_local_event(session_disabled, "rig.relay.session.started", {"v": 1})
        obs_disabled = sessions_dir / session_disabled / "observability.jsonl"
        marker_disabled = read_degradation_marker(session_disabled)

        assert obs_enabled.exists(), "enabled = observability file created"
        assert not obs_disabled.exists(), "disabled = no observability file"
        assert marker_enabled is None, "enabled = no degradation marker"
        assert marker_disabled is not None, "disabled = degradation marker present"
        assert (
            marker_disabled["degradation_mode"] == TelemetryMode.DISABLED_BY_USER.value
        )
        assert marker_disabled["export_allowed"] is False
    finally:
        set_telemetry_enabled(original_state)
        vh.SESSIONS_ROOT._resolver = original_resolver


def test_rig_telemetry_enabled_env_var_disables() -> None:
    from rig_relay.core.telemetry.local import (
        is_telemetry_enabled,
        set_telemetry_enabled,
    )

    set_telemetry_enabled(True)
    assert is_telemetry_enabled() is True

    original = os.environ.get("RIG_TELEMETRY_ENABLED")
    try:
        os.environ["RIG_TELEMETRY_ENABLED"] = "0"
        assert is_telemetry_enabled() is False
        os.environ["RIG_TELEMETRY_ENABLED"] = "false"
        assert is_telemetry_enabled() is False
        os.environ["RIG_TELEMETRY_ENABLED"] = "no"
        assert is_telemetry_enabled() is False
        os.environ["RIG_TELEMETRY_ENABLED"] = "1"
        assert is_telemetry_enabled() is True
        os.environ["RIG_TELEMETRY_ENABLED"] = "true"
        assert is_telemetry_enabled() is True
    finally:
        if original is not None:
            os.environ["RIG_TELEMETRY_ENABLED"] = original
        else:
            os.environ.pop("RIG_TELEMETRY_ENABLED", None)
        set_telemetry_enabled(True)
