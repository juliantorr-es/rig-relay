from __future__ import annotations

from pathlib import Path

from rig_relay.investigation_timeline._adapters import (
    adapt_coordination_events,
    adapt_disclosure_transitions,
    adapt_observability_events,
    adapt_publication_preview_events,
)
from rig_relay.investigation_timeline._models import TimelineEventKind

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_adapt_observability_events_from_real_fixture():
    fixture_path = FIXTURES_DIR / "observability_sample.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    assert len(events) > 0
    event_kinds = {e.event_kind for e in events}
    assert TimelineEventKind.TOOL_CALL_COMPLETED in event_kinds
    assert TimelineEventKind.SESSION_STARTED in event_kinds
    assert TimelineEventKind.TOOL_CALL_REFUSED in event_kinds
    assert TimelineEventKind.TOOL_CALL_FAILED in event_kinds
    assert TimelineEventKind.SESSION_CLOSED in event_kinds


def test_adapt_coordination_events_from_real_fixture():
    fixture_path = FIXTURES_DIR / "coordination_events_sample.jsonl"
    events, errors = adapt_coordination_events(fixture_path)
    assert len(events) > 0
    event_kinds = {e.event_kind for e in events}
    assert TimelineEventKind.COORDINATION_TASK_CLAIMED in event_kinds
    assert TimelineEventKind.COORDINATION_PATH_RESERVED in event_kinds
    assert TimelineEventKind.COORDINATION_RESERVATION_REFUSED in event_kinds
    assert TimelineEventKind.COORDINATION_CONFLICT_REPORTED in event_kinds
    assert TimelineEventKind.COORDINATION_ARTIFACT_PUBLISHED in event_kinds
    assert TimelineEventKind.COORDINATION_HANDOFF_REQUESTED in event_kinds
    assert TimelineEventKind.COORDINATION_HANDOFF_ACCEPTED in event_kinds
    assert TimelineEventKind.COORDINATION_HANDOFF_REJECTED in event_kinds
    assert TimelineEventKind.SESSION_REGISTERED in event_kinds
    assert TimelineEventKind.SESSION_HEARTBEAT in event_kinds


def test_adapt_disclosure_transitions_from_real_fixture():
    fixture_path = FIXTURES_DIR / "disclosure_transitions_sample.jsonl"
    events, errors = adapt_disclosure_transitions(fixture_path)
    assert len(events) > 0
    event_kinds = {e.event_kind for e in events}
    assert TimelineEventKind.DISCLOSURE_TRANSITION_INITIATED in event_kinds
    assert TimelineEventKind.DISCLOSURE_TRANSITION_ADVANCED in event_kinds
    assert TimelineEventKind.DISCLOSURE_TRANSITION_COMPLETED in event_kinds
    assert TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED in event_kinds

    refused_events = [
        e
        for e in events
        if e.event_kind == TimelineEventKind.DISCLOSURE_TRANSITION_REFUSED
    ]
    assert len(refused_events) > 0
    refused_statuses = {e.status for e in refused_events}
    assert "refused" in refused_statuses or "conflict" in refused_statuses


def test_adapt_publication_preview_from_real_fixture():
    fixture_path = FIXTURES_DIR / "publication_preview_sample.jsonl"
    events, errors = adapt_publication_preview_events(fixture_path)
    assert len(events) > 0
    compiled_events = [
        e
        for e in events
        if e.event_kind == TimelineEventKind.PUBLICATION_PREVIEW_COMPILED
    ]
    refused_events = [
        e
        for e in events
        if e.event_kind == TimelineEventKind.PUBLICATION_PREVIEW_REFUSED
    ]
    assert len(compiled_events) > 0
    assert len(refused_events) > 0
    for e in compiled_events:
        assert e.outcome == "compiled"
    for e in refused_events:
        assert e.outcome == "refused"


def test_adapt_malformed_evidence_produces_errors():
    fixture_path = FIXTURES_DIR / "malformed_evidence.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    assert len(errors) > 0
    assert any("malformed JSON" in err for err in errors)
    assert len(events) > 0


def test_adapt_missing_file_returns_errors():
    nonexistent_path = FIXTURES_DIR / "does_not_exist.jsonl"
    events, errors = adapt_observability_events(nonexistent_path)
    assert len(events) == 0
    assert len(errors) > 0
    assert any("not found" in err.lower() for err in errors)
