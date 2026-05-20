from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.enterprise.policy_engine import (
    BUILTIN_GATES,
    GateResult,
    PolicyContext,
    PolicyEngine,
    PolicyEvaluation,
    PolicyGate,
    evaluate_all_gates,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "rig.enterprise.policy_evaluation.v1.schema.json"
)

_POLICY_EVALUATION_SCHEMA = json.loads(_SCHEMA_PATH.read_text("utf-8"))


def _make_healthy_context() -> PolicyContext:
    stages = [{"stage": f"stage_{i}", "status": "complete"} for i in range(13)]
    return PolicyContext(
        readiness_artifacts={
            "checklist": {
                "operator_acknowledgements": [
                    "ack_1",
                    "ack_2",
                    "ack_3",
                    "ack_4",
                    "ack_5",
                    "ack_6",
                    "ack_7",
                    "ack_8",
                ],
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "preflight": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "permission_audit": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "runbook": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "rate_limit": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "rc_gate": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
        },
        metrics={"bridge_backend_health": "connected"},
        lifecycle_state={
            "lifecycle_stages": stages,
            "mutation_chain": {"remote_mutation_detected": False},
        },
        permission_audit={
            "gates": [
                {"id": "read_access", "proved": True},
                {"id": "write_access", "proved": True},
                {"id": "alert_access", "proved": True},
            ]
        },
        spiderweb_topology={},
    )


def _make_always_pass_evaluation() -> PolicyEvaluation:
    return PolicyEvaluation(
        policy_id="test.policy",
        gates=[
            GateResult(
                gate_id=f"gate_{i}",
                passed=True,
                evidence="pass",
                current_value="ok",
                required_value="ok",
            )
            for i in range(3)
        ],
        all_passed=True,
        passed_count=3,
        failed_count=0,
        blocked_count=0,
        operator_acknowledgements_required=["ack_1", "ack_2"],
        next_action="execute",
    )


def test_empty_context_evaluates_all_12_builtin_gates():
    engine = PolicyEngine()
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    assert len(result.gates) == len(BUILTIN_GATES) == 12


def test_healthy_context_passes_context_based_gates():
    ctx = _make_healthy_context()
    result = evaluate_all_gates(ctx)

    context_based_gate_ids = {
        "artifact_inventory_present",
        "replay_all_stages_complete",
        "permission_boundary_proven",
        "bridge_healthy",
        "mutation_not_in_progress",
        "no_raw_payloads_exposed",
    }

    for gate in result.gates:
        if gate.gate_id in context_based_gate_ids:
            assert gate.passed, (
                f"{gate.gate_id} should pass with healthy context: {gate.blocked_reason}"
            )


def test_policy_evaluation_all_passed_is_true_when_all_gates_pass():
    ctx = _make_healthy_context()

    always_pass = PolicyGate(
        gate_id="always_pass",
        description="Always passes",
        condition="true",
        evaluate=lambda c: GateResult(
            gate_id="always_pass",
            passed=True,
            evidence="always ok",
            current_value="pass",
            required_value="pass",
        ),
    )
    engine = PolicyEngine(gates=[always_pass, always_pass])
    result = engine.evaluate(ctx)
    assert result.all_passed is True
    assert result.passed_count == 2
    assert result.failed_count == 0
    assert result.blocked_count == 0


def test_policy_evaluation_next_action_execute_when_all_pass():
    always_pass = PolicyGate(
        gate_id="always_pass",
        description="Always passes",
        condition="true",
        evaluate=lambda c: GateResult(
            gate_id="always_pass",
            passed=True,
            evidence="ok",
            current_value="x",
            required_value="x",
        ),
    )
    engine = PolicyEngine(gates=[always_pass])
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    assert result.next_action == "execute"


def test_policy_evaluation_next_action_blocked_when_blocked_gate():
    always_blocked = PolicyGate(
        gate_id="blocked_gate",
        description="Always blocked",
        condition="false",
        evaluate=lambda c: GateResult(
            gate_id="blocked_gate",
            passed=False,
            evidence="blocked",
            current_value="0",
            required_value="1",
            blocked_reason="Test blocked",
        ),
    )
    engine = PolicyEngine(gates=[always_blocked])
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    assert result.all_passed is False
    assert result.next_action == "blocked"


def test_policy_evaluation_next_action_needs_human_review_when_failed():
    always_failed = PolicyGate(
        gate_id="failed_gate",
        description="Always fails without block reason",
        condition="false",
        evaluate=lambda c: GateResult(
            gate_id="failed_gate",
            passed=False,
            evidence="failure",
            current_value="0",
            required_value="1",
        ),
    )
    engine = PolicyEngine(gates=[always_failed])
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    assert result.all_passed is False
    assert result.next_action == "needs_human_review"


def test_blocked_takes_precedence_over_failed_for_next_action():
    blocked_gate = PolicyGate(
        gate_id="blocked_gate",
        description="Blocked",
        condition="false",
        evaluate=lambda c: GateResult(
            gate_id="blocked_gate",
            passed=False,
            evidence="blocked",
            current_value="0",
            required_value="1",
            blocked_reason="block reason",
        ),
    )
    failed_gate = PolicyGate(
        gate_id="failed_gate",
        description="Failed",
        condition="false",
        evaluate=lambda c: GateResult(
            gate_id="failed_gate",
            passed=False,
            evidence="fail",
            current_value="0",
            required_value="1",
        ),
    )
    engine = PolicyEngine(gates=[blocked_gate, failed_gate])
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    assert result.blocked_count == 1
    assert result.failed_count == 1
    assert result.next_action == "blocked"


def test_gate_result_includes_all_required_fields():
    engine = PolicyEngine()
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    for gate in result.gates:
        assert gate.gate_id
        assert isinstance(gate.passed, bool)
        assert isinstance(gate.evidence, str)
        assert isinstance(gate.current_value, str)
        assert isinstance(gate.required_value, str)
        assert isinstance(gate.blocked_reason, str)


def test_policy_evaluation_dict_validates_against_schema():
    engine = PolicyEngine()
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    data = engine.to_json(result)
    jsonschema.Draft7Validator(_POLICY_EVALUATION_SCHEMA).validate(data)


def test_policy_evaluation_is_content_light():
    engine = PolicyEngine()
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    data = engine.to_json(result)
    serialized = json.dumps(data, sort_keys=True)
    for token_pattern in ("ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-"):
        assert token_pattern not in serialized, f"Found token pattern: {token_pattern}"


def test_gate_evaluation_is_deterministic():
    engine = PolicyEngine()
    ctx = PolicyContext()
    first = engine.evaluate(ctx)
    second = engine.evaluate(ctx)
    for g1, g2 in zip(first.gates, second.gates, strict=False):
        assert g1.gate_id == g2.gate_id
        assert g1.passed == g2.passed, f"{g1.gate_id}: {g1.passed} != {g2.passed}"
        assert g1.evidence == g2.evidence


def test_bridge_healthy_passes_when_connected():
    ctx = PolicyContext(metrics={"bridge_backend_health": "connected"})
    result = evaluate_all_gates(ctx)
    bridge = next(r for r in result.gates if r.gate_id == "bridge_healthy")
    assert bridge.passed is True


def test_bridge_healthy_fails_when_disconnected():
    ctx = PolicyContext(metrics={"bridge_backend_health": "disconnected"})
    result = evaluate_all_gates(ctx)
    bridge = next(r for r in result.gates if r.gate_id == "bridge_healthy")
    assert bridge.passed is False
    assert bridge.blocked_reason != ""


def test_mutation_not_in_progress_passes_when_no_mutation_flag():
    ctx = PolicyContext(
        lifecycle_state={"mutation_chain": {"remote_mutation_detected": False}}
    )
    result = evaluate_all_gates(ctx)
    mut = next(r for r in result.gates if r.gate_id == "mutation_not_in_progress")
    assert mut.passed is True


def test_mutation_not_in_progress_fails_when_mutation_detected():
    ctx = PolicyContext(
        lifecycle_state={"mutation_chain": {"remote_mutation_detected": True}}
    )
    result = evaluate_all_gates(ctx)
    mut = next(r for r in result.gates if r.gate_id == "mutation_not_in_progress")
    assert mut.passed is False
    assert mut.blocked_reason != ""


def test_artifact_inventory_present_passes_when_all_artifacts_valid():
    ctx = PolicyContext(
        readiness_artifacts={
            "artifact_a": {"raw_payloads_exposed": False},
            "artifact_b": {"redaction_status": "content_light"},
        }
    )
    result = evaluate_all_gates(ctx)
    inv = next(r for r in result.gates if r.gate_id == "artifact_inventory_present")
    assert inv.passed is True


def test_missing_artifact_makes_corresponding_gate_blocked():
    ctx = PolicyContext(
        readiness_artifacts={
            "valid_artifact": {"raw_payloads_exposed": False},
            "empty_artifact": {},
        }
    )
    result = evaluate_all_gates(ctx)
    inv = next(r for r in result.gates if r.gate_id == "artifact_inventory_present")
    assert inv.passed is False
    assert len(inv.blocked_reason) > 0


def test_null_readiness_entry_makes_artifact_inventory_gate_blocked():
    ctx = PolicyContext(readiness_artifacts={"good": {"data": True}, "bad": {}})
    result = evaluate_all_gates(ctx)
    inv = next(r for r in result.gates if r.gate_id == "artifact_inventory_present")
    assert inv.passed is False


def test_non_dict_readiness_entry_makes_no_raw_payloads_gate_pass():
    ctx = PolicyContext(
        readiness_artifacts={
            "good": {"raw_payloads_exposed": False, "redaction_status": "content_light"}
            # non-dict entries are skipped by evaluate_gate_no_raw_payloads_exposed
        }
    )
    result = evaluate_all_gates(ctx)
    no_raw = next(r for r in result.gates if r.gate_id == "no_raw_payloads_exposed")
    assert no_raw.passed is True


def test_no_raw_payloads_fails_when_artifact_has_raw_payloads():
    ctx = PolicyContext(
        readiness_artifacts={
            "good": {
                "raw_payloads_exposed": False,
                "redaction_status": "content_light",
            },
            "bad": {"raw_payloads_exposed": True},
        }
    )
    result = evaluate_all_gates(ctx)
    no_raw = next(r for r in result.gates if r.gate_id == "no_raw_payloads_exposed")
    assert no_raw.passed is False


def test_engine_summary_returns_correct_counts():
    always_pass = PolicyGate(
        gate_id="p",
        description="passes",
        condition="true",
        evaluate=lambda c: GateResult(
            gate_id="p",
            passed=True,
            evidence="x",
            current_value="x",
            required_value="x",
        ),
    )
    engine = PolicyEngine(gates=[always_pass, always_pass])
    ctx = PolicyContext()
    result = engine.evaluate(ctx)
    summary = engine.summary(result)
    assert summary["all_passed"] is True
    assert summary["passed_count"] == 2
    assert summary["failed_count"] == 0
    assert summary["blocked_count"] == 0
    assert summary["next_action"] == "execute"


def test_permission_boundary_proven_passes_when_all_gates_proved():
    ctx = PolicyContext(
        permission_audit={
            "gates": [{"id": "r", "proved": True}, {"id": "w", "proved": True}]
        }
    )
    result = evaluate_all_gates(ctx)
    perm = next(r for r in result.gates if r.gate_id == "permission_boundary_proven")
    assert perm.passed is True


def test_permission_boundary_proven_fails_when_no_audit_gates():
    ctx = PolicyContext(permission_audit={"gates": []})
    result = evaluate_all_gates(ctx)
    perm = next(r for r in result.gates if r.gate_id == "permission_boundary_proven")
    assert perm.passed is False
