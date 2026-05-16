"""Tests for rig_relay.runtime.tool_invocation_receipt — receipt model, builder, schema.

All tests use synthetic fixtures and never mutate files, call tools,
or persist anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionStatus,
)
from rig_relay.runtime.tool_invocation_receipt import (
    RuntimeToolInvocationReceipt,
    build_runtime_tool_invocation_receipt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RECEIPT_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_invocation_receipt.v1.schema.json"
)

FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "content",
    "stdout",
    "stderr",
    "output_text",
    "diff",
    "patch",
    "chunk_text",
    "old_text",
    "new_text",
    "snippet",
    "file_contents",
    "prompt",
    "secret",
})


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def receipt_schema_dict() -> dict:
    raw = _load_json(RECEIPT_SCHEMA_PATH)
    assert raw is not None, f"Schema not found at {RECEIPT_SCHEMA_PATH}"
    return raw


def _make_result(**overrides: object) -> RuntimeToolExecutionResult:
    kwargs: dict[str, object] = {
        "status": RuntimeToolExecutionStatus.COMPLETED,
        "intent_id": "intent-001",
        "tool_name": "validate",
    }
    kwargs.update(overrides)
    return RuntimeToolExecutionResult(**kwargs)  # type: ignore[arg-type]


# ── Model tests ────────────────────────────────────────────────────────


class TestRuntimeToolInvocationReceiptModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolInvocationReceipt.model_validate({
                "schema_version": "rig.relay.runtime_tool_invocation_receipt.v1",
                "invocation_id": "i1",
                "intent_id": "i2",
                "tool_name": "validate",
                "adapter_status": "completed",
                "unknown_field": "x",
            })

    def test_minimal_valid_receipt(self) -> None:
        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name="validate",
            adapter_status="completed",
        )
        assert receipt.schema_version == "rig.relay.runtime_tool_invocation_receipt.v1"
        assert receipt.invocation_id == "inv-001"
        assert receipt.tool_status is None
        assert receipt.receipt_sha256 is None
        assert receipt.changed_paths == []
        assert receipt.warnings == []

    def test_full_receipt(self) -> None:
        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name="validate",
            adapter_status="completed",
            tool_status="passed",
            tool_error_kind=None,
            tool_receipt_kind="validate",
            tool_receipt_schema_version="rig.relay.validate_receipt.v1",
            receipt_sha256="abc123",
            envelope_id="env-001",
            audit_event_id="audit-001",
            changed_paths=["/tmp/file.txt"],
            duration_ms=150.0,
            created_at="2026-05-17T00:00:00Z",
            warnings=["note"],
        )
        assert receipt.changed_paths == ["/tmp/file.txt"]
        assert receipt.envelope_id == "env-001"
        assert receipt.audit_event_id == "audit-001"

    def test_dump_has_no_forbidden_fields(self) -> None:
        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name="validate",
            adapter_status="completed",
        )
        dumped = receipt.model_dump(mode="json")
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f"Found forbidden field '{forbidden}' in dump"
            )


# ── Builder tests ─────────────────────────────────────────────────────


class TestBuildRuntimeToolInvocationReceipt:
    def test_build_from_completed_result(self) -> None:
        result = _make_result(
            invocation_id="inv-001",
            tool_status="passed",
            receipt_sha256="abc123",
            duration_ms=150.0,
            tool_receipt_kind="validate",
            tool_receipt_schema_version="rig.relay.validate_receipt.v1",
            supervisor_result_envelope_id="sup-env-001",
            supervisor_result_envelope_sha256="sha256:sup-env",
            supervisor_result_classification="completed",
        )

        receipt = build_runtime_tool_invocation_receipt(
            result, created_at="2026-05-17T00:00:00Z"
        )

        assert receipt.invocation_id == "inv-001"
        assert receipt.intent_id == "intent-001"
        assert receipt.tool_name == "validate"
        assert receipt.adapter_status == "completed"
        assert receipt.tool_status == "passed"
        assert receipt.receipt_sha256 == "abc123"
        assert receipt.tool_receipt_kind == "validate"
        assert receipt.supervisor_result_envelope_id == "sup-env-001"
        assert receipt.supervisor_result_envelope_sha256 == "sha256:sup-env"
        assert receipt.supervisor_result_classification == "completed"
        assert receipt.created_at == "2026-05-17T00:00:00Z"

    def test_build_copies_changed_paths(self) -> None:
        result = _make_result(changed_paths=["/tmp/a.txt", "/tmp/b.txt"])
        receipt = build_runtime_tool_invocation_receipt(
            result, created_at="2026-05-17T00:00:00Z"
        )
        assert receipt.changed_paths == ["/tmp/a.txt", "/tmp/b.txt"]

    def test_build_default_created_at(self) -> None:
        result = _make_result()
        receipt = build_runtime_tool_invocation_receipt(result)
        assert receipt.created_at != ""

    def test_build_copies_envelope_and_audit_ids(self) -> None:
        result = _make_result(
            receipt_envelope_id="env-001",
            audit_event_id="audit-001",
            supervisor_result_envelope_id="sup-env-001",
            supervisor_result_envelope_sha256="sha256:sup-env",
            supervisor_result_classification="completed",
        )
        receipt = build_runtime_tool_invocation_receipt(
            result, created_at="2026-05-17T00:00:00Z"
        )
        assert receipt.envelope_id == "env-001"
        assert receipt.audit_event_id == "audit-001"
        assert receipt.supervisor_result_envelope_id == "sup-env-001"
        assert receipt.supervisor_result_envelope_sha256 == "sha256:sup-env"
        assert receipt.supervisor_result_classification == "completed"

    def test_build_invocation_id_falls_back_to_intent_id(self) -> None:
        result = _make_result(invocation_id=None)
        receipt = build_runtime_tool_invocation_receipt(
            result, created_at="2026-05-17T00:00:00Z"
        )
        assert receipt.invocation_id == "intent-001"

    def test_build_copies_all_status_fields(self) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.REFUSED,
            tool_status="refused",
            tool_error_kind="unsupported_tool",
            error_kind="unsupported_tool",
        )
        receipt = build_runtime_tool_invocation_receipt(
            result, created_at="2026-05-17T00:00:00Z"
        )
        assert receipt.adapter_status == "refused"
        assert receipt.tool_status == "refused"
        assert receipt.tool_error_kind == "unsupported_tool"


# ── Schema tests ──────────────────────────────────────────────────────


class TestReceiptSchema:
    def test_schema_validates_minimal_receipt(self, receipt_schema_dict: dict) -> None:
        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name="validate",
            adapter_status="completed",
            supervisor_result_envelope_id="sup-env-001",
            supervisor_result_envelope_sha256="sha256:sup-env",
            supervisor_result_classification="completed",
        )
        validator = jsonschema.Draft7Validator(receipt_schema_dict)
        errors = list(validator.iter_errors(receipt.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_full_receipt(self, receipt_schema_dict: dict) -> None:
        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name="search_replace",
            adapter_status="completed",
            tool_status="success",
            tool_receipt_kind="search_replace",
            tool_receipt_schema_version="rig.relay.search_replace_receipt.v1",
            receipt_sha256="abc123",
            envelope_id="env-001",
            audit_event_id="audit-001",
            changed_paths=["/tmp/file.txt"],
            duration_ms=200.0,
            created_at="2026-05-17T00:00:00Z",
            warnings=[],
        )
        validator = jsonschema.Draft7Validator(receipt_schema_dict)
        errors = list(validator.iter_errors(receipt.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_fields(self, receipt_schema_dict: dict) -> None:
        validator = jsonschema.Draft7Validator(receipt_schema_dict)
        bad = {
            "schema_version": "rig.relay.runtime_tool_invocation_receipt.v1",
            "invocation_id": "i1",
            "intent_id": "i2",
            "tool_name": "validate",
            "adapter_status": "completed",
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_has_no_forbidden_raw_fields(
        self, receipt_schema_dict: dict
    ) -> None:
        def _check(obj: object, path: str) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k not in FORBIDDEN_RAW_FIELD_NAMES, (
                        f"Forbidden field '{k}' at {path}"
                    )
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")

        _check(receipt_schema_dict, "schema")
