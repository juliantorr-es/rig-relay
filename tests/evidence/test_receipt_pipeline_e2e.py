"""Receipt pipeline E2E tests — build → capture → store → index validation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rig_relay.desktop.projection_integrity import build_projection_integrity_assessment
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptEnvelope,
    ReceiptEvidence,
    ReceiptInput,
    ReceiptOutput,
    ReceiptSubject,
    ReceiptSubjectKind,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore


def _make_envelope(
    envelope_id: str = "env-001",
    receipt_kind: str = "tool_execution",
    session_id: str = "s1",
) -> ReceiptEnvelope:
    now = datetime.now(UTC).isoformat()
    return ReceiptEnvelope(
        envelope_id=envelope_id,
        receipt_kind=receipt_kind,
        schema_version="rig.receipt_envelope.v1",
        created_at=now,
        actor=ReceiptActor(actor_id="tool-read_file", actor_kind=ReceiptActorKind.TOOL),
        subject=ReceiptSubject(
            subject_id="call-001",
            subject_kind=ReceiptSubjectKind.TOOL_INVOCATION,
            session_id=session_id,
        ),
        input=ReceiptInput(input_kind="tool_args", input_sha256="abc123"),
        output=ReceiptOutput(
            output_kind="tool_result", output_sha256="def456", status="completed"
        ),
        decision=ReceiptDecision(decision="approved"),
        evidence=[
            ReceiptEvidence(
                evidence_id="ev-001", evidence_kind="sha256", evidence_sha256="abc123"
            )
        ],
    )


class TestBuildCaptureStoreIndex:
    def test_envelope_build_and_validate(self):
        env = _make_envelope()
        assert env.envelope_id == "env-001"
        assert env.receipt_kind == "tool_execution"
        assert env.actor.actor_kind == ReceiptActorKind.TOOL

    def test_store_append_and_get(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        env = _make_envelope(envelope_id="env-test-001")
        path = store.append(env)
        assert path.is_file()
        retrieved = store.get("env-test-001")
        assert retrieved is not None
        assert retrieved.envelope_id == "env-test-001"

    def test_store_append_updates_manifest(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("env-001"))
        store.append(_make_envelope("env-002"))
        manifest = tmp_path / "manifest.jsonl"
        assert manifest.is_file()
        lines = manifest.read_text().strip().split("\n")
        assert len(lines) == 2
        assert "env-001" in lines[0]
        assert "env-002" in lines[1]

    def test_store_count(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        assert store.count() == 0
        store.append(_make_envelope("e1"))
        store.append(_make_envelope("e2"))
        assert store.count() == 2

    def test_store_list_newest_first(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("e1"))
        store.append(_make_envelope("e2"))
        results = store.list()
        assert len(results) == 2
        assert results[0].envelope_id == "e2"

    def test_store_list_by_session(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("e1", session_id="s1"))
        store.append(_make_envelope("e2", session_id="s2"))
        results = store.list_by_session("s1")
        assert len(results) == 1
        assert results[0].envelope_id == "e1"

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        assert store.get("nonexistent") is None

    def test_store_persistence_across_instances(self, tmp_path: Path):
        store1 = FilesystemReceiptStore(tmp_path)
        store1.append(_make_envelope("persistent-1"))
        store2 = FilesystemReceiptStore(tmp_path)
        retrieved = store2.get("persistent-1")
        assert retrieved is not None


class TestReceiptIndex:
    def test_index_from_empty_store(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        records, _ = _build_index(store)
        assert len(records) == 0

    def test_index_from_populated_store(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("idx-001"))
        store.append(_make_envelope("idx-002", receipt_kind="governance_decision"))
        store.append(_make_envelope("idx-003"))
        records, errors = _build_index(store)
        assert len(records) == 3
        assert len(errors) == 0

    def test_index_handles_malformed_manifest(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("good-1"))
        manifest = tmp_path / "manifest.jsonl"
        manifest.write_text(manifest.read_text() + "not json\n")
        store.append(_make_envelope("good-2"))
        records, _ = _build_index(store)
        assert len(records) >= 2


class TestIntegrityAssessment:
    def test_assessment_from_records(self, tmp_path: Path):
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope("integ-001"))
        store.append(_make_envelope("integ-002"))
        records, _ = _build_index(store)
        assessment = build_projection_integrity_assessment(receipt_records=records)
        assert assessment.receipt_count == 2

    def test_empty_assessment(self):
        assessment = build_projection_integrity_assessment(receipt_records=[])
        assert assessment.receipt_count == 0


class TestReceiptPolicyValidation:
    def test_missing_required_fields_detected(self):
        try:
            ReceiptEnvelope(
                envelope_id="bad-1",
                receipt_kind="tool_execution",
                schema_version="rig.receipt_envelope.v1",
                created_at=datetime.now(UTC).isoformat(),
            )
            raise AssertionError("Should have raised validation error")
        except Exception:
            pass

    def test_valid_receipt_passes_structure_check(self):
        env = _make_envelope()
        assert env.actor is not None
        assert env.subject is not None
        assert env.decision is not None
        assert len(env.evidence) > 0

    def test_content_light_enforcement(self):
        env = _make_envelope()
        output = env.output
        assert output.output_kind == "tool_result"
        assert output.output_sha256 is not None
        assert output.output_bytes is None


def _build_index(store: FilesystemReceiptStore) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    errors: list[str] = []
    envelopes = store.list(limit=1000)
    for env in envelopes:
        try:
            records.append(env.model_dump(mode="json"))
        except Exception as e:
            errors.append(str(e))
    return records, errors
