"""Tests for projection integrity assessment models and builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.desktop.projection_integrity import (
    ProjectionContractStatus,
    ProjectionIntegrityAssessment,
    ProjectionIntegrityStatus,
    ProjectionViolation,
    ProjectionViolationCode,
    build_projection_integrity_assessment,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INTEGRITY_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.projection_integrity.v1.schema.json"
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_receipt(
    tool_name: str = "bash",
    status: str = "success",
    session_id: str = "session-1",
    event_id: str = "evt-001",
    captured_at: str | None = None,
) -> dict[str, Any]:
    now = captured_at or datetime.now(UTC).isoformat()
    return {
        "tool_name": tool_name,
        "status": status,
        "session_id": session_id,
        "event_id": event_id,
        "captured_at": now,
    }


def _make_minimal_receipt() -> dict[str, Any]:
    return {}


def _load_integrity_schema() -> dict[str, Any]:
    schema = _load_json(INTEGRITY_SCHEMA_PATH)
    assert schema is not None, "Could not load integrity schema"
    return schema


# ── Model tests ────────────────────────────────────────────────────────


class TestProjectionIntegrityAssessmentModel:
    """ProjectionIntegrityAssessment model validates correctly."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ProjectionIntegrityAssessment.model_validate({
                "integrity_status": "verified",
                "unknown_field": "x",
            })

    def test_defaults_to_unknown_not_applicable(self) -> None:
        assessment = ProjectionIntegrityAssessment()
        assert assessment.integrity_status == ProjectionIntegrityStatus.UNKNOWN
        assert assessment.contract_status == ProjectionContractStatus.NOT_APPLICABLE
        assert assessment.violation_count == 0
        assert assessment.violations == []
        assert assessment.receipt_count == 0
        assert assessment.authority_backed is False

    def test_serializes_to_json_safely(self) -> None:
        assessment = ProjectionIntegrityAssessment(
            integrity_status=ProjectionIntegrityStatus.VERIFIED,
            contract_status=ProjectionContractStatus.SATISFIED,
            violation_count=0,
            checked_at=datetime.now(UTC).isoformat(),
            receipt_count=5,
            authority_backed=True,
        )
        dumped = assessment.model_dump(mode="json")
        assert dumped["integrity_status"] == "verified"
        assert dumped["contract_status"] == "satisfied"
        assert dumped["violations"] == []
        assert dumped["receipt_count"] == 5
        assert dumped["authority_backed"] is True
        assert dumped["schema_version"] == "rig.relay.projection_integrity.v1"

    def test_has_no_forbidden_raw_fields(self) -> None:
        """Ensure no raw content fields appear in the model."""
        forbidden = {"output", "stdout", "stderr", "content", "diff", "file_contents"}
        field_names = set(ProjectionIntegrityAssessment.model_fields.keys())
        overlap = field_names & forbidden
        assert overlap == set(), f"Forbidden fields found: {overlap}"


class TestProjectionViolationModel:
    """ProjectionViolation model validates correctly."""

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            ProjectionViolation.model_validate({
                "code": "stale_receipt",
                "message": "test",
                "unknown": "x",
            })

    def test_minimal_construction(self) -> None:
        v = ProjectionViolation(
            code=ProjectionViolationCode.STALE_RECEIPT, message="Test"
        )
        assert v.code == ProjectionViolationCode.STALE_RECEIPT
        assert v.message == "Test"
        assert v.severity == "warning"
        assert v.widget_name is None
        assert v.receipt_id is None
        assert v.path is None

    def test_full_construction(self) -> None:
        v = ProjectionViolation(
            code=ProjectionViolationCode.AUTHORITY_UNBACKED,
            message="No receipt backing",
            severity="error",
            widget_name="SafetyState",
            receipt_id="evt-001",
            path="/tmp/test",
        )
        assert v.code == ProjectionViolationCode.AUTHORITY_UNBACKED
        assert v.severity == "error"
        assert v.widget_name == "SafetyState"
        assert v.receipt_id == "evt-001"
        assert v.path == "/tmp/test"

    def test_has_no_forbidden_raw_fields(self) -> None:
        forbidden = {"output", "stdout", "stderr", "content", "diff", "file_contents"}
        field_names = set(ProjectionViolation.model_fields.keys())
        overlap = field_names & forbidden
        assert overlap == set(), f"Forbidden fields found: {overlap}"


# ── Builder tests ─────────────────────────────────────────────────────


class TestBuildProjectionIntegrityAssessment:
    """build_projection_integrity_assessment() behaves correctly."""

    def test_empty_receipts_with_no_authority_returns_unknown(self) -> None:
        assessment = build_projection_integrity_assessment()
        assert assessment.integrity_status == ProjectionIntegrityStatus.UNKNOWN
        assert assessment.contract_status == ProjectionContractStatus.NOT_APPLICABLE
        assert assessment.violation_count == 0
        assert assessment.receipt_count == 0
        assert assessment.authority_backed is False

    def test_none_receipts_returns_unknown(self) -> None:
        assessment = build_projection_integrity_assessment(receipt_records=None)
        assert assessment.integrity_status == ProjectionIntegrityStatus.UNKNOWN
        assert assessment.receipt_count == 0

    def test_valid_receipt_produces_verified_satisfied(self) -> None:
        receipt = _make_receipt()
        assessment = build_projection_integrity_assessment(
            receipt_records=[receipt], widget_names=["SafetyState"]
        )
        assert assessment.integrity_status == ProjectionIntegrityStatus.VERIFIED
        assert assessment.contract_status == ProjectionContractStatus.SATISFIED
        assert assessment.violation_count == 0
        assert assessment.receipt_count == 1
        assert assessment.authority_backed is True
        assert assessment.stale_receipt_count == 0
        assert assessment.orphaned_receipt_count == 0

    def test_multiple_valid_receipts(self) -> None:
        receipts = [
            _make_receipt(tool_name="bash", event_id="evt-001"),
            _make_receipt(tool_name="search_replace", event_id="evt-002"),
        ]
        assessment = build_projection_integrity_assessment(receipt_records=receipts)
        assert assessment.integrity_status == ProjectionIntegrityStatus.VERIFIED
        assert assessment.receipt_count == 2

    def test_stale_receipt_produces_stale_violation(self) -> None:
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        receipt = _make_receipt(captured_at=old_time)
        assessment = build_projection_integrity_assessment(
            receipt_records=[receipt], stale_after_seconds=3600
        )
        assert assessment.integrity_status == ProjectionIntegrityStatus.STALE
        assert assessment.stale_receipt_count == 1
        assert any(
            v.code == ProjectionViolationCode.STALE_RECEIPT
            for v in assessment.violations
        )

    def test_stale_detection_disabled_with_none(self) -> None:
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        receipt = _make_receipt(captured_at=old_time)
        assessment = build_projection_integrity_assessment(
            receipt_records=[receipt], stale_after_seconds=None
        )
        assert assessment.stale_receipt_count == 0
        assert assessment.integrity_status == ProjectionIntegrityStatus.VERIFIED

    def test_authority_claim_without_receipt_produces_unbacked(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[], claimed_authorities=["view_projection"]
        )
        assert assessment.integrity_status == ProjectionIntegrityStatus.DEGRADED
        assert assessment.authority_backed is False
        assert any(
            v.code == ProjectionViolationCode.AUTHORITY_UNBACKED
            for v in assessment.violations
        )

    def test_authority_dict_requires_exact_receipt_match(self) -> None:
        receipts = [_make_receipt(event_id="evt-001")]
        assessment = build_projection_integrity_assessment(
            receipt_records=receipts, claimed_authorities={"view_projection": "evt-002"}
        )
        assert assessment.authority_backed is False
        assert any(
            v.code == ProjectionViolationCode.AUTHORITY_UNBACKED
            for v in assessment.violations
        )

    def test_authority_dict_with_matching_receipt(self) -> None:
        receipts = [_make_receipt(event_id="evt-001")]
        assessment = build_projection_integrity_assessment(
            receipt_records=receipts, claimed_authorities={"view_projection": "evt-001"}
        )
        assert assessment.authority_backed is True
        assert all(
            v.code != ProjectionViolationCode.AUTHORITY_UNBACKED
            for v in assessment.violations
        )

    def test_unknown_widget_produces_violation(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[_make_receipt()], widget_names=["NonExistentWidget"]
        )
        assert any(
            v.code == ProjectionViolationCode.UNKNOWN_WIDGET
            for v in assessment.violations
        )
        assert assessment.contract_status == ProjectionContractStatus.PARTIAL

    def test_known_widget_no_violation(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[_make_receipt()], widget_names=["SafetyState"]
        )
        assert all(
            v.code != ProjectionViolationCode.UNKNOWN_WIDGET
            for v in assessment.violations
        )

    def test_malformed_minimal_dict_tolerated(self) -> None:
        receipt = _make_minimal_receipt()
        # Minimal dict missing session_id/tool_name — should be flagged as orphaned
        assessment = build_projection_integrity_assessment(
            receipt_records=[receipt], stale_after_seconds=None
        )
        assert assessment.orphaned_receipt_count == 1
        assert any(
            v.code == ProjectionViolationCode.ORPHANED_RECEIPT
            for v in assessment.violations
        )

    def test_no_forbidden_raw_fields_in_assessment_dump(self) -> None:
        receipt = _make_receipt()
        assessment = build_projection_integrity_assessment(receipt_records=[receipt])
        dumped = assessment.model_dump(mode="json")
        forbidden = {"output", "stdout", "stderr", "content", "diff", "file_contents"}

        def _check(val: Any, path: str) -> None:
            if isinstance(val, dict):
                for k, v in val.items():
                    if k in forbidden:
                        raise AssertionError(f"Forbidden field '{k}' at {path}")
                    _check(v, f"{path}.{k}")
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    _check(item, f"{path}[{i}]")

        _check(dumped, "assessment")

    def test_checked_at_is_set(self) -> None:
        now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
        assessment = build_projection_integrity_assessment(now=now)
        assert assessment.checked_at == "2026-05-15T12:00:00+00:00"

    def test_contract_not_applicable_when_no_authorities_or_widgets(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[_make_receipt()],
            claimed_authorities=None,
            widget_names=None,
        )
        assert assessment.contract_status == ProjectionContractStatus.NOT_APPLICABLE

    def test_contract_satisfied_with_widget_and_no_violations(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[_make_receipt()], widget_names=["SafetyState"]
        )
        assert assessment.contract_status == ProjectionContractStatus.SATISFIED

    def test_contract_violated_with_error_severity(self) -> None:
        assessment = build_projection_integrity_assessment(
            receipt_records=[], claimed_authorities=["view_projection"]
        )
        # authority_unbacked has severity "error"
        assert assessment.contract_status == ProjectionContractStatus.VIOLATED


# ── Schema tests ──────────────────────────────────────────────────────


class TestProjectionIntegritySchema:
    """schema validates assessment dumps correctly."""

    def _load_schema(self) -> dict[str, Any]:
        schema = _load_integrity_schema()
        return schema

    def test_schema_validates_verified_assessment(self) -> None:
        schema = self._load_schema()
        assessment = build_projection_integrity_assessment(
            receipt_records=[_make_receipt()]
        )
        dumped = assessment.model_dump(mode="json")
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(dumped))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_unknown_assessment(self) -> None:
        schema = self._load_schema()
        assessment = build_projection_integrity_assessment()
        dumped = assessment.model_dump(mode="json")
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(dumped))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_stale_assessment(self) -> None:
        schema = self._load_schema()
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        receipt = _make_receipt(captured_at=old_time)
        assessment = build_projection_integrity_assessment(
            receipt_records=[receipt], stale_after_seconds=3600
        )
        dumped = assessment.model_dump(mode="json")
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(dumped))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_top_level_fields(self) -> None:
        schema = self._load_schema()
        validator = jsonschema.Draft7Validator(schema)
        bad = {
            "schema_version": "rig.relay.projection_integrity.v1",
            "integrity_status": "unknown",
            "contract_status": "not_applicable",
            "violation_count": 0,
            "violations": [],
            "checked_at": "2026-05-15T12:00:00+00:00",
            "receipt_count": 0,
            "stale_receipt_count": 0,
            "orphaned_receipt_count": 0,
            "authority_backed": False,
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_rejects_unknown_violation_fields(self) -> None:
        schema = self._load_schema()
        validator = jsonschema.Draft7Validator(schema)
        bad = {
            "schema_version": "rig.relay.projection_integrity.v1",
            "integrity_status": "unknown",
            "contract_status": "not_applicable",
            "violation_count": 1,
            "violations": [
                {"code": "stale_receipt", "message": "test", "unknown_vfield": "x"}
            ],
            "checked_at": "2026-05-15T12:00:00+00:00",
            "receipt_count": 0,
            "stale_receipt_count": 0,
            "orphaned_receipt_count": 0,
            "authority_backed": False,
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_vfield" in str(e.message) for e in errors)

    def test_schema_rejects_invalid_status_value(self) -> None:
        schema = self._load_schema()
        validator = jsonschema.Draft7Validator(schema)
        bad = {
            "schema_version": "rig.relay.projection_integrity.v1",
            "integrity_status": "invalid_status",
            "contract_status": "not_applicable",
            "violation_count": 0,
            "violations": [],
            "checked_at": "2026-05-15T12:00:00+00:00",
            "receipt_count": 0,
            "stale_receipt_count": 0,
            "orphaned_receipt_count": 0,
            "authority_backed": False,
        }
        errors = list(validator.iter_errors(bad))
        assert any("invalid_status" in str(e.message) for e in errors)

    def test_schema_rejects_missing_required_fields(self) -> None:
        schema = self._load_schema()
        validator = jsonschema.Draft7Validator(schema)
        bad = {"schema_version": "rig.relay.projection_integrity.v1"}
        errors = list(validator.iter_errors(bad))
        required = schema.get("required", [])
        missing_messages = [
            e.message for e in errors if "is a required property" in e.message
        ]
        assert len(missing_messages) >= len(required) - 1

    def test_schema_has_no_forbidden_raw_fields(self) -> None:
        schema = self._load_schema()
        forbidden = {"output", "stdout", "stderr", "content", "diff", "file_contents"}

        def _check(obj: Any, path: str) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in forbidden:
                        raise AssertionError(f"Forbidden field '{k}' at {path}")
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")

        _check(schema, "schema")
