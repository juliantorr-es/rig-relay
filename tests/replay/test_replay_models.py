"""Tests for replay models."""

from __future__ import annotations

from rig_relay.replay.models import (
    ReplayConflictType,
    ReplayCursor,
    ReplayEvent,
    ReplayEventKind,
    ReplayFrame,
    ReplayIntegrityFinding,
    ReplayIntegritySeverity,
    ReplayResult,
    ReplayState,
)


class TestReplayEvent:
    def test_create(self) -> None:
        e = ReplayEvent(
            event_id="e1", sequence=1, event_kind=ReplayEventKind.RECEIPT,
            event_name="rig.relay.tool_receipt.captured", session_id="s1",
            created_at="2026-01-01T00:00:00", tool_name="bash",
        )
        assert e.event_id == "e1"
        assert e.sequence == 1
        assert e.tool_name == "bash"

    def test_ordering_by_sequence(self) -> None:
        e1 = ReplayEvent(event_id="a", sequence=1, event_kind=ReplayEventKind.RECEIPT,
                         event_name="x", session_id="s1", created_at="2026-01-01T00:00:00")
        e2 = ReplayEvent(event_id="b", sequence=2, event_kind=ReplayEventKind.RECEIPT,
                         event_name="x", session_id="s1", created_at="2026-01-01T00:00:00")
        assert e1 < e2

    def test_kind_from_event_name(self) -> None:
        from rig_relay.replay.engine import _event_kind_from_event_name
        assert _event_kind_from_event_name("rig.relay.tool_receipt.captured") == ReplayEventKind.RECEIPT
        assert _event_kind_from_event_name("rig.relay.governance.decision") == ReplayEventKind.GOVERNANCE_DECISION
        assert _event_kind_from_event_name("rig.relay.session.started") == ReplayEventKind.SESSION_EVENT
        assert _event_kind_from_event_name("random_event") == ReplayEventKind.UNKNOWN


class TestReplayFrame:
    def test_first_and_last_sequence(self) -> None:
        e1 = ReplayEvent(event_id="a", sequence=1, event_kind=ReplayEventKind.RECEIPT,
                         event_name="x", session_id="s1", created_at="")
        e2 = ReplayEvent(event_id="b", sequence=3, event_kind=ReplayEventKind.RECEIPT,
                         event_name="x", session_id="s1", created_at="")
        frame = ReplayFrame(frame_index=0, events=[e1, e2])
        assert frame.first_sequence == 1
        assert frame.last_sequence == 3

    def test_empty_frame_sequences(self) -> None:
        frame = ReplayFrame(frame_index=0)
        assert frame.first_sequence is None
        assert frame.last_sequence is None


class TestReplayCursor:
    def test_default_state(self) -> None:
        c = ReplayCursor()
        assert c.current_frame_index == 0
        assert c.can_go_back is False
        assert c.can_go_forward is False

    def test_navigation_with_frames(self) -> None:
        result = ReplayResult(
            replay_id="r1", session_id="s1",
            frames=[ReplayFrame(frame_index=0), ReplayFrame(frame_index=1)],
        )
        assert result.cursor.can_go_forward is True
        assert result.cursor.can_go_back is False

    def test_current_frame(self) -> None:
        f0 = ReplayFrame(frame_index=0, events=[ReplayEvent(
            event_id="a", sequence=0, event_kind=ReplayEventKind.RECEIPT,
            event_name="x", session_id="s1", created_at="")])
        f1 = ReplayFrame(frame_index=1)
        result = ReplayResult(replay_id="r1", session_id="s1", frames=[f0, f1])
        assert result.current_frame is f0
        result.cursor.current_frame_index = 1
        assert result.current_frame is f1


class TestReplayIntegrityFinding:
    def test_severity_comparison(self) -> None:
        e = ReplayIntegrityFinding(
            finding_id="f1", severity=ReplayIntegritySeverity.ERROR, message="bad"
        )
        assert e.severity == ReplayIntegritySeverity.ERROR

    def test_all_passed_no_critical(self) -> None:
        result = ReplayResult(
            replay_id="r1", session_id="s1",
            findings=[
                ReplayIntegrityFinding(
                    finding_id="f1", severity=ReplayIntegritySeverity.INFO, message="ok"
                ),
            ],
        )
        assert result.all_passed is True

    def test_all_passed_with_critical(self) -> None:
        result = ReplayResult(
            replay_id="r1", session_id="s1",
            findings=[
                ReplayIntegrityFinding(
                    finding_id="f2", severity=ReplayIntegritySeverity.ERROR, message="bad"
                ),
            ],
        )
        assert result.all_passed is False


class TestReplayState:
    def test_state_values(self) -> None:
        assert ReplayState.PENDING.value == "pending"
        assert ReplayState.COMPLETE.value == "complete"
        assert ReplayState.FAILED.value == "failed"


class TestReplayConflictType:
    def test_values(self) -> None:
        assert ReplayConflictType.SEQUENCE_GAP.value == "sequence_gap"
        assert ReplayConflictType.DUPLICATE_SEQUENCE.value == "duplicate_sequence"
