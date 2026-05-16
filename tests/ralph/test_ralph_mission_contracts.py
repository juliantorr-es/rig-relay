from __future__ import annotations
import pytest

pytestmark = [pytest.mark.integration]


from rig_relay.ralph.mission_contracts import (
    FORBIDDEN_CAPABILITIES,
    RalphMissionExecutionRefusal,
    RalphReadOnlyMissionPlan,
    RalphReadOnlyMissionRequest,
    RalphReadOnlyMissionResult,
)


def test_mission_request_rejects_mutation_capability():
    request = RalphReadOnlyMissionRequest(
        run_id="run-1",
        candidate_id="cand-1",
        capabilities=["read_files", "source_code_mutation"],
    )

    violations = request.validate_capabilities()
    assert "source_code_mutation" in violations


def test_mission_request_accepts_read_only_capabilities():
    request = RalphReadOnlyMissionRequest(
        run_id="run-1",
        candidate_id="cand-1",
        capabilities=["read_files", "inspect_git_status", "run_read_only_validators"],
    )

    violations = request.validate_capabilities()
    assert violations == []


def test_mission_plan_execution_disabled():
    plan = RalphReadOnlyMissionPlan(
        request_id="req-1",
        run_id="run-1",
    )

    assert plan.execution_enabled is False
    assert plan.implementation_status == "contract_only"


def test_mission_plan_lists_forbidden_capabilities():
    plan = RalphReadOnlyMissionPlan(
        request_id="req-1",
        run_id="run-1",
    )

    assert "source_code_mutation" in plan.forbidden_capabilities
    assert "git_commit" in plan.forbidden_capabilities
    assert "external_network_calls" in plan.forbidden_capabilities


def test_mission_result_is_not_implemented():
    result = RalphReadOnlyMissionResult(
        plan_id="plan-1",
    )

    assert result.status == "not_implemented"
    assert result.implementation_status == "contract_only"
    assert result.execution_enabled is False


def test_refusal_default_reason():
    refusal = RalphMissionExecutionRefusal(
        request_id="req-1",
    )

    assert refusal.reason == "execution_not_implemented"
    assert "not yet implemented" in refusal.message


def test_refusal_captures_forbidden_capabilities():
    refusal = RalphMissionExecutionRefusal(
        request_id="req-1",
        forbidden_capabilities_triggered=["source_code_mutation", "git_commit"],
    )

    assert len(refusal.forbidden_capabilities_triggered) == 2
    assert "source_code_mutation" in refusal.forbidden_capabilities_triggered


def test_all_forbidden_capabilities_are_documented():
    assert len(FORBIDDEN_CAPABILITIES) >= 10
    for cap in [
        "source_code_mutation",
        "canonical_finding_promotion",
        "git_commit",
        "external_network_calls",
        "background_recursion",
    ]:
        assert cap in FORBIDDEN_CAPABILITIES, f"Missing forbidden capability: {cap}"


def test_execution_never_enabled():
    request = RalphReadOnlyMissionRequest(
        run_id="run-1",
        candidate_id="cand-1",
        capabilities=["read_files"],
    )
    plan = RalphReadOnlyMissionPlan(
        request_id=request.request_id,
        run_id=request.run_id,
    )
    result = RalphReadOnlyMissionResult(plan_id=plan.plan_id)

    assert plan.execution_enabled is False
    assert result.execution_enabled is False
