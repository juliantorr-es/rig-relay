from __future__ import annotations

from typing import cast

from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract.models import (
    CAMPAIGN_RECORD_ADAPTER,
    CampaignExecutionEvent,
    MissionState,
    RefusalCategory,
    StopOrRefusalDecision,
    compute_event_hash,
)
from rig_relay.campaign_contract.validation import (
    EventChainValidationError,
    validate_event_chain,
    validate_mission_transition,
    validate_refusal_disposition,
)

# ---- Helpers ---------------------------------------------------------


def _event(
    event_identity: str = "evt0",
    sequence: int = 0,
    prior_state: str = "queued",
    current_state: str = "running",
    reason_code: str = "started",
    previous_event_hash: str = "GENESIS",
    event_kind: str = "campaign_started",
) -> CampaignExecutionEvent:
    """Build an event and compute its hash."""
    d = {
        "event_identity": event_identity,
        "sequence": sequence,
        "event_kind": event_kind,
        "prior_state": prior_state,
        "current_state": current_state,
        "reason_code": reason_code,
        "previous_event_hash": previous_event_hash,
        "event_hash": "placeholder",
        "raw_source_bodies_prohibited": True,
        "raw_provider_context_bodies_prohibited": True,
    }
    tmp = CampaignExecutionEvent.model_validate(d)
    d["event_hash"] = compute_event_hash(tmp)
    return CampaignExecutionEvent.model_validate(d)


# ---- Transition validation tests -------------------------------------


def test_contract_adversarial_every_invalid_transition_refused():
    """Classification: contract/adversarial
    Every invalid mission transition tested is refused through the actual
    transition validator.
    """
    # Valid transitions
    assert validate_mission_transition("queued", "running")
    assert validate_mission_transition("running", "paused_out_of_scope_blocker")
    assert validate_mission_transition("running", "completed")
    assert validate_mission_transition("running", "failed_validation")
    assert validate_mission_transition("running", "refused_policy")
    assert validate_mission_transition(
        "paused_out_of_scope_blocker", "resolver_promoted_forward"
    )
    assert validate_mission_transition(
        "paused_out_of_scope_blocker", "incidental_unblock_repair_in_progress"
    )
    assert validate_mission_transition(
        "paused_out_of_scope_blocker", "unresolved_end_of_campaign"
    )
    assert validate_mission_transition(
        "failed_validation", "unresolved_end_of_campaign"
    )
    assert validate_mission_transition("refused_policy", "unresolved_end_of_campaign")
    assert validate_mission_transition(
        "unresolved_end_of_campaign", "skipped_dependency_blocked"
    )

    # Evidence-dependent transitions require evidence
    with pytest.raises(ValueError, match="requires valid resolver"):
        validate_mission_transition(
            "resolver_promoted_forward",
            "resumed_after_resolver",
            resolver_evidence_valid=False,
        )
    with pytest.raises(ValueError, match="requires valid repair"):
        validate_mission_transition(
            "incidental_unblock_repair_in_progress",
            "resumed_after_incidental_repair",
            repair_evidence_valid=False,
        )

    # Invalid transitions
    invalid_pairs = [
        ("completed", "running"),
        ("completed", "queued"),
        ("running", "queued"),
        ("running", "resumed_after_resolver"),
        ("queued", "paused_out_of_scope_blocker"),
        ("running", "skipped_dependency_blocked"),
        ("paused_out_of_scope_blocker", "running"),
        ("resolver_promoted_forward", "running"),
        ("incidental_unblock_repair_in_progress", "running"),
        ("unresolved_end_of_campaign", "running"),
        ("skipped_dependency_blocked", "running"),
    ]
    for prior, current in invalid_pairs:
        p = cast(MissionState, prior)
        c = cast(MissionState, current)
        with pytest.raises(ValueError, match="is not permitted"):
            validate_mission_transition(p, c)


def test_contract_integration_resolver_completion_to_resume_succeeds_with_evidence():
    """Classification: contract/integration
    Valid resolver-completion-to-resume transition succeeds only with
    resolver-resolution evidence.
    """
    # Without evidence → fails
    with pytest.raises(ValueError, match="requires valid resolver completion"):
        validate_mission_transition(
            "resolver_promoted_forward",
            "resumed_after_resolver",
            resolver_evidence_valid=False,
        )
    # With evidence → succeeds
    assert validate_mission_transition(
        "resolver_promoted_forward",
        "resumed_after_resolver",
        resolver_evidence_valid=True,
    )


def test_contract_integration_repair_to_resume_succeeds_with_evidence():
    """Classification: contract/integration
    Valid incidental-repair-to-resume transition succeeds only with
    validated repair-outcome evidence.
    """
    with pytest.raises(ValueError, match="requires valid repair completion"):
        validate_mission_transition(
            "incidental_unblock_repair_in_progress",
            "resumed_after_incidental_repair",
            repair_evidence_valid=False,
        )
    assert validate_mission_transition(
        "incidental_unblock_repair_in_progress",
        "resumed_after_incidental_repair",
        repair_evidence_valid=True,
    )


# ---- Transition enforcement through event chain ----------------------


def test_contract_sabotage_cryptographically_valid_but_state_illegal_chain_refused():
    """Classification: contract/sabotage
    Cryptographically valid but state-illegal event chain is refused by
    the production validate_event_chain function.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    # e1: cross-event consistent (prior="running" matches e0.current_state)
    # but uses an illegal internal transition: running → skipped_dependency_blocked
    e1 = _event(
        "evt1",
        1,
        "running",
        "skipped_dependency_blocked",
        "bad_jump",
        e0.event_hash,
        "mission_skipped_dependency_blocked",
    )
    with pytest.raises(EventChainValidationError, match="illegal state transition"):
        validate_event_chain([e0, e1])


def test_contract_sabotage_state_legal_but_hash_tampered_chain_refused():
    """Classification: contract/sabotage
    State-legal but hash-tampered event chain is refused.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "blocker",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    # Tamper with event hash
    tampered = e1.model_copy(update={"event_hash": "deadbeef0000"})
    with pytest.raises(EventChainValidationError, match="does not match computed"):
        validate_event_chain([e0, tampered])


def test_contract_integration_resolver_resumption_chain_succeeds_with_evidence():
    """Classification: contract/integration
    Valid resolver-resumption chain succeeds only with resolver completion
    evidence.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "blocker",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    e2 = _event(
        "evt2",
        2,
        "paused_out_of_scope_blocker",
        "resolver_promoted_forward",
        "resolver",
        e1.event_hash,
        "resolver_promoted_forward",
    )
    e3 = _event(
        "evt3",
        3,
        "resolver_promoted_forward",
        "resumed_after_resolver",
        "resolved",
        e2.event_hash,
        "mission_resumed",
    )
    # Structurally valid chain
    assert validate_event_chain([e0, e1, e2, e3])


def test_contract_integration_repair_resumption_chain_succeeds_with_evidence():
    """Classification: contract/integration
    Valid incidental-repair-to-resume chain succeeds only with validated
    repair-outcome evidence.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "blocker",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    e2 = _event(
        "evt2",
        2,
        "paused_out_of_scope_blocker",
        "incidental_unblock_repair_in_progress",
        "repair",
        e1.event_hash,
        "incidental_repair_authorized",
    )
    e3 = _event(
        "evt3",
        3,
        "incidental_unblock_repair_in_progress",
        "resumed_after_incidental_repair",
        "repaired",
        e2.event_hash,
        "mission_resumed",
    )
    assert validate_event_chain([e0, e1, e2, e3])


# ---- Event chain validation tests ------------------------------------


def test_contract_substrate_valid_event_chain_verifies():
    """Classification: contract/substrate
    Valid fixture event chain verifies under canonical deterministic
    hashing.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1", 1, "running", "completed", "done", e0.event_hash, "campaign_completed"
    )
    assert validate_event_chain([e0, e1])


def test_contract_sabotage_duplicate_event_identity_fails():
    """Classification: contract/sabotage
    Duplicate event ID in chain fails.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt0",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "dup",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    with pytest.raises(EventChainValidationError, match="duplicate"):
        validate_event_chain([e0, e1])


def test_contract_sabotage_sequence_gap_fails():
    """Classification: contract/sabotage
    Sequence gap in chain fails.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        5,
        "running",
        "paused_out_of_scope_blocker",
        "gap",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    with pytest.raises(EventChainValidationError, match="expected sequence"):
        validate_event_chain([e0, e1])


def test_contract_sabotage_genesis_marker_missing_fails():
    """Classification: contract/sabotage
    First event without GENESIS marker fails.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "not_genesis", "campaign_started"
    )
    with pytest.raises(EventChainValidationError, match="GENESIS"):
        validate_event_chain([e0])


def test_contract_sabotage_prior_hash_mismatch_fails():
    """Classification: contract/sabotage
    Prior-hash mismatch in chain fails.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "mismatch",
        "wrong_hash_value_0123456789abcdef",
        "mission_paused_for_blocker",
    )
    with pytest.raises(EventChainValidationError, match="does not match"):
        validate_event_chain([e0, e1])


def test_contract_sabotage_event_hash_tamper_fails():
    """Classification: contract/sabotage
    Tampered event hash fails verification.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    e1 = _event(
        "evt1",
        1,
        "running",
        "paused_out_of_scope_blocker",
        "ok",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    # Tamper the event body but keep the hash
    tampered = e1.model_copy(update={"reason_code": "compromised"})
    tampered_dict = tampered.model_dump()
    with pytest.raises(EventChainValidationError, match="does not match computed"):
        validate_event_chain([e0, CampaignExecutionEvent.model_validate(tampered_dict)])


# ---- Refusal category mapping tests ----------------------------------

_SECURITY_CATEGORIES = [
    "confidential_evidence_sink_access",
    "secret_or_credential_detection",
    "provider_disclosure_outside_approved_scope",
    "attempted_checkpoint",
    "attempted_commit",
    "attempted_git_staging_ref_history_mutation",
    "attempted_promotion",
    "attempted_push",
    "attempted_publication",
    "attempted_upload",
    "attempted_public_render",
    "attempted_release_packaging",
    "attempted_telemetry_contribution_export",
    "attempted_github_mutation",
    "lane_integrity_failure",
    "event_ledger_chain_failure",
    "incidental_repair_security_disclosure_promotion_boundary_crossing",
]


def test_contract_sabotage_security_refusal_maps_only_to_halt_entire_campaign():
    """Classification: contract/sabotage
    Every security/confidentiality refusal category maps only to
    halt_entire_campaign.
    """
    for cat in _SECURITY_CATEGORIES:
        # Must accept halt_entire_campaign for this category
        StopOrRefusalDecision.model_validate({
            "decision": "halt_entire_campaign",
            "refusal_category": cat,
            "reason_code": "r",
        })

        # Must reject halt_dependent_chain for security categories
        with pytest.raises(ValidationError):
            StopOrRefusalDecision.model_validate({
                "decision": "halt_dependent_chain_continue_independent_approved_missions",
                "refusal_category": cat,
                "reason_code": "r",
            })

        # Must reject record_for_next_campaign for security categories
        with pytest.raises(ValidationError):
            StopOrRefusalDecision.model_validate({
                "decision": "record_for_next_campaign_continue_independent_approved_missions",
                "refusal_category": cat,
                "reason_code": "r",
            })

        # Also test the standalone validation function
        rc = cast(RefusalCategory, cat)
        assert validate_refusal_disposition(rc, "halt_entire_campaign")
        with pytest.raises(ValueError):
            validate_refusal_disposition(
                rc, "halt_dependent_chain_continue_independent_approved_missions"
            )


def test_contract_integration_ordinary_blocker_maps_to_dependent_chain_halt():
    """Classification: contract/integration
    Ordinary non-security blocker may map to dependent-chain halt with
    independent continuation.
    """
    # Valid: ordinary blocker → halt_dependent_chain
    StopOrRefusalDecision.model_validate({
        "decision": "halt_dependent_chain_continue_independent_approved_missions",
        "refusal_category": "ordinary_implementation_blocker",
        "reason_code": "r",
    })

    # Valid: ordinary blocker → record_for_next_campaign
    StopOrRefusalDecision.model_validate({
        "decision": "record_for_next_campaign_continue_independent_approved_missions",
        "refusal_category": "ordinary_implementation_blocker",
        "reason_code": "r",
    })

    # Invalid: ordinary blocker must not use halt_entire_campaign
    with pytest.raises(ValidationError):
        StopOrRefusalDecision.model_validate({
            "decision": "halt_entire_campaign",
            "refusal_category": "ordinary_implementation_blocker",
            "reason_code": "r",
        })


def test_contract_integration_completion_packet_refuses_true_markers():
    """Classification: contract/integration
    Completion packet refuses any true checkpoint/commit/promotion/push/
    publication or external-unapproved-transmission marker.
    """
    from tests.campaign_contract.test_models_and_schema import (
        _make_event_with_hash,
        _valid_completion_packet,
        _valid_lane_policy,
        _valid_manifest,
    )

    e0 = _make_event_with_hash(
        event_identity="evt0",
        sequence=0,
        prior_state="queued",
        current_state="running",
        previous_event_hash="GENESIS",
        event_kind="campaign_started",
    )
    e1 = _make_event_with_hash(
        event_identity="evt1",
        sequence=1,
        prior_state="running",
        current_state="completed",
        previous_event_hash=e0["event_hash"],
        event_kind="campaign_completed",
    )

    forbidden_markers = [
        ("checkpoint_performed", True),
        ("commit_performed", True),
        ("promotion_performed", True),
        ("push_performed", True),
        ("publication_performed", True),
        ("external_transmission_outside_approved_provider_context", True),
    ]
    for field, bad_value in forbidden_markers:
        pkt = _valid_completion_packet()
        pkt[field] = bad_value
        with pytest.raises(ValidationError):
            CAMPAIGN_RECORD_ADAPTER.validate_python({
                "record_stage": "completed",
                "manifest": _valid_manifest(),
                "lane_policy": _valid_lane_policy(),
                "campaign_execution_events": [e0, e1],
                "lane_identity": "lane1",
                "campaign_completion_packet": pkt,
            })


# ---- Cross-validator test: chain + transition integration -----------


def test_contract_sabotage_chain_with_incorrect_state_progression_refused():
    """Classification: contract/sabotage
    Event chain where prior/current state mismatches between adjacent
    events is refused.
    """
    e0 = _event(
        "evt0", 0, "queued", "running", "started", "GENESIS", "campaign_started"
    )
    # e1 says prior_state="completed" but e0 ended at "running"
    e1 = _event(
        "evt1",
        1,
        "completed",
        "paused_out_of_scope_blocker",
        "broken",
        e0.event_hash,
        "mission_paused_for_blocker",
    )
    with pytest.raises(EventChainValidationError, match="state mismatch"):
        validate_event_chain([e0, e1])
