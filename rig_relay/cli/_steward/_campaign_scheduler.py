"""Mission scheduler and bounded repair runtime for campaign execution.

Implements execution semantics: sequential missions, blocker detection,
resolver promotion, and bounded incidental repair evaluation.
"""

from __future__ import annotations

from rig_relay.campaign_contract.models import (
    BlockingFinding,
    BoundedIncidentalUnblockRepairDecision,
    CampaignManifest,
    MissionDefinition,
    ResolverEvaluationDecision,
)
from rig_relay.campaign_contract.validation import validate_resolver_decision
from rig_relay.cli._steward._campaign_models import CampaignState

_MAX_BOUNDED_REPAIR_SOURCE_PATHS = 3


def find_next_eligible_mission(
    manifest: CampaignManifest, state: CampaignState
) -> MissionDefinition | None:
    """Find the next eligible mission in approved order.

    Returns None if all missions are complete or paused.
    """
    for mission in manifest.ordered_missions:
        if mission.mission_id in state.completed_missions:
            continue
        if mission.mission_id in state.paused_missions:
            continue
        if any(
            prereq not in state.completed_missions for prereq in mission.prerequisites
        ):
            continue
        return mission
    return None


def record_blocked_finding(
    campaign_id: str, root_path: object, mission: MissionDefinition, reason: str
) -> dict:
    """Record a structured blocker finding.

    The finding goes into the campaign findings ledger.
    """
    return {
        "campaign_id": campaign_id,
        "mission_id": mission.mission_id,
        "finding_class": "out_of_scope_blocker_without_approved_resolver",
        "reason": reason,
        "blocked_continuation_policy": mission.blocked_continuation_policy,
    }


def evaluate_resolver_promotion(
    manifest: CampaignManifest, blocked_mission: MissionDefinition, state: CampaignState
) -> MissionDefinition | None:
    """Find an eligible resolver mission for a blocked mission.

    Returns the resolver mission if one is found and eligible.
    """
    for candidate in manifest.ordered_missions:
        if candidate.mission_id == blocked_mission.mission_id:
            continue
        if candidate.mission_id in state.completed_missions:
            continue
        if candidate.mission_id in state.paused_missions:
            continue

        # Build a simple BlockingFinding and decision
        finding = BlockingFinding.model_validate({
            "finding_class": "out_of_scope_blocker_with_approved_resolver",
            "blocking_status": True,
            "affected_contract_clause": f"mission_{blocked_mission.mission_id}",
            "resolution_scope": "mission_impl",
            "candidate_approved_resolvers": [candidate.mission_id],
            "incidental_repair_eligibility": False,
            "end_of_campaign_disposition": "pending",
        })
        decision = ResolverEvaluationDecision.model_validate({
            "mission_id": blocked_mission.mission_id,
            "resolver_mission_id": candidate.mission_id,
            "is_approved": True,
            "reason_code": "resolver_candidate",
            "requested_owned_paths": candidate.owned_path_scope,
            "requested_read_context_paths": candidate.read_context_scope,
            "requested_provider_context_paths": candidate.provider_context_scope,
            "requested_resolution_scope": "mission_impl",
        })

        try:
            validate_resolver_decision(
                manifest, blocked_mission.mission_id, finding, decision, []
            )
            return candidate
        except ValueError:
            continue
    return None


def evaluate_bounded_repair(
    repair_decision: BoundedIncidentalUnblockRepairDecision,
) -> bool:
    """Evaluate whether a bounded incidental repair is admissible.

    Returns True if the repair passes all constraints.
    """
    constraints = [
        repair_decision.no_security_boundary_change,
        repair_decision.no_disclosure_boundary_change,
        repair_decision.no_dependency_change,
        repair_decision.no_policy_config_schema_family_change,
        repair_decision.no_shared_module_refactor,
        repair_decision.no_unsafe_fallback,
        repair_decision.no_test_weakening,
        repair_decision.bypass_prohibited,
        repair_decision.global_fixture_prohibited,
        repair_decision.lint_suppression_prohibited,
    ]
    if not all(c is True for c in constraints):
        return False
    if not (
        0
        <= repair_decision.out_of_scope_source_path_count
        <= _MAX_BOUNDED_REPAIR_SOURCE_PATHS
    ):
        return False
    return True


def record_mission_outcome(
    state: CampaignState, mission_id: str, status: str, validation_result: str
) -> CampaignState:
    """Record a mission outcome and update state."""
    if status == "success":
        if mission_id not in state.completed_missions:
            state.completed_missions.append(mission_id)
        if mission_id in state.paused_missions:
            state.paused_missions.remove(mission_id)
    elif status in {"failure", "refused", "blocked"}:
        if mission_id not in state.paused_missions:
            state.paused_missions.append(mission_id)
    return state
