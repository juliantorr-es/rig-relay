"""Tests for receipt envelope models, builder, schema, and content-light policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.evidence.receipt_envelope import (
    PLACEHOLDER_NO_RECEIPT,
    PLACEHOLDER_UNAVAILABLE,
    PLACEHOLDER_UNKNOWN,
    ReceiptActor,
    ReceiptActorKind,
    ReceiptActorTier,
    ReceiptDecision,
    ReceiptEnvelope,
    ReceiptEvidence,
    ReceiptEvidenceKind,
    ReceiptInput,
    ReceiptOutput,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENVELOPE_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.receipt_envelope.v1.schema.json"
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
        actor_id="rig-relay-cli",
        actor_kind=ReceiptActorKind.AGENT,
        display_name="Rig Relay CLI Agent",
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
def sample_decision() -> ReceiptDecision:
    return ReceiptDecision(
        decision="allowed", rationale="Tool invocation permitted", gate="tool_gate"
    )


@pytest.fixture
def schema_dict() -> dict[str, Any]:
    schema = _load_json(ENVELOPE_SCHEMA_PATH)
    assert schema is not None, "Could not load receipt envelope schema"
    return schema


# ── Model tests ───────────────────────────────────────────────────────


class TestReceiptActorModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptActor.model_validate({
                "actor_id": "x",
                "actor_kind": "human",
                "unknown": "y",
            })

    def test_minimal_construction(self) -> None:
        a = ReceiptActor(actor_id="sys", actor_kind=ReceiptActorKind.SYSTEM)
        assert a.actor_id == "sys"
        assert a.actor_kind == ReceiptActorKind.SYSTEM
        assert a.display_name is None
        assert a.is_human is False
        assert a.authority_tier == ReceiptActorTier.NONE

    def test_full_construction(self) -> None:
        a = ReceiptActor(
            actor_id="agent-1",
            actor_kind=ReceiptActorKind.AGENT,
            display_name="Agent 1",
            is_human=False,
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        )
        assert a.model_dump(mode="json")["actor_kind"] == "agent"

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptActor.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptSubjectModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptSubject.model_validate({
                "subject_id": "x",
                "subject_kind": "session",
                "unknown": "y",
            })

    def test_minimal_construction(self) -> None:
        s = ReceiptSubject(subject_id="s1", subject_kind=ReceiptSubjectKind.SESSION)
        assert s.session_id is None
        assert s.path is None

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptSubject.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptInputModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptInput.model_validate({"input_kind": "file", "unknown": "y"})

    def test_minimal_construction(self) -> None:
        i = ReceiptInput(input_kind="file")
        assert i.input_id is None
        assert i.input_sha256 is None
        assert i.input_bytes is None

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptInput.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptOutputModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptOutput.model_validate({"output_kind": "receipt", "unknown": "y"})

    def test_minimal_construction(self) -> None:
        o = ReceiptOutput(output_kind="receipt")
        assert o.status is None

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptOutput.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptEvidenceModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptEvidence.model_validate({"evidence_kind": "sha256", "unknown": "y"})

    def test_minimal_construction(self) -> None:
        e = ReceiptEvidence(evidence_kind=ReceiptEvidenceKind.SHA256)
        assert e.evidence_sha256 is None

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptEvidence.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptDecisionModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptDecision.model_validate({"decision": "allowed", "unknown": "y"})

    def test_minimal_construction(self) -> None:
        d = ReceiptDecision(decision="allowed")
        assert d.rationale is None
        assert d.gate is None

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptDecision.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)


class TestReceiptEnvelopeModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ReceiptEnvelope.model_validate({
                "envelope_id": "e1",
                "receipt_kind": "test",
                "actor": {"actor_id": "x", "actor_kind": "system"},
                "subject": {"subject_id": "s", "subject_kind": "session"},
                "evidence": [],
                "created_at": "now",
                "unknown": "y",
            })

    def test_minimal_valid(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e1",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert env.schema_version == "rig.relay.receipt_envelope.v1"
        assert env.input is None
        assert env.output is None
        assert env.decision is None
        assert env.evidence == []

    def test_full_construction(
        self,
        sample_actor: ReceiptActor,
        sample_subject: ReceiptSubject,
        sample_decision: ReceiptDecision,
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e2",
            receipt_kind="tool_invocation",
            actor=sample_actor,
            subject=sample_subject,
            input=ReceiptInput(input_kind="file", input_sha256="abc"),
            output=ReceiptOutput(output_kind="receipt", output_sha256="def"),
            decision=sample_decision,
            evidence=[
                ReceiptEvidence(
                    evidence_kind=ReceiptEvidenceKind.TOOL_RECEIPT,
                    evidence_sha256="abc123",
                )
            ],
            created_at="2026-05-15T12:00:00+00:00",
        )
        dumped = env.model_dump(mode="json")
        assert dumped["schema_version"] == "rig.relay.receipt_envelope.v1"
        assert dumped["input"]["input_sha256"] == "abc"
        assert dumped["output"]["output_sha256"] == "def"
        assert dumped["decision"]["decision"] == "allowed"
        assert len(dumped["evidence"]) == 1

    def test_has_no_forbidden_raw_fields(self) -> None:
        fields = set(ReceiptEnvelope.model_fields.keys())
        assert not (fields & FORBIDDEN_RAW_FIELD_NAMES)

    def test_envelope_dump_has_no_forbidden_fields(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e3",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        dumped = env.model_dump(mode="json")

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

        _check(dumped, "envelope")

    def test_enum_values_serialize_as_stable_strings(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e4",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        dumped = env.model_dump(mode="json")
        assert dumped["actor"]["actor_kind"] == "agent"
        assert dumped["subject"]["subject_kind"] == "tool_invocation"


# ── Builder tests ─────────────────────────────────────────────────────


class TestBuildReceiptEnvelope:
    def test_minimal_build(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = build_receipt_envelope(
            envelope_id="e1",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert env.envelope_id == "e1"
        assert env.receipt_kind == "test"
        assert env.evidence == []

    def test_hashes_payload_dict(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        payload = {"tool_name": "bash", "status": "success"}
        env = build_receipt_envelope(
            envelope_id="e2",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload=payload,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert len(env.evidence) == 1
        ev = env.evidence[0]
        assert ev.evidence_kind == ReceiptEvidenceKind.TOOL_RECEIPT
        assert ev.evidence_sha256 is not None
        assert len(ev.evidence_sha256) == 64

    def test_does_not_store_raw_payload(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        payload = {"tool_name": "bash", "stdout": "secret_data"}
        env = build_receipt_envelope(
            envelope_id="e3",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload=payload,
            created_at="2026-05-15T12:00:00+00:00",
        )
        dumped = env.model_dump(mode="json")
        # The raw payload should NOT appear anywhere in the dump
        raw_text = str(dumped)
        assert "secret_data" not in raw_text
        assert "stdout" not in dumped.get("evidence", [])

    def test_identical_payload_and_ids_give_stable_envelope(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        payload = {"tool_name": "bash", "status": "success"}
        e1 = build_receipt_envelope(
            envelope_id="stable",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload=payload,
            created_at="2026-05-15T12:00:00+00:00",
        )
        e2 = build_receipt_envelope(
            envelope_id="stable",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload=payload,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert e1.model_dump(mode="json") == e2.model_dump(mode="json")

    def test_different_payload_gives_different_hash(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        e1 = build_receipt_envelope(
            envelope_id="diff1",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload={"status": "success"},
            created_at="2026-05-15T12:00:00+00:00",
        )
        e2 = build_receipt_envelope(
            envelope_id="diff2",
            receipt_kind="tool_receipt",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload={"status": "failed"},
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert e1.evidence[0].evidence_sha256 != e2.evidence[0].evidence_sha256

    def test_accepts_model_payload(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        decision = ReceiptDecision(decision="allowed", rationale="test")
        env = build_receipt_envelope(
            envelope_id="model-payload",
            receipt_kind="governance_decision",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload=decision,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert len(env.evidence) == 1
        assert env.evidence[0].evidence_kind == ReceiptEvidenceKind.TOOL_RECEIPT

    def test_rejects_invalid_payload_type(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        with pytest.raises(
            TypeError, match="receipt_payload must be a dict or BaseModel"
        ):
            build_receipt_envelope(
                envelope_id="err",
                receipt_kind="tool_receipt",
                actor=sample_actor,
                subject=sample_subject,
                receipt_payload="not_a_dict",  # type: ignore[arg-type]
                created_at="2026-05-15T12:00:00+00:00",
            )

    def test_evidence_override_included(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        override = [
            ReceiptEvidence(
                evidence_kind=ReceiptEvidenceKind.SCHEMA,
                schema_version="rig.relay.test.v1",
            )
        ]
        env = build_receipt_envelope(
            envelope_id="override",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            evidence_override=override,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert len(env.evidence) == 1
        assert env.evidence[0].evidence_kind == ReceiptEvidenceKind.SCHEMA

    def test_evidence_override_with_payload(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        override = [
            ReceiptEvidence(
                evidence_kind=ReceiptEvidenceKind.SCHEMA,
                schema_version="rig.relay.test.v1",
            )
        ]
        env = build_receipt_envelope(
            envelope_id="combined",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload={"status": "ok"},
            evidence_override=override,
            created_at="2026-05-15T12:00:00+00:00",
        )
        assert len(env.evidence) == 2

    def test_no_forbidden_fields_in_built_envelope(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = build_receipt_envelope(
            envelope_id="safe",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        dumped = env.model_dump(mode="json")

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

        _check(dumped, "envelope")

    def test_auto_generates_envelope_id(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = build_receipt_envelope(
            receipt_kind="test", actor=sample_actor, subject=sample_subject
        )
        assert env.envelope_id is not None
        assert len(env.envelope_id) > 0

    def test_auto_generates_created_at(
        self, sample_actor: ReceiptActor, sample_subject: ReceiptSubject
    ) -> None:
        env = build_receipt_envelope(
            envelope_id="auto-time",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
        )
        assert env.created_at is not None
        assert "T" in env.created_at


# ── Schema tests ──────────────────────────────────────────────────────


class TestReceiptEnvelopeSchema:
    def test_schema_validates_minimal_envelope(
        self,
        schema_dict: dict[str, Any],
        sample_actor: ReceiptActor,
        sample_subject: ReceiptSubject,
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e1",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            created_at="2026-05-15T12:00:00+00:00",
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(env.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_full_envelope(
        self,
        schema_dict: dict[str, Any],
        sample_actor: ReceiptActor,
        sample_subject: ReceiptSubject,
        sample_decision: ReceiptDecision,
    ) -> None:
        env = ReceiptEnvelope(
            envelope_id="e2",
            receipt_kind="tool_invocation",
            actor=sample_actor,
            subject=sample_subject,
            input=ReceiptInput(input_kind="file", input_sha256="abc"),
            output=ReceiptOutput(output_kind="receipt", output_sha256="def"),
            decision=sample_decision,
            evidence=[
                ReceiptEvidence(
                    evidence_kind=ReceiptEvidenceKind.TOOL_RECEIPT,
                    evidence_sha256="abc123",
                )
            ],
            created_at="2026-05-15T12:00:00+00:00",
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(env.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_built_envelope(
        self,
        schema_dict: dict[str, Any],
        sample_actor: ReceiptActor,
        sample_subject: ReceiptSubject,
    ) -> None:
        env = build_receipt_envelope(
            envelope_id="e3",
            receipt_kind="test",
            actor=sample_actor,
            subject=sample_subject,
            receipt_payload={"tool_name": "bash"},
            created_at="2026-05-15T12:00:00+00:00",
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(env.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_top_level_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {
            "schema_version": "rig.relay.receipt_envelope.v1",
            "envelope_id": "e1",
            "receipt_kind": "test",
            "actor": {"actor_id": "x", "actor_kind": "system"},
            "subject": {"subject_id": "s", "subject_kind": "session"},
            "evidence": [],
            "created_at": "now",
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_rejects_invalid_actor_kind(
        self, schema_dict: dict[str, Any]
    ) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {
            "schema_version": "rig.relay.receipt_envelope.v1",
            "envelope_id": "e1",
            "receipt_kind": "test",
            "actor": {"actor_id": "x", "actor_kind": "not_a_real_kind"},
            "subject": {"subject_id": "s", "subject_kind": "session"},
            "evidence": [],
            "created_at": "now",
        }
        errors = list(validator.iter_errors(bad))
        assert any("not_a_real_kind" in str(e.message) for e in errors)

    def test_schema_rejects_missing_required_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {"schema_version": "rig.relay.receipt_envelope.v1"}
        errors = list(validator.iter_errors(bad))
        missing = [e.message for e in errors if "is a required property" in e.message]
        assert len(missing) >= 4

    def test_schema_has_no_forbidden_raw_fields(
        self, schema_dict: dict[str, Any]
    ) -> None:
        from tests.evidence._helpers import check_schema_for_forbidden_fields

        check_schema_for_forbidden_fields(schema_dict)


# ── Placeholder tests ────────────────────────────────────────────────


class TestPlaceholders:
    def test_placeholder_constants_are_strings(self) -> None:
        assert isinstance(PLACEHOLDER_UNKNOWN, str)
        assert isinstance(PLACEHOLDER_UNAVAILABLE, str)
        assert isinstance(PLACEHOLDER_NO_RECEIPT, str)

    def test_placeholder_values(self) -> None:
        assert PLACEHOLDER_UNKNOWN == "unknown"
        assert PLACEHOLDER_UNAVAILABLE == "unavailable"
        assert PLACEHOLDER_NO_RECEIPT == "no_receipt"
