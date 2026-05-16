"""Tests for ProgressEvent model and WebSocket progress streaming."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.desktop.progress_events import (
    EVENT_OPERATION_COMPLETED,
    EVENT_OPERATION_FAILED,
    EVENT_OPERATION_PROGRESS,
    EVENT_OPERATION_REFUSED,
    EVENT_OPERATION_STARTED,
    EVENT_OPERATION_WARNING,
    ProgressEvent,
    ProgressEventBuffer,
    build_progress_event,
    progress_event_sha256,
)


def _valid_request(intent_name: str = "refresh_projection") -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": "test_progress_001",
        "created_at": "2026-05-14T00:00:00Z",
        "intent_name": intent_name,
        "parameters": {},
        "dry_run": True,
    }


# ── Schema Validation ──


class TestProgressEventSchema:
    def test_schema_validates(self):
        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.progress_event.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        event = build_progress_event(
            operation_id="test_op",
            event_type=EVENT_OPERATION_STARTED,
            phase="test",
            message="Test event",
        )
        import jsonschema

        jsonschema.validate(
            instance=event.model_dump(mode="json", exclude_none=True), schema=schema
        )


# ── ProgressEvent Model ──


class TestProgressEventModel:
    def test_build_progress_event_has_required_fields(self):
        event = build_progress_event(
            operation_id="op_123",
            event_type=EVENT_OPERATION_STARTED,
            phase="validation",
            message="Starting validation",
        )
        assert event.schema_version == "rig.relay.progress_event.v1"
        assert event.event_id.startswith("pe_")
        assert event.operation_id == "op_123"
        assert event.event_type == EVENT_OPERATION_STARTED
        assert event.phase == "validation"
        assert event.status == "running"
        assert event.content_light_guarantee is True
        assert event.projection_refresh_recommended is False

    def test_content_light_guarantee(self):
        event = build_progress_event(
            operation_id="op_1",
            event_type=EVENT_OPERATION_COMPLETED,
            phase="done",
            status="completed",
        )
        assert event.content_light_guarantee is True

        d = event.model_dump(mode="json", exclude_none=True)
        assert "access_token" not in d
        assert "refresh_token" not in d
        assert "stdout" not in d
        assert "stderr" not in d
        assert "prompt" not in d

    def test_build_with_progress_bar(self):
        event = build_progress_event(
            operation_id="op_2",
            event_type=EVENT_OPERATION_PROGRESS,
            phase="processing",
            progress_current=3,
            progress_total=10,
            percent=30.0,
        )
        assert event.progress_current == 3
        assert event.progress_total == 10
        assert event.percent == 30.0

    def test_build_with_warnings(self):
        event = build_progress_event(
            operation_id="op_3",
            event_type=EVENT_OPERATION_WARNING,
            phase="check",
            status="warning",
            warnings=["Disk space low"],
        )
        assert event.warnings == ["Disk space low"]

    def test_build_with_output_refs(self):
        event = build_progress_event(
            operation_id="op_4",
            event_type=EVENT_OPERATION_COMPLETED,
            phase="done",
            status="completed",
            output_refs=["docs/report.md"],
        )
        assert event.output_refs == ["docs/report.md"]

    def test_progress_event_sha256_deterministic(self):
        # Build a fixed event — SHA256 must be deterministic for same fields
        fixed = ProgressEvent(
            event_id="pe_fixed",
            operation_id="op_fixed",
            event_type=EVENT_OPERATION_COMPLETED,
            phase="done",
            status="completed",
            message="All good",
            content_light_guarantee=True,
        )
        h1 = progress_event_sha256(fixed)
        h2 = progress_event_sha256(fixed)
        assert h1 == h2

    def test_progress_event_sha256_deterministic_with_warnings(self):
        fixed = ProgressEvent(
            event_id="pe_warn",
            operation_id="op_warn",
            event_type=EVENT_OPERATION_WARNING,
            phase="check",
            status="warning",
            warnings=["Issue"],
            content_light_guarantee=True,
        )
        h1 = progress_event_sha256(fixed)
        h2 = progress_event_sha256(fixed)
        assert h1 == h2


# ── ProgressEventBuffer ──


class TestProgressEventBuffer:
    def test_push_and_recent(self):
        buffer = ProgressEventBuffer(max_events=10)
        assert len(buffer) == 0
        assert buffer.recent() == []

        e1 = build_progress_event(
            operation_id="op1", event_type=EVENT_OPERATION_STARTED, phase="start"
        )
        e2 = build_progress_event(
            operation_id="op1",
            event_type=EVENT_OPERATION_COMPLETED,
            phase="end",
            status="completed",
        )
        buffer.push(e1)
        buffer.push(e2)
        assert len(buffer) == 2
        assert len(buffer.recent(10)) == 2

    def test_buffer_bounded(self):
        buffer = ProgressEventBuffer(max_events=3)
        for i in range(10):
            e = build_progress_event(
                operation_id=f"op{i}",
                event_type=EVENT_OPERATION_STARTED,
                phase=f"step{i}",
            )
            buffer.push(e)
        assert len(buffer) == 3
        assert buffer.recent()[0]["phase"] == "step7"

    def test_clear(self):
        buffer = ProgressEventBuffer()
        e = build_progress_event(
            operation_id="op1", event_type=EVENT_OPERATION_STARTED, phase="start"
        )
        buffer.push(e)
        assert len(buffer) == 1
        buffer.clear()
        assert len(buffer) == 0


# ── Intent Wire Tests ──


class TestIntentProgressEvents:
    def test_intent_execution_emits_started_via_emitter(self):
        """Test that execute_desktop_intent calls the progress_emitter."""
        events: list[dict[str, Any]] = []

        def emitter(event_data: dict[str, Any]) -> None:
            events.append(event_data)

        result = execute_desktop_intent(
            _valid_request("refresh_projection"), progress_emitter=emitter
        )
        assert result["status"] in {"completed", "failed"}

        # Should have at least a started event
        started_events = [
            e for e in events if e.get("event_type") == EVENT_OPERATION_STARTED
        ]
        assert len(started_events) >= 1

        # Should have a completed or failed event
        terminal_events = [
            e
            for e in events
            if e.get("event_type")
            in (EVENT_OPERATION_COMPLETED, EVENT_OPERATION_FAILED)
        ]
        assert len(terminal_events) >= 1

    def test_unknown_intent_emits_refused(self):
        events: list[dict[str, Any]] = []

        def emitter(event_data: dict[str, Any]) -> None:
            events.append(event_data)

        result = execute_desktop_intent(
            _valid_request("nonexistent_intent"), progress_emitter=emitter
        )
        assert result["status"] == "refused"

        refused_events = [
            e for e in events if e.get("event_type") == EVENT_OPERATION_REFUSED
        ]
        assert len(refused_events) >= 1

    def test_protected_intent_emits_refused(self):
        from rig_relay.desktop.intents import PROTECTED_INTENTS

        events: list[dict[str, Any]] = []

        def emitter(event_data: dict[str, Any]) -> None:
            events.append(event_data)

        protected_name = next(iter(PROTECTED_INTENTS))
        result = execute_desktop_intent(
            _valid_request(protected_name), progress_emitter=emitter
        )
        assert result["status"] == "refused"

        refused_events = [
            e for e in events if e.get("event_type") == EVENT_OPERATION_REFUSED
        ]
        assert len(refused_events) >= 1

    def test_progress_event_content_light_in_emitter(self):
        """Verify emitted progress events have content_light_guarantee=True."""
        events: list[dict[str, Any]] = []

        def emitter(event_data: dict[str, Any]) -> None:
            events.append(event_data)

        execute_desktop_intent(
            _valid_request("refresh_projection"), progress_emitter=emitter
        )

        for ev in events:
            assert ev.get("content_light_guarantee") is True
            assert "access_token" not in str(ev)
            assert "refresh_token" not in str(ev)


# ── WebSocket Broadcast (integration) ──


class TestWebSocketProgressBroadcast:
    @pytest.mark.asyncio
    async def test_authenticated_client_receives_progress_event(
        self, unused_tcp_port: int
    ):
        import websockets

        from rig_relay.desktop.websocket_server import (
            DEFAULT_HOST,
            ProjectionWebSocketServer,
        )

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            # Emit a progress event
            event_data = build_progress_event(
                operation_id="test_ws_op",
                event_type=EVENT_OPERATION_STARTED,
                phase="ws_test",
                message="WS test event",
            ).model_dump(mode="json", exclude_none=True)

            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Authenticate
                await ws.send(json.dumps({"type": "auth", "token": "test-token"}))
                auth_resp = json.loads(await ws.recv())
                assert auth_resp["type"] == "auth_ok"

                # Broadcast progress event
                await server.broadcast_progress_event(event_data)

                # Receive it
                msg = json.loads(await ws.recv())
                assert msg["type"] == "progress_event"
                assert msg["data"]["event_type"] == EVENT_OPERATION_STARTED
                assert msg["data"]["operation_id"] == "test_ws_op"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_authenticated_client_can_request_events(self, unused_tcp_port: int):
        import websockets

        from rig_relay.desktop.websocket_server import (
            DEFAULT_HOST,
            ProjectionWebSocketServer,
        )

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            # Push an event before client connects
            event_data = build_progress_event(
                operation_id="pre_op",
                event_type=EVENT_OPERATION_COMPLETED,
                phase="pre",
                status="completed",
                message="Pre-existing event",
            ).model_dump(mode="json", exclude_none=True)
            await server.broadcast_progress_event(event_data)

            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                await ws.send(json.dumps({"type": "auth", "token": "test-token"}))
                auth_resp = json.loads(await ws.recv())
                assert auth_resp["type"] == "auth_ok"

                # Request progress events
                await ws.send(json.dumps({"type": "get_progress_events", "count": 10}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "progress_events"
                assert len(resp["events"]) >= 1
                assert resp["events"][0]["operation_id"] == "pre_op"
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_unauthenticated_client_blocked(self, unused_tcp_port: int):
        import websockets

        from rig_relay.desktop.websocket_server import (
            DEFAULT_HOST,
            ProjectionWebSocketServer,
        )

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="secret", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(
                f"ws://{DEFAULT_HOST}:{unused_tcp_port}"
            ) as ws:
                # Send get_progress_events without auth
                await ws.send(json.dumps({"type": "get_progress_events"}))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "auth_required"
        finally:
            await server.close()
