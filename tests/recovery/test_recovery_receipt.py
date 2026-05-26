"""Test content-light recovery receipt — integrity, hashes, no raw content."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from rig_relay.recovery.models import (
    RecoveryAdmissionDecision,
    RecoveryIntent,
    RecoveryRefusal,
    RecoveryRefusalCode,
)
from rig_relay.recovery.receipt import (
    ToolIntentRecoveryReceipt,
    build_recovery_receipt_from_intent,
    build_recovery_receipt_from_refusal,
)


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def test_receipt_round_trip() -> None:
    receipt = ToolIntentRecoveryReceipt(
        receipt_id="test-1",
        manifest_digest=_sha256("manifest"),
        original_emission_sha256=_sha256("emission"),
        payload_schema_valid=True,
    )
    data = receipt.model_dump_json()
    parsed = ToolIntentRecoveryReceipt.model_validate_json(data)
    assert parsed.receipt_id == "test-1"
    assert parsed.receipt_sha256 is not None


def test_receipt_integrity() -> None:
    receipt = ToolIntentRecoveryReceipt(
        receipt_id="test-2",
        manifest_digest=_sha256("man_2"),
        original_emission_sha256=_sha256("em_2"),
        payload_schema_valid=False,
    )
    assert receipt.verify_integrity()
    original_digest = receipt.receipt_sha256
    receipt_dict = json.loads(receipt.model_dump_json())
    receipt_dict["manifest_digest"] = _sha256("tampered")
    receipt_dict.pop("receipt_sha256", None)
    tampered = ToolIntentRecoveryReceipt.model_validate(receipt_dict)
    assert tampered.receipt_sha256 != original_digest, (
        "Tampered receipt should have different digest"
    )


def test_receipt_schema_valid() -> None:
    receipt = ToolIntentRecoveryReceipt(
        receipt_id="test-schema",
        manifest_digest=_sha256("ms"),
        original_emission_sha256=_sha256("es"),
        admission_decision=RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY,
        selected_canonical_tool="git_status",
        selected_tool_mutation_class="read_only",
        normalized_payload_sha256=_sha256("payload"),
        payload_schema_valid=True,
    )
    data = json.loads(receipt.model_dump_json())
    schema_path = (
        Path(__file__).parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.tool_intent_recovery_receipt.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    validate(instance=data, schema=schema)


def test_receipt_from_intent_builder() -> None:
    intent = RecoveryIntent(
        canonical_tool_name="git_status",
        normalized_args={"path": "."},
        payload_digest=_sha256("p"),
        manifest_digest=_sha256("m"),
        mutation_class="read_only",
        rules_applied=["unwrap_function_object"],
    )
    receipt = build_recovery_receipt_from_intent(
        receipt_id="r1",
        intent=intent,
        manifest_digest=_sha256("m"),
        emission_sha256=_sha256("e"),
        admission_result=RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY,
    )
    assert receipt.selected_canonical_tool == "git_status"
    assert receipt.payload_schema_valid is True
    assert (
        receipt.admission_decision == RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY
    )
    assert receipt.verify_integrity()


def test_receipt_from_refusal_builder() -> None:
    refusal = RecoveryRefusal(
        refusal_code=RecoveryRefusalCode.UNKNOWN_ALIAS,
        reason="Not found",
        candidate_count=0,
        manifest_digest=_sha256("m"),
        original_emission_hash=_sha256("e"),
    )
    receipt = build_recovery_receipt_from_refusal(
        receipt_id="r2",
        refusal=refusal,
        manifest_digest=_sha256("m"),
        emission_sha256=_sha256("e"),
    )
    assert receipt.payload_schema_valid is False
    assert receipt.refused_reason is not None
    assert "unknown_alias" in receipt.refused_reason.lower()
    assert receipt.verify_integrity()


def test_receipt_never_contains_raw_paths() -> None:
    """Prove that hostile input does not leak into receipt fields."""
    intent = RecoveryIntent(
        canonical_tool_name="read_file",
        normalized_args={"file_path": "/etc/secrets/.env"},
        payload_digest=_sha256("secret"),
        manifest_digest=_sha256("m"),
        mutation_class="read_only",
        rules_applied=[],
    )
    receipt = build_recovery_receipt_from_intent(
        receipt_id="r-secret",
        intent=intent,
        manifest_digest=_sha256("m"),
        emission_sha256=_sha256("e"),
    )
    receipt_data = json.loads(receipt.model_dump_json())
    serialized = json.dumps(receipt_data)
    assert "/etc/secrets" not in serialized
    assert ".env" not in serialized
    assert receipt_data["normalized_payload_sha256"].startswith("sha256:")


def test_receipt_serialization_excludes_forbidden_keys() -> None:
    """Receipt JSON must not contain forbidden raw-content keys."""
    receipt = ToolIntentRecoveryReceipt(
        receipt_id="r-forbidden",
        manifest_digest=_sha256("mf"),
        original_emission_sha256=_sha256("ef"),
        payload_schema_valid=True,
    )
    data = json.loads(receipt.model_dump_json())
    forbidden = {
        "raw_emission",
        "raw_content",
        "raw_model_output",
        "file_content",
        "secret",
        "api_key",
        "token",
    }
    for key in forbidden:
        assert key not in data, f"Receipt contains forbidden key: {key}"
