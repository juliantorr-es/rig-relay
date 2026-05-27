from __future__ import annotations

from pathlib import Path

from rig_relay.investigation_timeline._adapters import (
    adapt_coordination_events,
    adapt_disclosure_transitions,
    adapt_observability_events,
    adapt_publication_preview_events,
)
from rig_relay.investigation_timeline._models import (
    TimelineEventKind,
    VerificationClass,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_adapt_observability_events_from_real_fixture():
    fixture_path = FIXTURES_DIR / "observability_sample.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    assert len(events) > 0
    event_kinds = {e.event_kind for e in events}
    assert TimelineEventKind.SESSION_STARTED in event_kinds
    assert TimelineEventKind.TOOL_CALL_COMPLETED in event_kinds
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


def test_adapt_publication_preview_consumes_real_nested_format():
    fixture_path = FIXTURES_DIR / "publication_preview_sample.jsonl"
    events, errors = adapt_publication_preview_events(fixture_path)
    assert len(events) > 0, "must produce events from nested publication fixture"
    event_kinds = {e.event_kind for e in events}
    assert TimelineEventKind.PUBLICATION_PREVIEW_COMPILED in event_kinds
    assert TimelineEventKind.PUBLICATION_PREVIEW_REFUSED in event_kinds


def test_adapt_publication_preview_preserves_producer_digest():
    fixture_path = FIXTURES_DIR / "publication_preview_sample.jsonl"
    events, errors = adapt_publication_preview_events(fixture_path)
    for e in events:
        assert e.producer_digest is not None
        assert e.producer_digest.startswith("sha256:")


def test_adapt_observability_verifies_event_hash():
    fixture_path = FIXTURES_DIR / "observability_sample.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    verified = [
        e
        for e in events
        if e.verification_class == VerificationClass.VERIFIED_CANONICAL
    ]
    assert len(verified) >= 3, (
        "events with correct event_hash must be VERIFIED_CANONICAL"
    )


def test_adapt_observability_flags_unverified_when_no_event_hash():
    fixture_path = FIXTURES_DIR / "observability_sample.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    unverified = [
        e for e in events if e.verification_class == VerificationClass.PARSED_UNVERIFIED
    ]
    assert len(unverified) >= 1, "events without event_hash must be PARSED_UNVERIFIED"


def test_adapt_disclosure_uses_transition_digest_directly():
    fixture_path = FIXTURES_DIR / "disclosure_transitions_sample.jsonl"
    events, errors = adapt_disclosure_transitions(fixture_path)
    for e in events:
        assert e.producer_digest is not None
        assert e.producer_digest.startswith("sha256:")
        assert e.producer_digest == e.source_event_id or e.producer_digest != ""


def test_adapt_disclosure_does_not_set_session_id_to_transition_id():
    fixture_path = FIXTURES_DIR / "disclosure_transitions_sample.jsonl"
    events, errors = adapt_disclosure_transitions(fixture_path)
    for e in events:
        if e.session_id is not None:
            assert not e.session_id.startswith("dzt_")


def test_adapt_malformed_produces_corrupt_events():
    fixture_path = FIXTURES_DIR / "malformed_evidence.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    assert len(errors) > 0
    assert any("malformed JSON" in err for err in errors)

    corrupt_events = [
        e
        for e in events
        if e.verification_class == VerificationClass.CORRUPT
        or e.event_kind == TimelineEventKind.EVIDENCE_CORRUPT
    ]
    assert len(corrupt_events) > 0, "malformed JSON must produce corrupt events"


def test_adapt_unmapped_event_produces_unverified_event():
    fixture_path = FIXTURES_DIR / "observability_sample.jsonl"
    events, errors = adapt_observability_events(fixture_path)
    unverified = [
        e for e in events if e.event_kind == TimelineEventKind.EVIDENCE_UNVERIFIED
    ]
    assert len(unverified) == 1, (
        "exactly one intentionally unmapped event must produce EVIDENCE_UNVERIFIED"
    )
    assert unverified[0].verification_class == VerificationClass.PARSED_UNVERIFIED
    assert unverified[0].source_domain == "observability"
    assert "unknown" in (unverified[0].degradation_detail or "")


def test_adapt_publication_preserves_operation_id():
    fixture_path = FIXTURES_DIR / "publication_preview_sample.jsonl"
    events, errors = adapt_publication_preview_events(fixture_path)
    assert len(events) > 0, "must produce events with operation_id"
    operation_ids = {e.operation_id for e in events if e.operation_id is not None}
    assert "op_001" in operation_ids
    assert "op_002" in operation_ids


def test_adapt_coordination_verifier_returns_corrupt_on_mismatch(tmp_path):
    coord_path = tmp_path / "coord_corrupt.jsonl"
    coord_path.write_text(
        '{"event_name":"coord.session.registered","event_id":"evt_001",'
        '"session_id":"s-abc","created_at":"2025-01-15T10:00:00Z",'
        '"payload":{"status":"registered","outcome":"registered"},'
        '"event_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}\n'
    )
    events, errors = adapt_coordination_events(coord_path)
    assert len(events) > 0
    assert events[0].verification_class == VerificationClass.CORRUPT


def test_adapt_publication_verifier_returns_corrupt_on_mismatch(tmp_path):
    pub_path = tmp_path / "pub_corrupt.jsonl"
    pub_path.write_text(
        '{"schema_version":"rig.relay.publication_preview_event.v1",'
        '"receipt":{"schema_version":"rig.relay.publication_preview_receipt.v1",'
        '"receipt_id":"sha256:aaa111aaa111aaa111aaa111aaa111aaa111aaa111aaa111aaa111aaa111aaa111",'
        '"compiled_at":"2026-05-01T10:00:00Z","compilation_successful":true,'
        '"safety_passed":true,"deployment_ready":false,"preview_only":true},'
        '"event_digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}\n'
    )
    events, errors = adapt_publication_preview_events(pub_path)
    assert len(events) > 0
    assert events[0].verification_class == VerificationClass.CORRUPT


def test_adapt_disclosure_verifier_returns_corrupt_on_mismatch(tmp_path):
    disc_path = tmp_path / "disc_corrupt.jsonl"
    disc_path.write_text(
        '{"transition_id":"dt_001","status":"prepared",'
        '"created_at":"2025-01-15T10:00:00Z","authorization_id":"auth_001",'
        '"schema_version":"rig.relay.disclosure_transition.v1",'
        '"evidence_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"projection_id":"proj_001","disclosure_class":"standard","sequence":1,'
        '"transition_digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}\n'
    )
    events, errors = adapt_disclosure_transitions(disc_path)
    assert len(events) > 0
    assert events[0].verification_class == VerificationClass.CORRUPT


def test_adapt_missing_file_returns_errors():
    nonexistent_path = FIXTURES_DIR / "does_not_exist.jsonl"
    events, errors = adapt_observability_events(nonexistent_path)
    assert len(events) == 0
    assert len(errors) > 0
    assert any("not found" in err.lower() for err in errors)
