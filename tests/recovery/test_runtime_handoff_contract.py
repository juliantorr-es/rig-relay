"""Test Lane B5/D1 runtime integration handoff contract."""

from __future__ import annotations

import json

import pytest

from rig_relay.recovery.handoff import (
    RecoveryHandoffMutationProposal,
    build_mutation_handoff,
    build_read_only_handoff,
    build_refusal_handoff,
    build_validation_handoff,
)


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def test_read_only_handoff_validates() -> None:
    h = build_read_only_handoff(_sha256("r"), _sha256("m"), "read_file", _sha256("p"))
    assert h.handoff_kind == "read_only"
    assert h.admission_decision == "auto_execute_read_only"
    data = json.loads(h.model_dump_json())
    assert data["schema_version"] == "rig.relay.tool_recovery_runtime_handoff.v1"


def test_validation_handoff_validates() -> None:
    h = build_validation_handoff(_sha256("r"), _sha256("m"), "validate", _sha256("p"))
    assert h.handoff_kind == "validation"
    assert h.admission_decision == "auto_execute_validation"


def test_mutation_handoff_validates() -> None:
    h = build_mutation_handoff(
        _sha256("r"),
        _sha256("m"),
        "write_file",
        _sha256("p"),
        mutation_class="writes_workspace",
    )
    assert h.handoff_kind == "mutation_proposal_only"
    assert h.admission_decision == "proposal_only_mutation"
    assert h.patch_proposal_required is True


def test_refusal_handoff_validates() -> None:
    h = build_refusal_handoff(
        _sha256("r"), _sha256("m"), "unknown_alias", reason="not found"
    )
    assert h.handoff_kind == "refusal"
    assert h.refusal_code == "unknown_alias"


def test_mutation_handoff_cannot_express_direct_execution() -> None:
    """Mutation handoff must never express auto-execute."""
    h = build_mutation_handoff(
        _sha256("r"),
        _sha256("m"),
        "write_file",
        _sha256("p"),
        mutation_class="writes_workspace",
    )
    assert h.admission_decision != "auto_execute_read_only"
    assert h.admission_decision != "auto_execute_validation"
    data = json.loads(h.model_dump_json())
    assert "auto_execute" not in data.get("admission_decision", "")


def test_schema_validates_handoff() -> None:
    from pathlib import Path

    from jsonschema import validate as jsonschema_validate

    h = build_read_only_handoff(_sha256("r"), _sha256("m"), "git_status", _sha256("p"))
    data = json.loads(h.model_dump_json())
    schema_path = (
        Path(__file__).parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.tool_recovery_runtime_handoff.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    jsonschema_validate(instance=data, schema=schema)


def test_recovery_receipt_sha256_is_digest() -> None:
    """Prove handoff uses digest (sha256:) not raw content."""
    h = build_read_only_handoff(
        _sha256("receipt-data"), _sha256("manifest"), "read_file", _sha256("payload")
    )
    assert h.recovery_receipt_sha256.startswith("sha256:")
    assert h.payload_digest.startswith("sha256:")
    assert h.manifest_digest.startswith("sha256:")


from pydantic import ValidationError


def test_handoff_rejects_extra_fields() -> None:
    """Extra fields must be rejected."""
    with pytest.raises(ValidationError):
        RecoveryHandoffMutationProposal(
            recovery_receipt_sha256=_sha256("r"),
            manifest_digest=_sha256("m"),
            canonical_tool_name="write_file",
            payload_digest=_sha256("p"),
            mutation_class="writes_workspace",
            execute_directly=True,  # forbidden
        )
