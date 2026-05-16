"""Tests for the replay engine."""

from __future__ import annotations

from pathlib import Path

from rig_relay.replay.engine import (
    _build_event_from_observability,
    _check_duplicates,
    _frame_events,
    replay_session_from_observability,
    replay_session_from_receipt_index,
)
from rig_relay.replay.models import (
    ReplayEvent,
    ReplayEventKind,
    ReplayIntegritySeverity,
    ReplayResult,
    ReplayState,
)


class TestBuildEventFromObservability:
    def test_tool_receipt_event(self) -> None:
        line = (
            '{"event_id": "e1", "event_name": "rig.relay.tool_receipt.captured", '
            '"session_id": "s1", "created_at": "2026-01-01T00:00:00", '
            '"payload": {"tool_name": "bash", "receipt": {"status": "completed"}}}'
        )
        event = _build_event_from_observability(line, 0, "s1")
        assert event is not None
        assert event.event_kind == ReplayEventKind.RECEIPT
        assert event.tool_name == "bash"
        assert event.status == "completed"

    def test_malformed_json_returns_none(self) -> None:
        event = _build_event_from_observability("{not json", 0, "s1")
        assert event is None

    def test_unknown_event_name(self) -> None:
        line = '{"event_id": "e2", "event_name": "something.else", "session_id": "s1", "created_at": ""}'
        event = _build_event_from_observability(line, 0, "s1")
        assert event is not None
        assert event.event_kind == ReplayEventKind.UNKNOWN


class TestCheckDuplicates:
    def test_no_duplicates(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
            ),
            ReplayEvent(
                event_id="b",
                sequence=1,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
            ),
        ]
        findings = _check_duplicates(events)
        assert len(findings) == 0

    def test_duplicate_detected(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
            ),
            ReplayEvent(
                event_id="a",
                sequence=1,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
            ),
        ]
        findings = _check_duplicates(events)
        assert len(findings) >= 1
        assert findings[0].severity == ReplayIntegritySeverity.ERROR


class TestFrameEvents:
    def test_single_tool_frames(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            ),
            ReplayEvent(
                event_id="b",
                sequence=1,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            ),
        ]
        frames, findings = _frame_events(events)
        assert len(frames) == 1
        assert len(findings) == 0

    def test_multiple_tools_split(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            ),
            ReplayEvent(
                event_id="b",
                sequence=1,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="search_replace",
            ),
        ]
        frames, _findings = _frame_events(events)
        assert len(frames) == 2

    def test_sequence_gap_detected(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            ),
            ReplayEvent(
                event_id="b",
                sequence=5,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            ),
        ]
        _frames, findings = _frame_events(events)
        gap_findings = [f for f in findings if "Sequence gap" in f.message]
        assert len(gap_findings) >= 1

    def test_frame_hash_chain(self) -> None:
        events = [
            ReplayEvent(
                event_id="a",
                sequence=0,
                event_kind=ReplayEventKind.RECEIPT,
                event_name="x",
                session_id="s1",
                created_at="",
                tool_name="bash",
            )
        ]
        frames, _findings = _frame_events(events)
        assert len(frames) == 1
        assert frames[0].frame_hash is not None
        assert frames[0].previous_frame_hash is None


class TestReplaySessionFromObservability:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = replay_session_from_observability("s1", tmp_path / "nonexistent.jsonl")
        assert result.state == ReplayState.FAILED
        assert len(result.findings) >= 1

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        result = replay_session_from_observability("s1", f)
        assert result.state == ReplayState.COMPLETE
        assert result.total_events == 0

    def test_valid_events(self, tmp_path: Path) -> None:
        f = tmp_path / "events.jsonl"
        f.write_text(
            '{"event_id": "e1", "event_name": "rig.relay.tool_receipt.captured", '
            '"session_id": "s1", "created_at": "2026-01-01T00:00:00", '
            '"payload": {"tool_name": "bash", "receipt": {"status": "completed"}}}\n'
            '{"event_id": "e2", "event_name": "rig.relay.tool_receipt.captured", '
            '"session_id": "s1", "created_at": "2026-01-01T00:01:00", '
            '"payload": {"tool_name": "search_replace", "receipt": {"status": "completed"}}}\n',
            encoding="utf-8",
        )
        result = replay_session_from_observability("s1", f)
        assert result.state == ReplayState.COMPLETE
        assert result.total_events == 2
        assert len(result.frames) >= 1
        assert result.summary["total_events"] == 2

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "mixed.jsonl"
        f.write_text(
            '{"event_id": "e1", "event_name": "rig.relay.tool_receipt.captured", '
            '"session_id": "s1", "created_at": "", '
            '"payload": {"tool_name": "bash", "receipt": {"status": "ok"}}}\n'
            "{not valid json}\n"
            '{"event_id": "e2", "event_name": "rig.relay.tool_receipt.captured", '
            '"session_id": "s1", "created_at": "", '
            '"payload": {"tool_name": "validate", "receipt": {"status": "passed"}}}\n',
            encoding="utf-8",
        )
        result = replay_session_from_observability("s1", f)
        assert result.total_events == 2

    def test_replay_result_class(self) -> None:
        assert isinstance(ReplayResult, type)


class TestReplaySessionFromReceiptIndex:
    def test_empty_records(self) -> None:
        result = replay_session_from_receipt_index("s1", [])
        assert result.state == ReplayState.COMPLETE
        assert result.total_events == 0

    def test_single_record(self) -> None:
        from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord

        record = ToolReceiptIndexRecord(
            session_id="s1", tool_name="bash", status="completed", event_id="e1"
        )
        result = replay_session_from_receipt_index("s1", [record])
        assert result.total_events == 1
        assert len(result.frames) >= 1

    def test_multiple_records_frame_by_tool(self) -> None:
        from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord

        records = [
            ToolReceiptIndexRecord(
                session_id="s1", tool_name="bash", status="completed", event_id="e1"
            ),
            ToolReceiptIndexRecord(
                session_id="s1", tool_name="bash", status="completed", event_id="e2"
            ),
            ToolReceiptIndexRecord(
                session_id="s1",
                tool_name="search_replace",
                status="completed",
                event_id="e3",
            ),
        ]
        result = replay_session_from_receipt_index("s1", records)
        assert result.total_events == 3
        assert len(result.frames) >= 2
        assert result.summary["by_tool"].get("bash") == 2
        assert result.summary["by_tool"].get("search_replace") == 1
