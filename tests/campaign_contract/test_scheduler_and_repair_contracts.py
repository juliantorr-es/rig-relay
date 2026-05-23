from __future__ import annotations

from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract.models import (
    BlockingFinding,
    BoundedIncidentalUnblockRepairDecision,
    CampaignManifest,
    MissionOutcome,
    ResolverEvaluationDecision,
)
from rig_relay.campaign_contract.validation import validate_resolver_decision

# ---- Valid helpers ---------------------------------------------------


def _valid_mission_dict(mission_id: str = "m1") -> dict:
    return {
        "mission_id": mission_id,
        "owned_path_scope": [f"{mission_id}_owned"],
        "read_context_scope": [f"{mission_id}_read"],
        "provider_context_scope": [f"{mission_id}_prov"],
        "validation_commands": ["v"],
        "prerequisites": [],
        "resolver_scope_declarations": [],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    }


def _valid_manifest(ordered_mission_ids: list[str]) -> CampaignManifest:
    missions = []
    for mid in ordered_mission_ids:
        d = _valid_mission_dict(mid)
        if mid == "resolver1":
            d["resolver_scope_declarations"] = ["scope_x"]
            d["owned_path_scope"] = ["resolver1_owned"]
            d["read_context_scope"] = ["resolver1_read"]
            d["provider_context_scope"] = ["resolver1_prov"]
        missions.append(d)
    return CampaignManifest.model_validate({
        "ordered_missions": missions,
        "user_approval_marker": True,
        "operating_mode": "confidential_autonomous_campaign_nonpromoting",
        "provider_disclosure_attestation": {
            "mode": "hosted_confidential_full_source_user_approved",
            "provider_family_identity": "fam",
            "provider_model_identity": "model1",
            "actual_retention_control_mode_classification": "standard_retention",
            "campaign_scope_digest": "dig",
            "campaign_scope_approval_marker": True,
            "mission_level_provider_scope_enforcement_marker": True,
        },
        "absolute_exclusions": [
            "credentials",
            "secrets",
            "tokens",
            "private_authentication_material",
            "patent_or_counsel_material",
            "legal_strategy_material",
            "confidential_audit_artifacts",
            "confidential_build_sink",
            "local_crosswalks",
            "provider_policy_evidence_bodies",
            "encrypted_snapshots",
            "unrelated_repository_content",
            "unclassified_paths",
        ],
        "mission_universe_immutable_after_execution_begins": True,
    })


def _valid_finding(
    finding_class: str = "out_of_scope_blocker_with_approved_resolver",
    candidates: list[str] | None = None,
) -> BlockingFinding:
    if candidates is None:
        candidates = ["resolver1"]
    return BlockingFinding.model_validate({
        "finding_class": finding_class,
        "blocking_status": True,
        "affected_contract_clause": "c",
        "resolution_scope": "scope_x",
        "candidate_approved_resolvers": candidates,
        "incidental_repair_eligibility": False,
        "end_of_campaign_disposition": "d",
    })


def _valid_decision(
    mission_id: str = "m1",
    resolver_mission_id: str = "resolver1",
    is_approved: bool = True,
) -> ResolverEvaluationDecision:
    return ResolverEvaluationDecision.model_validate({
        "mission_id": mission_id,
        "resolver_mission_id": resolver_mission_id,
        "is_approved": is_approved,
        "reason_code": "r",
        "requested_owned_paths": ["resolver1_owned"],
        "requested_read_context_paths": ["resolver1_read"],
        "requested_provider_context_paths": ["resolver1_prov"],
        "requested_resolution_scope": "scope_x",
    })


# ---- Incidental repair boundary tests --------------------------------


def test_contract_sabotage_negative_incidental_repair_source_path_count_fails():
    """Classification: contract/sabotage
    Negative incidental repair source path count fails.
    """
    valid: dict = {
        "operation_kind": "bounded_incidental_unblock_repair",
        "no_eligible_manifest_resolver_marker": True,
        "low_blast_radius": True,
        "non_architectural": True,
        "compatibility_preserving": True,
        "no_security_boundary_change": True,
        "no_disclosure_boundary_change": True,
        "no_dependency_change": True,
        "no_policy_config_schema_family_change": True,
        "no_shared_module_refactor": True,
        "no_unsafe_fallback": True,
        "no_test_weakening": True,
        "pre_edit_decision_recorded": True,
        "targeted_validation_plan": "t",
        "validation_result_required_before_resume": True,
        "out_of_scope_source_path_count": 0,
        "broad_refactor_prohibited": True,
        "bypass_prohibited": True,
        "global_fixture_prohibited": True,
        "lint_suppression_prohibited": True,
    }
    BoundedIncidentalUnblockRepairDecision.model_validate(valid)

    valid["out_of_scope_source_path_count"] = -1
    with pytest.raises(ValidationError):
        BoundedIncidentalUnblockRepairDecision.model_validate(valid)


def test_contract_sabotage_incidental_repair_over_three_paths_fails():
    """Classification: contract/sabotage
    Incidental repair over three outside-scope paths fails.
    """
    valid: dict = {
        "operation_kind": "bounded_incidental_unblock_repair",
        "no_eligible_manifest_resolver_marker": True,
        "low_blast_radius": True,
        "non_architectural": True,
        "compatibility_preserving": True,
        "no_security_boundary_change": True,
        "no_disclosure_boundary_change": True,
        "no_dependency_change": True,
        "no_policy_config_schema_family_change": True,
        "no_shared_module_refactor": True,
        "no_unsafe_fallback": True,
        "no_test_weakening": True,
        "pre_edit_decision_recorded": True,
        "targeted_validation_plan": "t",
        "validation_result_required_before_resume": True,
        "out_of_scope_source_path_count": 4,
        "broad_refactor_prohibited": True,
        "bypass_prohibited": True,
        "global_fixture_prohibited": True,
        "lint_suppression_prohibited": True,
    }
    with pytest.raises(ValidationError):
        BoundedIncidentalUnblockRepairDecision.model_validate(valid)


def test_contract_sabotage_incidental_repair_boundary_violation_fails():
    """Classification: contract/sabotage
    Incidental repair permitting boundary, schema, dependency, fallback,
    lint suppression, global fixture, or test weakening fails.
    """
    base: dict = {
        "operation_kind": "bounded_incidental_unblock_repair",
        "no_eligible_manifest_resolver_marker": True,
        "low_blast_radius": True,
        "non_architectural": True,
        "compatibility_preserving": True,
        "no_security_boundary_change": True,
        "no_disclosure_boundary_change": True,
        "no_dependency_change": True,
        "no_policy_config_schema_family_change": True,
        "no_shared_module_refactor": True,
        "no_unsafe_fallback": True,
        "no_test_weakening": True,
        "pre_edit_decision_recorded": True,
        "targeted_validation_plan": "t",
        "validation_result_required_before_resume": True,
        "out_of_scope_source_path_count": 0,
        "broad_refactor_prohibited": True,
        "bypass_prohibited": True,
        "global_fixture_prohibited": True,
        "lint_suppression_prohibited": True,
    }
    BoundedIncidentalUnblockRepairDecision.model_validate(base)

    # Each boundary violation must fail
    violations = [
        ("no_dependency_change", False),
        ("no_security_boundary_change", False),
        ("no_disclosure_boundary_change", False),
        ("no_policy_config_schema_family_change", False),
        ("no_shared_module_refactor", False),
        ("no_unsafe_fallback", False),
        ("no_test_weakening", False),
        ("bypass_prohibited", False),
        ("global_fixture_prohibited", False),
        ("lint_suppression_prohibited", False),
    ]
    for field, bad_value in violations:
        invalid = dict(base)
        invalid[field] = bad_value
        with pytest.raises(ValidationError):
            BoundedIncidentalUnblockRepairDecision.model_validate(invalid)


# ---- Resolver context validation tests --------------------------------


def test_contract_sabotage_resolver_not_in_manifest_fails():
    """Classification: contract/sabotage
    Resolver not in approved manifest fails.
    """
    manifest = _valid_manifest(["m1", "m2"])
    finding = _valid_finding(candidates=["missing_resolver"])
    decision = _valid_decision(resolver_mission_id="missing_resolver")

    with pytest.raises(ValueError, match="not in the approved mission universe"):
        validate_resolver_decision(manifest, "m1", finding, decision)


def test_contract_sabotage_resolver_not_matching_finding_scope_fails():
    """Classification: contract/sabotage
    Resolver with nonmatching finding scope fails.
    """
    manifest = _valid_manifest(["m1", "resolver1"])
    finding = _valid_finding(candidates=["other_resolver"])
    decision = _valid_decision(resolver_mission_id="resolver1")

    with pytest.raises(ValueError, match="does not declare matching scope"):
        validate_resolver_decision(manifest, "m1", finding, decision)


def test_contract_sabotage_resolver_unsatisfied_prereqs_fails():
    """Classification: contract/sabotage
    Resolver with unsatisfied prerequisites fails.
    """
    manifest = _valid_manifest(["m1", "resolver1"])
    # resolver1 requires "m2" as prerequisite but m2 has no outcome
    resolver_dict = _valid_mission_dict("resolver1")
    resolver_dict["prerequisites"] = ["m2"]
    resolver_dict["resolver_scope_declarations"] = ["scope_x"]
    manifest = CampaignManifest.model_validate({
        "ordered_missions": [_valid_mission_dict("m1"), resolver_dict],
        "user_approval_marker": True,
        "operating_mode": "confidential_autonomous_campaign_nonpromoting",
        "provider_disclosure_attestation": {
            "mode": "hosted_confidential_full_source_user_approved",
            "provider_family_identity": "fam",
            "provider_model_identity": "model1",
            "actual_retention_control_mode_classification": "standard_retention",
            "campaign_scope_digest": "dig",
            "campaign_scope_approval_marker": True,
            "mission_level_provider_scope_enforcement_marker": True,
        },
        "absolute_exclusions": [
            "credentials",
            "secrets",
            "tokens",
            "private_authentication_material",
            "patent_or_counsel_material",
            "legal_strategy_material",
            "confidential_audit_artifacts",
            "confidential_build_sink",
            "local_crosswalks",
            "provider_policy_evidence_bodies",
            "encrypted_snapshots",
            "unrelated_repository_content",
            "unclassified_paths",
        ],
        "mission_universe_immutable_after_execution_begins": True,
    })
    finding = _valid_finding(candidates=["resolver1"])
    decision = _valid_decision(resolver_mission_id="resolver1")

    with pytest.raises(ValueError, match="has no recorded outcome"):
        validate_resolver_decision(manifest, "m1", finding, decision, [])


def test_contract_sabotage_resolver_already_consumed_fails():
    """Classification: contract/sabotage
    Resolver already consumed, failed, refused, or blocked fails.
    """
    manifest = _valid_manifest(["m1", "resolver1"])
    finding = _valid_finding(candidates=["resolver1"])
    decision = _valid_decision(resolver_mission_id="resolver1")
    outcomes = [
        MissionOutcome.model_validate({
            "mission_id": "resolver1",
            "status": "success",
            "validation_result": "done",
        })
    ]

    with pytest.raises(ValueError, match="is already consumed"):
        validate_resolver_decision(manifest, "m1", finding, decision, outcomes)


def test_contract_sabotage_resolver_scope_expansion_fails():
    """Classification: contract/sabotage
    Resolver that requires scope expansion beyond its approved mission
    scope fails.
    """
    manifest = _valid_manifest(["m1", "resolver1"])
    finding = _valid_finding(candidates=["resolver1"])
    decision = _valid_decision(resolver_mission_id="resolver1")
    # Request owned paths outside the resolver's approved scope
    decision.requested_owned_paths = ["resolver1_owned", "extra_path"]

    with pytest.raises(ValueError, match="owned_path paths exceed approved"):
        validate_resolver_decision(manifest, "m1", finding, decision)
