"""Desktop WebSocket correlation tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from rig_relay.desktop.correlation import (
    DesktopCorrelation,
    _classify_path_kind,
    _safe_details,
    hash_dict_payload,
    hash_message_payload,
    new_correlation_id,
    new_transport_session_id,
)


class TestCorrelationIDs:
    def test_correlation_ids_are_unique(self) -> None:
        ids = {new_correlation_id() for _ in range(100)}
        assert len(ids) == 100

    def test_correlation_id_format(self) -> None:
        cid = new_correlation_id()
        assert cid.startswith("corr_")
        assert len(cid) > 12

    def test_transport_session_ids_are_unique(self) -> None:
        ids = {new_transport_session_id() for _ in range(100)}
        assert len(ids) == 100

    def test_transport_session_id_format(self) -> None:
        tid = new_transport_session_id()
        assert tid.startswith("ts_")
        assert len(tid) > 10


class TestPayloadHashing:
    def test_message_hash_deterministic(self) -> None:
        a = hash_message_payload("hello")
        b = hash_message_payload("hello")
        assert a == b

    def test_message_hash_different(self) -> None:
        a = hash_message_payload("hello")
        b = hash_message_payload("world")
        assert a != b

    def test_dict_hash_deterministic(self) -> None:
        d = {"type": "ping", "seq": 1}
        a = hash_dict_payload(d)
        b = hash_dict_payload(d)
        assert a == b

    def test_dict_hash_order_independent(self) -> None:
        a = hash_dict_payload({"a": 1, "b": 2})
        b = hash_dict_payload({"b": 2, "a": 1})
        assert a == b

    def test_dict_hash_different(self) -> None:
        a = hash_dict_payload({"type": "ping"})
        b = hash_dict_payload({"type": "auth"})
        assert a != b


class TestDesktopCorrelation:
    def test_disabled_recorder_is_noop(self) -> None:
        corr = DesktopCorrelation()
        assert corr.is_active is False
        # Should not raise
        corr.emit_event("test.event", {"key": "val"})
        corr.emit_transport_event("test.transport")
        corr.emit_intent_dispatched("ralph_scan")

    def test_emits_event_when_recorder_active(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()

        corr = DesktopCorrelation(trace_recorder=recorder)
        corr.emit_event("test.event", {"k": "v"})

        recorder.event.assert_called_once()
        call = recorder.event.call_args
        assert call.args[0] == "test.event"
        assert call.kwargs["attributes"]["k"] == "v"
        assert "correlation_id" in call.kwargs["attributes"]

    def test_emit_transport_event_includes_session_id(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()

        corr = DesktopCorrelation(trace_recorder=recorder)
        corr.emit_transport_event(
            "desktop.transport.message",
            transport_session_id="ts_abc",
            attributes={"transport.host": "127.0.0.1"},
        )

        attrs = recorder.event.call_args.kwargs["attributes"]
        assert attrs["transport.session_id"] == "ts_abc"
        assert attrs["transport.host"] == "127.0.0.1"

    def test_bridge_step_safe_details_included(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()

        corr = DesktopCorrelation(trace_recorder=recorder)
        corr.emit_bridge_step(
            "bridge:01",
            "assets verified",
            status="ok",
            details={"port": 9876, "tls_enabled": False},
        )

        attrs = recorder.event.call_args.kwargs["attributes"]
        assert attrs["bridge.step_id"] == "bridge:01"
        assert attrs["port"] == 9876

    def test_intent_dispatched_includes_hash(self) -> None:
        recorder = MagicMock()
        recorder.event = MagicMock()

        corr = DesktopCorrelation(trace_recorder=recorder)
        corr.emit_intent_dispatched(
            "ralph_scan",
            intent_id="int-1",
            payload_hash="sha256:abc",
            payload_kind="command",
        )

        attrs = recorder.event.call_args.kwargs["attributes"]
        assert attrs["intent.name"] == "ralph_scan"
        assert attrs["intent.payload_hash"] == "sha256:abc"


class TestSafeDetailsPrivacy:
    def test_frontend_dir_hashed_not_raw(self) -> None:
        details = {"frontend_dir": "/Users/user/Developer/rig-relay/frontend"}
        result = _safe_details(details)
        assert "frontend_dir" not in result
        assert "frontend_dir_hash" in result
        assert result["frontend_dir_kind"] == "repo"

    def test_ws_url_is_scheme_only(self) -> None:
        result = _safe_details({"ws_url": "wss://127.0.0.1:9876"})
        assert result["ws_scheme"] == "wss"

    def test_frontend_url_is_scheme_only(self) -> None:
        result = _safe_details({"frontend_url": "https://127.0.0.1:9876"})
        assert result["frontend_scheme"] == "https"

    def test_unknown_keys_are_dropped(self) -> None:
        result = _safe_details({"secret_token": "leaked", "raw_path": "/etc/passwd"})
        assert "secret_token" not in result
        assert "raw_path" not in result

    def test_safe_keys_preserved(self) -> None:
        result = _safe_details({"port": 9876, "host": "127.0.0.1"})
        assert result["port"] == 9876
        assert result["host"] == "127.0.0.1"

    def test_null_details(self) -> None:
        assert _safe_details(None) == {}


class TestPathClassification:
    def test_temp_path(self) -> None:
        assert _classify_path_kind("/tmp/scratch") == "temp"
        assert _classify_path_kind("/var/folders/x/y") == "temp"

    def test_worktree_path(self) -> None:
        assert _classify_path_kind("/some/worktree/lane") == "worktree"

    def test_app_support_path(self) -> None:
        assert (
            _classify_path_kind("/Users/user/Library/Application Support/Rig Relay")
            == "app_support"
        )

    def test_repo_path(self) -> None:
        assert _classify_path_kind("/Users/user/dev/rig-relay") == "repo"
