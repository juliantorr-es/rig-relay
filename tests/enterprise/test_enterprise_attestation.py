from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.enterprise.policy_engine import (
    GateResult,
    PolicyEngine,
    PolicyEvaluation,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

_ATTESTATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "rig.enterprise.attestation.v1.schema.json"
)

_ATTESTATION_SCHEMA = json.loads(_ATTESTATION_SCHEMA_PATH.read_text("utf-8"))


def _make_evaluation(*, all_pass: bool = True) -> tuple[PolicyEvaluation, PolicyEngine]:
    passed = all_pass
    gate = GateResult(
        gate_id="test_gate",
        passed=passed,
        evidence="test evidence",
        current_value="ok" if passed else "fail",
        required_value="ok",
        blocked_reason="" if passed else "blocked for test",
    )
    evaluation = PolicyEvaluation(
        policy_id="rig.enterprise.policy.v1",
        gates=[gate],
        all_passed=passed,
        passed_count=1 if passed else 0,
        failed_count=0 if passed else 1,
        blocked_count=0,
        operator_acknowledgements_required=["ack_1_test", "ack_2_test"],
        next_action="execute" if passed else "blocked",
    )
    engine = PolicyEngine()
    return evaluation, engine


def test_sign_attestation_produces_attestation_with_all_required_fields():
    from rig_relay.enterprise.attestation import sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)

    assert att.attestation_id
    assert att.attestation_id.startswith("attest-")
    assert att.policy_evaluation_id
    assert att.signed_by == "operator-test"
    assert att.signed_at
    assert att.signature_hash
    assert isinstance(att.acknowledged_gates, list)
    assert isinstance(att.acknowledged_checks, list)
    assert att.content_light is True


def test_attestation_signature_hash_is_non_empty_sha256():
    from rig_relay.enterprise.attestation import sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)

    assert len(att.signature_hash) == 64
    int(att.signature_hash, 16)


def test_verify_attestation_returns_true_for_valid_attestation():
    from rig_relay.enterprise.attestation import sign_attestation, verify_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)
    assert verify_attestation(att, evaluation, engine) is True


def test_verify_attestation_returns_false_for_tampered_evaluation():
    from rig_relay.enterprise.attestation import sign_attestation, verify_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)

    tampered_gate = GateResult(
        gate_id="test_gate",
        passed=False,
        evidence="tampered",
        current_value="bad",
        required_value="ok",
        blocked_reason="tampered",
    )
    tampered = PolicyEvaluation(
        policy_id=evaluation.policy_id,
        gates=[tampered_gate],
        all_passed=False,
        passed_count=0,
        failed_count=1,
        blocked_count=0,
        operator_acknowledgements_required=evaluation.operator_acknowledgements_required,
        next_action="blocked",
    )
    assert verify_attestation(att, tampered, engine) is False


def test_verify_attestation_returns_false_for_tampered_signature():
    from rig_relay.enterprise.attestation import (
        Attestation,
        sign_attestation,
        verify_attestation,
    )

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)

    tampered_att = Attestation(
        attestation_id=att.attestation_id,
        policy_evaluation_id=att.policy_evaluation_id,
        signed_by=att.signed_by,
        signed_at=att.signed_at,
        signature_hash="0" * 64,
        acknowledged_gates=att.acknowledged_gates,
        acknowledged_checks=att.acknowledged_checks,
        content_light=True,
    )
    assert verify_attestation(tampered_att, evaluation, engine) is False


def test_verify_attestation_returns_false_for_wrong_operator():
    from rig_relay.enterprise.attestation import sign_attestation, verify_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)

    att_wrong = copy.copy(att)
    object.__setattr__(att_wrong, "signed_by", "other-operator")
    assert verify_attestation(att_wrong, evaluation, engine) is False


def test_attestation_dict_validates_against_schema():
    from rig_relay.enterprise.attestation import attestation_to_json, sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-schema-test", engine)
    data = attestation_to_json(att)
    jsonschema.Draft7Validator(_ATTESTATION_SCHEMA).validate(data)


def test_attestation_is_content_light():
    from rig_relay.enterprise.attestation import attestation_to_json, sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "operator-test", engine)
    data = attestation_to_json(att)
    serialized = json.dumps(data, sort_keys=True)
    assert att.content_light is True
    for token_pattern in ("ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-"):
        assert token_pattern not in serialized, f"Found token pattern: {token_pattern}"


def test_acknowledged_checks_contains_operator_acknowledgement_strings():
    from rig_relay.enterprise.attestation import sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "op", engine)
    assert att.acknowledged_checks == ["ack_1_test", "ack_2_test"]
    assert "ack_1_test" in att.acknowledged_checks
    assert "ack_2_test" in att.acknowledged_checks


def test_policy_evaluation_id_is_sha256_of_canonical_json():
    from rig_relay.enterprise.attestation import sign_attestation

    evaluation, engine = _make_evaluation(all_pass=True)
    att = sign_attestation(evaluation, "op", engine)

    canonical = json.dumps(
        engine.to_json(evaluation), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    assert att.policy_evaluation_id == expected
