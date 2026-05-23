"""Tests for audit trail models, store, schema, and content-light policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.evidence.audit_trail import (
    AuditActionKind,
    AuditDecisionKind,
    AuditEvent,
    AuditTrailStore,
)
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptActorTier,
    ReceiptEnvelope,
    ReceiptSubject,
    ReceiptSubjectKind,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.audit_event.v1.schema.json"
)

FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "content",
    "stdout",
    "stderr",
    "output_text",
    "diff",
    "patch",
    "snippet",
    "file_contents",
    "old_text",
    "new_text",
})


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_actor() -> ReceiptActor:
    return ReceiptActor(
        actor_id="relay-agent",
        actor_kind=ReceiptActorKind.AGENT,
        display_name="Relay Agent",
        is_human=False,
        authority_tier=ReceiptActorTier.ADMINISTRATIVE,
    )


@pytest.fixture
def sample_subject() -> ReceiptSubject:
    return ReceiptSubject(
        subject_id="evt-001",
        subject_kind=ReceiptSubjectKind.TOOL_INVOCATION,
        session_id="session-abc",
    )


@pytest.fixture
def sample_envelope(sample_actor, sample_subject) -> ReceiptEnvelope:
    return ReceiptEnvelope(
        envelope_id="env-001",
        receipt_kind="tool_invocation",
        actor=sample_actor,
        subject=sample_subject,
        created_at="2026-05-15T12:00:00+00:00",
    )


@pytest.fixture
def schema_dict() -> dict[str, Any]:
    schema = _load_json(AUDIT_SCHEMA_PATH)
    assert schema is not None, "Could not load audit event schema"
    return schema


@pytest.fixture
def store(tmp_path: Path) -> AuditTrailStore:
    return AuditTrailStore(tmp_path / "audit.jsonl")


# ── Model tests ────────────────────────────────────────────────────────


class TestAuditEventModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            AuditEvent.model_validate({
                "event_id": "e1",
                "sequence": 1,
                "timestamp": "now",
                "action": "receipt_created",
                "decision": "informational",
                "unknown": "x",
            })

    def test_minimal_valid(self) -> None:
        event = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-05-15T12:00:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        assert event.schema_version == "rig.relay.audit_event.v1"
        assert event.envelope_id is None
        assert event.envelope is None
        assert event.actor is None
        assert event.subject is None
        assert event.notes == []

    def test_full_with_envelope(
        self, sample_actor, sample_subject, sample_envelope
    ) -> None:
        event = AuditEvent(
            event_id="e2",
            sequence=2,
            timestamp="2026-05-15T12:01:00+00:00",
            workspace_id="ws-1",
            session_id="session-abc",
            actor=sample_actor,
            action=AuditActionKind.ENVELOPE_CREATED,
            subject=sample_subject,
            decision=AuditDecisionKind.COMPLETED,
            envelope_id="env-001",
            envelope=sample_envelope,
            evidence_sha256="abc123",
            notes=["Test note"],
        )
        dumped = event.model_dump(mode="json")
        assert dumped["schema_version"] == "rig.relay.audit_event.v1"
        assert dumped["envelope_id"] == "env-001"
        assert dumped["envelope"]["envelope_id"] == "env-001"
        assert dumped["actor"]["actor_id"] == "relay-agent"
        assert dumped["notes"] == ["Test note"]

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(AuditEvent.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)

    def test_dump_has_no_forbidden_fields(
        self, sample_actor, sample_subject, sample_envelope
    ) -> None:
        event = AuditEvent(
            event_id="e3",
            sequence=3,
            timestamp="2026-05-15T12:00:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.ALLOWED,
            actor=sample_actor,
            subject=sample_subject,
            envelope=sample_envelope,
        )
        dumped = event.model_dump(mode="json")

        def _check(val: Any, path: str) -> None:
            if isinstance(val, dict):
                for k, v in val.items():
                    assert k not in FORBIDDEN_RAW_FIELD_NAMES, (
                        f"Forbidden field '{k}' at {path}"
                    )
                    _check(v, f"{path}.{k}")
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    _check(item, f"{path}[{i}]")

        _check(dumped, "event")

    def test_enum_values_serialize_as_stable_strings(self) -> None:
        event = AuditEvent(
            event_id="e4",
            sequence=4,
            timestamp="2026-05-15T12:00:00+00:00",
            action=AuditActionKind.PROJECTION_BUILT,
            decision=AuditDecisionKind.COMPLETED,
        )
        dumped = event.model_dump(mode="json")
        assert dumped["action"] == "projection_built"
        assert dumped["decision"] == "completed"


# ── Store tests ───────────────────────────────────────────────────────


class TestAuditTrailStore:
    def test_append_creates_jsonl_file(self, store: AuditTrailStore) -> None:
        event = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-05-15T12:00:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        store.append(event)
        assert store.path.is_file()
        lines = store.path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_append_preserves_existing_and_adds_new(
        self, store: AuditTrailStore
    ) -> None:
        e1 = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="now",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        e2 = AuditEvent(
            event_id="e2",
            sequence=2,
            timestamp="now+1",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.ALLOWED,
        )
        store.append(e1)
        store.append(e2)
        lines = store.path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_read_events_returns_events_in_order(self, store: AuditTrailStore) -> None:
        e2 = AuditEvent(
            event_id="e2",
            sequence=2,
            timestamp="2026-05-15T12:02:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.ALLOWED,
        )
        e1 = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-05-15T12:01:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        # Append out of sequence order
        store.append(e2)
        store.append(e1)
        events, errors = store.read_events()
        assert errors == []
        assert len(events) == 2
        # Should be sorted by sequence
        assert events[0].event_id == "e1"
        assert events[1].event_id == "e2"

    def test_next_sequence_increments(self, store: AuditTrailStore) -> None:
        assert store.next_sequence() == 1
        store.append(
            AuditEvent(
                event_id="e1",
                sequence=1,
                timestamp="now",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.INFORMATIONAL,
            )
        )
        assert store.next_sequence() == 2
        store.append(
            AuditEvent(
                event_id="e2",
                sequence=2,
                timestamp="now+1",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.ALLOWED,
            )
        )
        assert store.next_sequence() == 3

    def test_malformed_line_returns_error_and_valid_lines_still_load(
        self, store: AuditTrailStore
    ) -> None:
        # Write a valid line, then a malformed line, then another valid line
        store.append(
            AuditEvent(
                event_id="e1",
                sequence=1,
                timestamp="now",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.INFORMATIONAL,
            )
        )
        # Inject malformed line via raw write
        with store.path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
        store.append(
            AuditEvent(
                event_id="e3",
                sequence=3,
                timestamp="now+2",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.ALLOWED,
            )
        )

        events, errors = store.read_events()
        assert len(errors) == 1
        assert "not valid json" in str(errors[0].message) or "line 2" in str(
            errors[0].message
        )
        assert len(events) == 2
        assert events[0].event_id == "e1"
        assert events[1].event_id == "e3"

    def test_empty_store_returns_empty(self, store: AuditTrailStore) -> None:
        events, errors = store.read_events()
        assert events == []
        assert errors == []

    def test_store_does_not_exist_returns_empty(self, tmp_path: Path) -> None:
        store = AuditTrailStore(tmp_path / "nonexistent" / "audit.jsonl")
        events, errors = store.read_events()
        assert events == []
        assert errors == []

    def test_latest_event_returns_last(self, store: AuditTrailStore) -> None:
        e1 = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="now",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        e2 = AuditEvent(
            event_id="e2",
            sequence=2,
            timestamp="now+1",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.ALLOWED,
        )
        store.append(e1)
        last = store.latest_event()
        assert last is not None
        assert last.event_id == "e1"
        store.append(e2)
        last2 = store.latest_event()
        assert last2 is not None
        assert last2.event_id == "e2"

    def test_latest_event_on_empty_store(self, store: AuditTrailStore) -> None:
        assert store.latest_event() is None

    def test_append_audit_event_auto_sequences(self, store: AuditTrailStore) -> None:
        event = store.append_audit_event(
            event_id="e1",
            action=AuditActionKind.PROJECTION_BUILT,
            decision=AuditDecisionKind.COMPLETED,
        )
        assert event.sequence == 1
        assert event.event_id == "e1"
        assert store.path.is_file()

    def test_append_audit_event_with_envelope(
        self, store: AuditTrailStore, sample_actor, sample_envelope
    ) -> None:
        event = store.append_audit_event(
            event_id="e2",
            action=AuditActionKind.ENVELOPE_CREATED,
            decision=AuditDecisionKind.COMPLETED,
            actor=sample_actor,
            envelope_id="env-001",
            envelope=sample_envelope,
            session_id="session-abc",
        )
        assert event.sequence == 1
        assert event.envelope_id == "env-001"
        assert event.envelope is not None

    def test_store_does_not_rewrite_or_truncate(self, store: AuditTrailStore) -> None:
        e1 = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="now",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        store.append(e1)
        content_before = store.path.read_text(encoding="utf-8")
        # Append same event again
        store.append(e1)
        content_after = store.path.read_text(encoding="utf-8")
        # Content should have grown, not been truncated
        assert len(content_after) > len(content_before)
        # First line should be preserved
        assert content_after.startswith(content_before.strip())

    def test_no_forbidden_fields_in_store_output(
        self, store: AuditTrailStore, sample_actor, sample_subject, sample_envelope
    ) -> None:
        store.append_audit_event(
            event_id="safe",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.ALLOWED,
            actor=sample_actor,
            subject=sample_subject,
            envelope=sample_envelope,
        )
        events, errors = store.read_events()
        assert errors == []
        assert len(events) == 1
        dumped = events[0].model_dump(mode="json")

        def _check(val: Any, path: str) -> None:
            if isinstance(val, dict):
                for k, v in val.items():
                    assert k not in FORBIDDEN_RAW_FIELD_NAMES, (
                        f"Forbidden field '{k}' at {path}"
                    )
                    _check(v, f"{path}.{k}")
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    _check(item, f"{path}[{i}]")

        _check(dumped, "event")

    def test_store_path_property(self, store: AuditTrailStore) -> None:
        assert store.path.name == "audit.jsonl"

    def test_empty_lines_are_skipped(self, store: AuditTrailStore) -> None:
        # Write a valid line, then an empty line, then another valid line
        store.append(
            AuditEvent(
                event_id="e1",
                sequence=1,
                timestamp="now",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.INFORMATIONAL,
            )
        )
        with store.path.open("a", encoding="utf-8") as f:
            f.write("\n")
            f.write("   \n")
        store.append(
            AuditEvent(
                event_id="e2",
                sequence=2,
                timestamp="now+1",
                action=AuditActionKind.RECEIPT_CREATED,
                decision=AuditDecisionKind.ALLOWED,
            )
        )
        events, errors = store.read_events()
        assert len(errors) == 0  # empty/whitespace lines should be skipped, not errors
        assert len(events) == 2


# ── Schema tests ──────────────────────────────────────────────────────


class TestAuditEventSchema:
    def test_schema_validates_minimal_event(self, schema_dict: dict[str, Any]) -> None:
        event = AuditEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-05-15T12:00:00+00:00",
            action=AuditActionKind.RECEIPT_CREATED,
            decision=AuditDecisionKind.INFORMATIONAL,
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_full_event(
        self, schema_dict: dict[str, Any], sample_actor, sample_subject, sample_envelope
    ) -> None:
        event = AuditEvent(
            event_id="e2",
            sequence=2,
            timestamp="2026-05-15T12:01:00+00:00",
            workspace_id="ws-1",
            session_id="session-abc",
            actor=sample_actor,
            action=AuditActionKind.ENVELOPE_CREATED,
            subject=sample_subject,
            decision=AuditDecisionKind.COMPLETED,
            envelope_id="env-001",
            envelope=sample_envelope,
            evidence_sha256="abc123",
            notes=["Test"],
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_top_level_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {
            "schema_version": "rig.relay.audit_event.v1",
            "event_id": "e1",
            "sequence": 1,
            "timestamp": "now",
            "action": "receipt_created",
            "decision": "informational",
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_rejects_invalid_action(self, schema_dict: dict[str, Any]) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {
            "schema_version": "rig.relay.audit_event.v1",
            "event_id": "e1",
            "sequence": 1,
            "timestamp": "now",
            "action": "not_a_real_action",
            "decision": "informational",
        }
        errors = list(validator.iter_errors(bad))
        assert any("not_a_real_action" in str(e.message) for e in errors)

    def test_schema_rejects_missing_required_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {"schema_version": "rig.relay.audit_event.v1"}
        errors = list(validator.iter_errors(bad))
        missing = [e.message for e in errors if "is a required property" in e.message]
        assert len(missing) >= 3

    def test_schema_has_no_forbidden_raw_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        from tests.evidence._helpers import check_schema_for_forbidden_fields

        check_schema_for_forbidden_fields(schema_dict)
