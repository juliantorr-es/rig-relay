from __future__ import annotations

import json

import pytest

from rig_relay.desktop.bridge_runtime_state import (
    BridgeRuntimeState,
    BridgeRuntimeStateTracker,
)


class TestBridgeRuntimeStateTracker:
    def test_initial_state_is_starting(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        assert rt.state == BridgeRuntimeState.STARTING

    def test_set_ready_transitions_to_idle(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        assert rt.state == BridgeRuntimeState.IDLE

    def test_record_work_started_transitions_to_active(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        assert rt.state == BridgeRuntimeState.IDLE
        rt.record_work_started()
        assert rt.state == BridgeRuntimeState.ACTIVE
        assert rt.active_work_count == 1

    def test_record_work_finished_transitions_to_idle(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        rt.record_work_started()
        assert rt.state == BridgeRuntimeState.ACTIVE
        rt.record_work_finished()
        assert rt.state == BridgeRuntimeState.IDLE
        assert rt.active_work_count == 0

    def test_nested_work_keeps_active_state(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        rt.record_work_started()
        rt.record_work_started()
        assert rt.state == BridgeRuntimeState.ACTIVE
        assert rt.active_work_count == 2
        rt.record_work_finished()
        assert rt.state == BridgeRuntimeState.ACTIVE
        assert rt.active_work_count == 1
        rt.record_work_finished()
        assert rt.state == BridgeRuntimeState.IDLE
        assert rt.active_work_count == 0

    def test_set_disconnected(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        rt.set_disconnected()
        assert rt.state == BridgeRuntimeState.DISCONNECTED
        assert not rt.is_connected

    def test_set_degraded(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        rt.set_degraded("projection build failed")
        assert rt.state == BridgeRuntimeState.DEGRADED
        assert rt.is_connected

    def test_set_failed(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_failed("backend initialization error")
        assert rt.state == BridgeRuntimeState.FAILED
        assert not rt.is_connected

    def test_idle_sequence_increments(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        assert rt.idle_sequence == 0
        assert rt.next_idle_sequence() == 1
        assert rt.next_idle_sequence() == 2
        assert rt.idle_sequence == 2

    def test_build_bridge_status_has_required_fields(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        rt.set_capabilities(["projection", "intent"])
        rt.set_disabled_reasons({"mutation": "gated"})
        rt.next_idle_sequence()
        status = rt.build_bridge_status()
        assert status["schema_version"] == "rig.relay.bridge_runtime.v1"
        assert status["handshake_id"] == "hs_test"
        assert status["backend_session_id"] == "be_test"
        assert status["bridge_runtime_state"] == "idle"
        assert status["idle_sequence"] == 1
        assert status["capabilities"] == ["projection", "intent"]
        assert status["disabled_reasons"] == {"mutation": "gated"}
        assert "generated_at" in status
        assert "started_at" in status
        assert "last_transition_at" in status

    def test_build_bridge_status_is_content_light(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        status = rt.build_bridge_status()
        json_str = json.dumps(status, sort_keys=True)
        assert len(json_str) < 4096
        sensitive_patterns = ["token", "secret", "api_key", "password", "raw_content"]
        for pattern in sensitive_patterns:
            assert pattern not in json_str.lower()

    def test_snapshot_includes_liveness_metrics(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()
        snap = rt.snapshot()
        assert snap["state"] == "idle"
        assert snap["handshake_id"] == "hs_test"
        assert snap["backend_session_id"] == "be_test"
        assert "uptime_sec" in snap
        assert snap["uptime_sec"] >= 0

    def test_multiple_transitions_track_count(self) -> None:
        rt = BridgeRuntimeStateTracker(
            handshake_id="hs_test", backend_session_id="be_test"
        )
        rt.set_ready()  # STARTING → READY → IDLE (2 transitions)
        rt.record_work_started()  # IDLE → ACTIVE (1)
        rt.record_work_finished()  # ACTIVE → IDLE (1)
        rt.set_degraded("test reason")  # IDLE → DEGRADED (1)
        snap = rt.snapshot()
        assert snap["transition_count"] == 5
        assert snap["state"] == "degraded"
        assert snap["previous_state"] == "idle"


class TestBridgeRuntimeStateEnum:
    def test_all_states_defined(self) -> None:
        expected = {
            "starting",
            "ready",
            "idle",
            "active",
            "degraded",
            "disconnecting",
            "disconnected",
            "failed",
        }
        actual = {s.value for s in BridgeRuntimeState}
        assert actual == expected

    def test_connected_states(self) -> None:
        connected = {
            BridgeRuntimeState.STARTING,
            BridgeRuntimeState.READY,
            BridgeRuntimeState.IDLE,
            BridgeRuntimeState.ACTIVE,
            BridgeRuntimeState.DEGRADED,
        }
        for state in BridgeRuntimeState:
            rt = BridgeRuntimeStateTracker(
                handshake_id="hs_test", backend_session_id="be_test"
            )
            rt._state = state
            assert rt.is_connected == (state in connected)
