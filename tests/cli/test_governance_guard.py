from __future__ import annotations

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution,
)


def test_dry_run_returns_allowed_without_governance_evaluation():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="test_capability",
        execute_requested=False,
    )
    assert decision.decision.value == "allowed"
    assert decision.gate == "cli.dry_run"
    assert decision.surface == "cli_script"


def test_execute_requested_evaluates_governance():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=True,
        allow_mutation=True,
    )
    assert decision.decision.value == "allowed"
    assert decision.decision_id.startswith("gd-")
    assert decision.surface == "cli_script"


def test_execute_without_allow_mutation_returns_blocked_or_review():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=True,
        allow_mutation=False,
    )
    assert decision.decision.value in {"blocked", "requires_review"}


def test_emit_structured_result_dry_run():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        execute_requested=False,
    )
    result = emit_structured_result(
        script_name="test_script",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        dry_run=True,
        execute_requested=False,
        decision=decision,
        status="dry_run",
    )
    assert result["schema_version"] == "rig.relay.cli_script_result.v1"
    assert result["dry_run"] is True
    assert result["execute_requested"] is False
    assert result["content_light"] is True
    assert result["status"] == "dry_run"
    assert result["surface"] == "cli_script"


def test_emit_structured_result_blocked():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        execute_requested=True,
        allow_mutation=False,
    )
    result = emit_structured_result(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="file_write_proposal",
        dry_run=False,
        execute_requested=True,
        decision=decision,
        status="blocked_by_governance",
    )
    assert result["execute_requested"] is True
    assert result["decision"] in {"blocked", "requires_review"}
    assert result["content_light"] is True


def test_emit_structured_result_includes_decision_id():
    decision = require_governed_execution(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="test_cap",
        execute_requested=True,
        allow_mutation=True,
    )
    result = emit_structured_result(
        script_name="test_script",
        authority_tier="local_mutation",
        capability_id="test_cap",
        dry_run=False,
        execute_requested=True,
        decision=decision,
        status="executed",
    )
    assert result["decision_id"].startswith("gd-")
    assert len(result["decision_id"]) > 3


def test_admin_requires_execute():
    decision = require_governed_execution(
        script_name="enterprise_admin",
        authority_tier="admin_configuration",
        capability_id="tenant_register",
        execute_requested=False,
    )
    assert decision.decision.value == "allowed"
    assert decision.gate == "cli.dry_run"


def test_remote_mutation_requires_network_and_mutation():
    decision = require_governed_execution(
        script_name="github_pr_write",
        authority_tier="remote_mutation",
        capability_id="shell_proposal",
        execute_requested=True,
        allow_mutation=False,
        allow_network=False,
    )
    assert decision.decision.value in {"blocked", "requires_review"}
