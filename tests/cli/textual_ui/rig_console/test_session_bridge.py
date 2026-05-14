"""Tests for the Rig Console compatibility bridge."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rig_relay.evidence.receipt_store import FilesystemReceiptStore
from vibe.cli.textual_ui.rig_console.session_bridge import (
    _ITEMS_MAX,
    CodingSessionBridge,
    FixtureSessionAdapter,
    Subscription,
)
from vibe.cli.textual_ui.rig_console.session_events import (
    CodingSessionEvents,
    CodingTranscriptItemProjection,
)
from vibe.core.types import AssistantEvent, UserMessageEvent


class TestCodingSessionBridge:
    @pytest.mark.asyncio
    async def test_submit_user_message_starts_background_turn(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()

        class FakeLoop:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.telemetry_client = MagicMock()

            async def __aenter__(self) -> FakeLoop:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def aclose(self) -> None:
                return None

            def emit_new_session_telemetry(self) -> None:
                return None

            async def act(self, text: str, client_message_id: str | None = None):
                yield UserMessageEvent(content=text, message_id="msg-1")
                yield AssistantEvent(content="assistant reply", message_id="msg-2")

        with patch(
            "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", FakeLoop
        ):
            result = await bridge.submit_user_message("hello")

            assert result.accepted is True
            assert result.status == "running"
            assert bridge.is_turn_active is True

            await bridge.wait_for_turn()

            assert bridge.turn_status == "completed"
            assert bridge.is_turn_active is False

            events = await bridge.events_since(None)
            assert len(events.items) >= 3
            assert events.items[0].kind == "user_message"
            assert events.items[1].kind == "assistant_message"
            assert events.items[2].kind == "turn_status"
            assert events.items[2].status == "completed"

    @pytest.mark.asyncio
    async def test_events_since_returns_content_light_events(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()

        class FakeLoop:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.telemetry_client = MagicMock()

            async def __aenter__(self) -> FakeLoop:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def aclose(self) -> None:
                return None

            def emit_new_session_telemetry(self) -> None:
                return None

            async def act(self, text: str, client_message_id: str | None = None):
                yield UserMessageEvent(content=text, message_id="msg-1")
                yield AssistantEvent(content="assistant reply", message_id="msg-2")

        with patch(
            "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", FakeLoop
        ):
            result = await bridge.submit_user_message("hello")
            assert result.accepted is True

            await bridge.wait_for_turn()

            events = await bridge.events_since(None)
            assert isinstance(events, CodingSessionEvents)
            assert events.items[0].body_text == "hello"

    @pytest.mark.asyncio
    async def test_submit_user_message_records_failure_in_background(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()

        class FakeLoop:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.telemetry_client = MagicMock()

            async def __aenter__(self) -> FakeLoop:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def aclose(self) -> None:
                return None

            def emit_new_session_telemetry(self) -> None:
                return None

            async def act(self, text: str, client_message_id: str | None = None):
                if False:
                    yield UserMessageEvent(content=text, message_id="msg-1")
                raise RuntimeError("missing backend")

        with patch(
            "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", FakeLoop
        ):
            result = await bridge.submit_user_message("hello")

            assert result.accepted is True
            assert result.status == "running"

            await bridge.wait_for_turn()

            assert bridge.turn_status == "failed"
            events = await bridge.events_since(None)
            assert any(e.kind == "turn_status" for e in events.items)

    @pytest.mark.asyncio
    async def test_cancel_turn_during_background_task(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()

        class FakeLoop:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.telemetry_client = MagicMock()

            async def __aenter__(self) -> FakeLoop:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def aclose(self) -> None:
                return None

            def emit_new_session_telemetry(self) -> None:
                return None

            async def act(self, text: str, client_message_id: str | None = None):
                yield UserMessageEvent(content=text, message_id="msg-1")
                await asyncio.sleep(10)

        with patch(
            "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", FakeLoop
        ):
            result = await bridge.submit_user_message("hello")

            assert result.accepted is True
            assert bridge.is_turn_active is True

            await bridge.cancel_turn()

            assert bridge.turn_status == "cancelled"
            assert bridge.is_turn_active is False

    @pytest.mark.asyncio
    async def test_refuses_when_turn_already_active(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()

        class FakeLoop:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.telemetry_client = MagicMock()

            async def __aenter__(self) -> FakeLoop:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def aclose(self) -> None:
                return None

            def emit_new_session_telemetry(self) -> None:
                return None

            async def act(self, text: str, client_message_id: str | None = None):
                yield UserMessageEvent(content=text, message_id="msg-1")
                await asyncio.sleep(10)

        with patch(
            "vibe.cli.textual_ui.rig_console.session_bridge.AgentLoop", FakeLoop
        ):
            result1 = await bridge.submit_user_message("hello")
            assert result1.accepted is True

            result2 = await bridge.submit_user_message("world")
            assert result2.accepted is False
            assert "already active" in (result2.refusal_reason or "").lower()

            await bridge.cancel_turn()

    @pytest.mark.asyncio
    async def test_memory_cap_on_runtime_adapter(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()
        for i in range(_ITEMS_MAX + 20):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        assert len(bridge._items) <= _ITEMS_MAX
        assert bridge.dropped_count == 20

    @pytest.mark.asyncio
    async def test_events_since_after_pruning_runtime_adapter(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()
        for i in range(_ITEMS_MAX + 10):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        events = await bridge.events_since(None)
        assert len(events.items) == _ITEMS_MAX

    def test_subscribe_emits_items(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()
        received: list = []
        sub = bridge.subscribe(received.append)
        assert sub.active is True
        bridge._append("user_message", "User", body_text="test")
        assert len(received) >= 1

    def test_subscribe_unsubscribe_stops_emitting(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()
        received: list = []
        sub = bridge.subscribe(received.append)
        sub.unsubscribe()
        assert sub.active is False
        bridge._append("user_message", "User", body_text="test")
        assert len(received) == 0

    def test_subscription_idempotent_unsubscribe(self) -> None:
        sub = Subscription(lambda x: None)
        sub.unsubscribe()
        sub.unsubscribe()
        assert sub.active is False

    def test_content_light_item_projection(self) -> None:
        forbidden = {
            "stdout",
            "stderr",
            "file_contents",
            "chunk_text",
            "diff",
            "patch",
            "raw_prompt",
            "secret",
            "argv",
            "raw_output",
        }
        fields = set(CodingTranscriptItemProjection.model_fields.keys())
        assert not forbidden & fields

    @pytest.mark.asyncio
    async def test_empty_prompt_refused_immediately(self) -> None:
        bridge = CodingSessionBridge(session_id="s1")
        bridge.config = MagicMock()
        result = await bridge.submit_user_message("")
        assert result.accepted is False
        assert result.status == "refused"
        assert "Empty" in (result.refusal_reason or "")


class TestFixtureSessionAdapter:
    @pytest.mark.asyncio
    async def test_submit_user_message_is_deterministic(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        result = await bridge.submit_user_message("hello")
        assert result.accepted is True
        assert result.status == "completed"
        snapshot = await bridge.snapshot()
        assert snapshot.transcript.items[0].body_text == "hello"
        assert snapshot.transcript.items[1].body_text == "Fixture reply"

    @pytest.mark.asyncio
    async def test_turn_status_is_idle(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        assert bridge.is_turn_active is False
        assert bridge.turn_status == "idle"
        await bridge.cancel_turn()
        assert bridge.turn_status == "idle"

    @pytest.mark.asyncio
    async def test_empty_prompt_refused(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        result = await bridge.submit_user_message("")
        assert result.accepted is False

    @pytest.mark.asyncio
    async def test_memory_cap_prunes_old_items(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        count = _ITEMS_MAX + 50
        for i in range(count):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        assert len(bridge._items) <= _ITEMS_MAX
        assert bridge.dropped_count == 50

    @pytest.mark.asyncio
    async def test_dropped_count_increments_on_prune(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        count = _ITEMS_MAX + 10
        for i in range(count):
            bridge._append("user_message", "User", body_text=f"m-{i}")
        assert bridge.dropped_count == 10
        assert len(bridge._items) == _ITEMS_MAX

    @pytest.mark.asyncio
    async def test_events_since_still_works_after_pruning(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        count = _ITEMS_MAX + 10
        for i in range(count):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        events = await bridge.events_since(None)
        assert len(events.items) == _ITEMS_MAX

    @pytest.mark.asyncio
    async def test_events_since_respects_cursor_after_pruning(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        for i in range(_ITEMS_MAX + 5):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        events = await bridge.events_since(str(_ITEMS_MAX))
        assert len(events.items) == 5

    def test_item_projection_has_no_forbidden_raw_fields(self) -> None:
        forbidden = {
            "stdout",
            "stderr",
            "file_contents",
            "chunk_text",
            "diff",
            "patch",
            "raw_prompt",
            "secret",
            "argv",
            "raw_output",
        }
        fields = set(CodingTranscriptItemProjection.model_fields.keys())
        assert not forbidden & fields, f"Forbidden fields found: {forbidden & fields}"

    @pytest.mark.asyncio
    async def test_dropped_count_in_snapshot(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1")
        for i in range(_ITEMS_MAX + 20):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        snapshot = await bridge.snapshot()
        assert snapshot.transcript.dropped_count == 20
        assert len(snapshot.transcript.items) == _ITEMS_MAX


class TestCompactionReceipts:
    @pytest.mark.asyncio
    async def test_prune_emits_compaction_receipt(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        bridge = FixtureSessionAdapter(session_id="s1", receipt_store=store)
        count = _ITEMS_MAX + 10
        for i in range(count):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        receipts = store.list_by_session("s1", limit=10)
        compact = [r for r in receipts if r.receipt_kind == "compaction"]
        assert len(compact) >= 1
        assert compact[0].decision is not None
        assert "Dropped" in (compact[0].decision.rationale or "")

    @pytest.mark.asyncio
    async def test_runtime_adapter_emits_compaction_receipt(
        self, tmp_path: Path
    ) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        bridge = CodingSessionBridge(session_id="s1", receipt_store=store)
        for i in range(_ITEMS_MAX + 5):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        receipts = store.list_by_session("s1", limit=10)
        compact = [r for r in receipts if r.receipt_kind == "compaction"]
        assert len(compact) >= 1

    @pytest.mark.asyncio
    async def test_no_store_skips_compaction(self) -> None:
        bridge = FixtureSessionAdapter(session_id="s1", receipt_store=None)
        for i in range(_ITEMS_MAX + 10):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        assert bridge.dropped_count == 10
        assert len(bridge._items) == _ITEMS_MAX

    @pytest.mark.asyncio
    async def test_compaction_receipt_not_in_transcript(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        bridge = FixtureSessionAdapter(session_id="s1", receipt_store=store)
        for i in range(_ITEMS_MAX + 10):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        has_compaction_item = any(e.kind == "compaction" for e in bridge._items)
        assert has_compaction_item is False

    @pytest.mark.asyncio
    async def test_compaction_receipt_summarizes_kinds(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        bridge = FixtureSessionAdapter(session_id="s1", receipt_store=store)
        for i in range(_ITEMS_MAX + 5):
            bridge._append("user_message", "User", body_text=f"msg-{i}")
        bridge._append("assistant_message", "Assistant", body_text="reply")
        for i in range(5):
            bridge._append("tool_result", "Tool", body_text=f"result-{i}")
        receipts = store.list_by_session("s1", limit=10)
        compact = [r for r in receipts if r.receipt_kind == "compaction"]
        assert len(compact) >= 1
        decision = compact[0].decision
        assert decision is not None
        assert decision.rationale is not None
        assert "user_message" in decision.rationale
