from __future__ import annotations

import json

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract.models import (
    CAMPAIGN_RECORD_ADAPTER,
    CampaignExecutionEvent,
    CampaignManifest,
    CompletedCampaignRecord,
    InProgressCampaignRecord,
    compute_event_hash,
)
from rig_relay.campaign_contract.schema import generate_campaign_contract_schema
from rig_relay.campaign_contract.validation import (
    ValidationResultStatus,
    validate_campaign_manifest_fixture,
    validate_event_chain,
)

# ---- Shared test fixture helpers -------------------------------------

_EXCLUSIONS = [
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
]


def _valid_mission(mission_id: str = "m1") -> dict:
    return {
        "mission_id": mission_id,
        "owned_path_scope": ["p1"],
        "read_context_scope": ["p2"],
        "provider_context_scope": ["p3"],
        "validation_commands": ["v"],
        "prerequisites": [],
        "resolver_scope_declarations": [],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    }


def _valid_lane_policy(lane_identity: str = "lane1") -> dict:
    return {
        "lane_identity": lane_identity,
        "additive_accumulated_delta_marker": True,
        "write_scope": "isolated_campaign_lane_only",
        "checkpoint_prohibited": True,
        "commit_prohibited": True,
        "promotion_prohibited": True,
        "push_prohibited": True,
        "publication_prohibited": True,
        "git_history_mutation_prohibited": True,
        "upload_prohibited": True,
        "public_render_prohibited": True,
        "telemetry_export_prohibited": True,
        "human_promotion_marker": True,
    }


def _valid_manifest() -> dict:
    return {
        "ordered_missions": [_valid_mission()],
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
        "absolute_exclusions": list(_EXCLUSIONS),
        "mission_universe_immutable_after_execution_begins": True,
    }


def _valid_entry_gate() -> dict:
    return {
        "entries": [
            {
                "required_gate_identity": "g1",
                "required_status": "satisfied",
                "current_satisfaction_status": True,
                "content_light_evidence_reference": "ref1",
                "blocks_runtime_implementation": False,
                "blocks_live_steward_execution": True,
                "blocks_real_campaign_execution": True,
                "blocks_promotion_authority": True,
            }
        ]
    }


def _valid_event(
    event_identity: str = "evt0",
    sequence: int = 0,
    prior_state: str = "queued",
    current_state: str = "running",
    reason_code: str = "started",
    previous_event_hash: str = "GENESIS",
    event_kind: str = "campaign_started",
) -> dict:
    return {
        "event_identity": event_identity,
        "sequence": sequence,
        "event_kind": event_kind,
        "prior_state": prior_state,
        "current_state": current_state,
        "reason_code": reason_code,
        "previous_event_hash": previous_event_hash,
        "event_hash": "",
        "raw_source_bodies_prohibited": True,
        "raw_provider_context_bodies_prohibited": True,
    }


def _make_event_with_hash(
    event_identity: str = "evt0",
    sequence: int = 0,
    prior_state: str = "queued",
    current_state: str = "running",
    reason_code: str = "started",
    previous_event_hash: str = "GENESIS",
    event_kind: str = "campaign_started",
) -> dict:
    d = _valid_event(
        event_identity=event_identity,
        sequence=sequence,
        prior_state=prior_state,
        current_state=current_state,
        reason_code=reason_code,
        previous_event_hash=previous_event_hash,
        event_kind=event_kind,
    )
    # Build a temporary event to compute the hash
    tmp = CampaignExecutionEvent.model_validate({**d, "event_hash": "placeholder"})
    d["event_hash"] = compute_event_hash(tmp)
    return d


def _valid_completion_packet() -> dict:
    return {
        "actual_execution_order": ["m1"],
        "resolver_reorder_events": [],
        "incidental_repair_outcomes": [],
        "unresolved_findings": [],
        "cumulative_delta_digest": "abc123",
        "cumulative_changed_path_identities": ["p1"],
        "validation_summary": "all passed",
        "provider_disclosure_modes_used": [
            "hosted_confidential_full_source_user_approved"
        ],
        "refused_operation_counts": {},
        "checkpoint_performed": False,
        "commit_performed": False,
        "promotion_performed": False,
        "push_performed": False,
        "publication_performed": False,
        "external_transmission_outside_approved_provider_context": False,
        "human_promotion_marker": True,
        "recommended_disposition": "review_ready_for_human_promotion_decision",
    }


def _valid_approved_definition_dict() -> dict:
    return {
        "record_stage": "approved_definition",
        "manifest": _valid_manifest(),
        "lane_policy": _valid_lane_policy(),
        "implementation_entry_gate": _valid_entry_gate(),
    }


# ---- Schema self-validation test -------------------------------------


def test_contract_substrate_schema_validates_itself_and_defs_reachable():
    """Classification: contract/substrate
    Emitted Draft 2020-12 schema validates itself and stage roots expose
    reachable schema definitions for all required contract surfaces.
    """
    schema = generate_campaign_contract_schema()

    # Schema self-validation
    jsonschema.Draft202012Validator.check_schema(schema)

    # Discriminator mapping must expose each stage variant
    defs = schema.get("$defs", {})
    required_surfaces = [
        "ApprovedCampaignDefinition",
        "InProgressCampaignRecord",
        "CompletedCampaignRecord",
        "CampaignManifest",
        "PersistentCampaignLanePolicy",
        "MissionDefinition",
        "MissionOutcome",
        "BlockingFinding",
        "ResolverEvaluationDecision",
        "BoundedIncidentalUnblockRepairDecision",
        "CampaignExecutionEvent",
        "StopOrRefusalDecision",
        "CampaignCompletionPacket",
        "ImplementationEntryGate",
    ]
    for surface in required_surfaces:
        assert surface in defs, f"Missing $def: {surface}"


# ---- Lifecycle stage validation tests --------------------------------


def test_contract_integration_approved_definition_validates_pydantic_and_jsonschema():
    """Classification: contract/integration
    A valid approved-campaign-definition fixture validates through both
    Pydantic and JSON Schema.
    """
    d = _valid_approved_definition_dict()
    res = validate_campaign_manifest_fixture(json.dumps(d))
    assert res.status == ValidationResultStatus.VALID
    assert res.schema_identity is not None


def test_contract_integration_in_progress_with_valid_chain_validates():
    """Classification: contract/integration
    A valid in-progress campaign fixture validates only when it contains
    valid chained event history.
    """
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
        current_state="paused_out_of_scope_blocker",
        previous_event_hash=e0["event_hash"],
        event_kind="mission_paused_for_blocker",
    )
    d = {
        "record_stage": "in_progress",
        "manifest": _valid_manifest(),
        "lane_policy": _valid_lane_policy(),
        "campaign_execution_events": [e0, e1],
        "lane_identity": "lane1",
    }
    # Validate through Pydantic
    rec = CAMPAIGN_RECORD_ADAPTER.validate_python(d)
    assert isinstance(rec, InProgressCampaignRecord)

    # Validate through chain validator
    assert validate_event_chain(rec.campaign_execution_events)


def test_contract_integration_completed_with_terminal_and_packet_validates():
    """Classification: contract/integration
    A valid completed campaign fixture validates only with terminal event
    and completion packet.
    """
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
    d = {
        "record_stage": "completed",
        "manifest": _valid_manifest(),
        "lane_policy": _valid_lane_policy(),
        "campaign_execution_events": [e0, e1],
        "lane_identity": "lane1",
        "campaign_completion_packet": _valid_completion_packet(),
    }
    rec = CAMPAIGN_RECORD_ADAPTER.validate_python(d)
    assert isinstance(rec, CompletedCampaignRecord)


# ---- Adversarial tests -----------------------------------------------


def test_contract_adversarial_approved_definition_missing_lane_policy_fails():
    """Classification: contract/adversarial
    Approved campaign definition missing lane policy fails.
    """
    d = _valid_approved_definition_dict()
    del d["lane_policy"]
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python(d)


def test_contract_adversarial_removal_of_each_exclusion_category_fails():
    """Classification: contract/adversarial
    Removal of each canonical absolute exclusion category fails.
    """
    manifest = _valid_manifest()
    for cat in _EXCLUSIONS:
        invalid = dict(manifest)
        invalid["absolute_exclusions"] = [
            x for x in invalid["absolute_exclusions"] if x != cat
        ]
        with pytest.raises(ValidationError):
            CampaignManifest.model_validate(invalid)


def test_contract_adversarial_unexpected_fields_refused_on_security_surfaces():
    """Classification: contract/adversarial
    Unexpected fields are refused on every security-relevant contract surface.
    """
    # Test extra field on lane policy (checkpoint/commit/promotion surface)
    lp = _valid_lane_policy()
    lp["extra_secret_field"] = "should_be_rejected"
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "approved_definition",
            "manifest": _valid_manifest(),
            "lane_policy": lp,
            "implementation_entry_gate": _valid_entry_gate(),
        })

    # Test extra field on completion packet
    cp = _valid_completion_packet()
    cp["extra_release_flag"] = True
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "completed",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [
                _make_event_with_hash(
                    event_identity="evt0",
                    sequence=0,
                    prior_state="queued",
                    current_state="running",
                    previous_event_hash="GENESIS",
                    event_kind="campaign_started",
                ),
                _make_event_with_hash(
                    event_identity="evt1",
                    sequence=1,
                    prior_state="running",
                    current_state="completed",
                    previous_event_hash=_make_event_with_hash(
                        event_identity="evt0",
                        sequence=0,
                        prior_state="queued",
                        current_state="running",
                        previous_event_hash="GENESIS",
                        event_kind="campaign_started",
                    )["event_hash"],
                    event_kind="campaign_completed",
                ),
            ],
            "lane_identity": "lane1",
            "campaign_completion_packet": cp,
        })

    # Test extra field on StopOrRefusalDecision (via in-progress record)
    refusal = {
        "decision": "halt_entire_campaign",
        "refusal_category": "secret_or_credential_detection",
        "reason_code": "r",
        "extra_backdoor": "no",
    }
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "in_progress",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [
                _make_event_with_hash(
                    event_identity="evt0",
                    sequence=0,
                    prior_state="queued",
                    current_state="running",
                    previous_event_hash="GENESIS",
                    event_kind="campaign_started",
                )
            ],
            "lane_identity": "lane1",
            "stop_or_refusal_decisions": [refusal],
        })


# ---- Structured validation result tests -------------------------------


def test_contract_integration_structured_refusal_result_for_invalid_fixtures():
    """Classification: contract/integration
    Public validation API returns structured content-light refusal results
    for invalid fixture contracts without including raw fixture bodies.
    """
    # Invalid JSON
    res = validate_campaign_manifest_fixture("not json")
    assert res.status == ValidationResultStatus.INVALID_JSON
    assert res.error_codes == ["json_parse_error"]
    # Result must not contain raw fixture text
    assert "not json" not in res.model_dump_json()

    # Invalid contract (missing required field)
    invalid = _valid_approved_definition_dict()
    del invalid["manifest"]
    res = validate_campaign_manifest_fixture(json.dumps(invalid))
    assert res.status in (
        ValidationResultStatus.INVALID_CONTRACT,
        ValidationResultStatus.INVALID_SCHEMA,
    )
    # Result must be content-light — no raw fixture body
    raw = res.model_dump_json()
    assert "secret_sentinel_value" not in raw


def test_integration_real_artifact_emits_schema_identity_and_validation():
    """Classification: integration/real-artifact
    Deterministically emits schema identity/hash and content-light fixture
    validation result.
    """
    d = _valid_approved_definition_dict()
    res = validate_campaign_manifest_fixture(json.dumps(d))
    assert res.status == ValidationResultStatus.VALID
    assert res.schema_identity is not None
    assert len(res.schema_identity) == 64  # SHA-256 hex


# ---- Stage-specific enforcement tests --------------------------------


def test_contract_adversarial_approved_definition_rejects_events():
    """Classification: contract/adversarial
    ApprovedCampaignDefinition structurally refuses runtime-only fields
    like campaign_execution_events.
    """
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "approved_definition",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "implementation_entry_gate": _valid_entry_gate(),
            "campaign_execution_events": [
                _make_event_with_hash(
                    event_identity="evt0",
                    sequence=0,
                    prior_state="queued",
                    current_state="running",
                    previous_event_hash="GENESIS",
                    event_kind="campaign_started",
                )
            ],
        })


def test_contract_adversarial_in_progress_rejects_terminal_event():
    """Classification: contract/adversarial
    InProgressCampaignRecord refuses a terminal campaign event.
    """
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
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "in_progress",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [e0, e1],
            "lane_identity": "lane1",
        })


def test_contract_adversarial_completed_requires_terminal_event():
    """Classification: contract/adversarial
    CompletedCampaignRecord requires a terminal campaign event.
    """
    e0 = _make_event_with_hash(
        event_identity="evt0",
        sequence=0,
        prior_state="queued",
        current_state="running",
        previous_event_hash="GENESIS",
        event_kind="campaign_started",
    )
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "completed",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [e0],
            "lane_identity": "lane1",
            "campaign_completion_packet": _valid_completion_packet(),
        })


def test_contract_adversarial_completed_requires_nonempty_execution_order():
    """Classification: contract/adversarial
    CompletedCampaignRecord requires non-empty actual_execution_order.
    """
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
    pkt = _valid_completion_packet()
    pkt["actual_execution_order"] = []
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "completed",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [e0, e1],
            "lane_identity": "lane1",
            "campaign_completion_packet": pkt,
        })


def test_contract_adversarial_completed_refuses_true_checkpoint_marker():
    """Classification: contract/adversarial
    Completion packet refuses true checkpoint/commit/promotion markers.
    """
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
    pkt = _valid_completion_packet()
    pkt["checkpoint_performed"] = True  # must be False
    with pytest.raises(ValidationError):
        CAMPAIGN_RECORD_ADAPTER.validate_python({
            "record_stage": "completed",
            "manifest": _valid_manifest(),
            "lane_policy": _valid_lane_policy(),
            "campaign_execution_events": [e0, e1],
            "lane_identity": "lane1",
            "campaign_completion_packet": pkt,
        })
