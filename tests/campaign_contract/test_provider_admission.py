from __future__ import annotations

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract._provider_admission import (
    evaluate_provider_context_admission,
)
from rig_relay.campaign_contract._provider_models import (
    ProviderContextAdmissionRequest,
    ProviderContextItemDescriptor,
    ProviderDisclosurePolicyAttestation,
    generate_provider_policy_schema,
)
from rig_relay.campaign_contract.models import CampaignManifest

# ---- Shared helpers --------------------------------------------------

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


def _mission_dict(mission_id: str, provider_scope: list[str] | None = None):
    return {
        "mission_id": mission_id,
        "owned_path_scope": ["p1"],
        "read_context_scope": ["p2"],
        "provider_context_scope": provider_scope or [f"{mission_id}_ctx"],
        "validation_commands": ["v"],
        "prerequisites": [],
        "resolver_scope_declarations": [],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    }


def _manifest(
    missions: list[dict] | None = None,
    provider_mode: str = "hosted_confidential_full_source_user_approved",
) -> CampaignManifest:
    if missions is None:
        missions = [_mission_dict("m1")]

    if provider_mode == "provider_context_refused":
        attestation: dict = {
            "mode": "provider_context_refused",
            "transmission_prohibited": True,
        }
    else:
        attestation = {
            "mode": provider_mode,
            "provider_family_identity": "fam",
            "provider_model_identity": "model1",
            "actual_retention_control_mode_classification": "standard_retention",
            "campaign_scope_digest": "dig",
            "campaign_scope_approval_marker": True,
            "mission_level_provider_scope_enforcement_marker": True,
        }
    return CampaignManifest.model_validate({
        "ordered_missions": missions,
        "user_approval_marker": True,
        "operating_mode": "confidential_autonomous_campaign_nonpromoting",
        "provider_disclosure_attestation": attestation,
        "absolute_exclusions": list(_EXCLUSIONS),
        "mission_universe_immutable_after_execution_begins": True,
    })


def _attestation(
    campaign_mode: str = "hosted_confidential_full_source_user_approved",
    control_mode: str = "default_api_controls",
    full_source_approved: bool = True,
    minimized_source_approved: bool = False,
    zdr_verified: bool = False,
    mam_verified: bool = False,
    application_state: str = "retention_present_or_possible",
    prompt_cache: str = "cache_retention_unverified",
) -> ProviderDisclosurePolicyAttestation:
    return ProviderDisclosurePolicyAttestation.model_validate({
        "attestation_identity": "att1",
        "campaign_approved_provider_mode": campaign_mode,
        "provider_family_identity": "fam",
        "provider_model_identity": "model1",
        "endpoint_family": "responses",
        "provider_control_mode": control_mode,
        "campaign_scope_digest": "dig",
        "human_approval_marker": True,
        "mission_scope_enforcement_marker": True,
        "full_source_approved_marker": full_source_approved,
        "minimized_source_approved_marker": minimized_source_approved,
        "zero_data_retention_verified_marker": zdr_verified,
        "modified_abuse_monitoring_verified_marker": mam_verified,
        "abuse_monitoring_retention_classification": "default_30_day",
        "application_state_classification": application_state,
        "prompt_cache_retention_classification": prompt_cache,
        "permitted_capabilities": ["plain_text_request_only"],
        "refused_capabilities": [],
        "attestation_source_class": "fixture",
        "no_real_provider_request_in_this_slice_marker": True,
        "actual_provider_request_performed": False,
        "actual_external_transmission_performed": False,
    })


def _item(identity: str, classification: str) -> ProviderContextItemDescriptor:
    return ProviderContextItemDescriptor.model_validate({
        "normalized_identity": identity,
        "context_classification": classification,
        "identity_digest": f"sha256:{identity}",
    })


def _request(
    mission_id: str = "m1",
    mode: str = "hosted_confidential_full_source_user_approved",
    items: list[ProviderContextItemDescriptor] | None = None,
) -> ProviderContextAdmissionRequest:
    if items is None:
        items = [_item("m1_ctx", "mission_scoped_source_candidate")]
    return ProviderContextAdmissionRequest.model_validate({
        "attestation_identity": "att1",
        "campaign_identity": "c1",
        "mission_identity": mission_id,
        "requested_provider_context_mode": mode,
        "requested_context_items": [i.model_dump() for i in items],
        "requested_capabilities": ["plain_text_request_only"],
        "requested_endpoint_family": "responses",
        "minimum_necessary_purpose_label": "test",
        "human_approved_campaign_identity_reference": "c1",
    })


# ---- Schema surface tests --------------------------------------------


def test_contract_substrate_provider_policy_schema_self_validates():
    """Classification: contract/substrate
    Provider policy attestation schema validates itself with Draft 2020-12
    and exposes reachable definitions for all required contract surfaces.
    """
    schema = generate_provider_policy_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    defs = schema.get("$defs", {})
    required = [
        "ProviderDisclosurePolicyAttestation",
        "ProviderContextItemDescriptor",
        "ProviderContextAdmissionRequest",
        "ProviderContextAdmissionDecision",
    ]
    for surface in required:
        assert surface in defs, f"Missing $def: {surface}"


# ---- Provider control verification tests -----------------------------


def test_contract_integration_default_api_controls_no_overclaim():
    """Classification: contract/integration
    Default API controls can be represented without claiming ZDR, MAM,
    no-retention, no-application-state, or verified prompt-cache behavior.
    """
    att = _attestation(
        control_mode="default_api_controls",
        zdr_verified=False,
        mam_verified=False,
        application_state="retention_present_or_possible",
        prompt_cache="cache_retention_unverified",
    )
    assert att.provider_control_mode == "default_api_controls"
    assert att.zero_data_retention_verified_marker is False
    assert att.modified_abuse_monitoring_verified_marker is False


def test_contract_sabotage_default_controls_claiming_zdr_fails():
    """Classification: contract/sabotage
    Default controls attempting to claim ZDR fails closed.
    """
    with pytest.raises(ValidationError):
        _attestation(control_mode="default_api_controls", zdr_verified=True)


def test_contract_sabotage_zdr_mode_without_verified_marker_fails():
    """Classification: contract/sabotage
    ZDR mode without explicit verified marker fails closed.
    """
    with pytest.raises(ValidationError):
        _attestation(control_mode="zero_data_retention_verified", zdr_verified=False)


def test_contract_sabotage_mam_mode_without_verified_marker_fails():
    """Classification: contract/sabotage
    MAM mode without explicit verified marker fails closed.
    """
    with pytest.raises(ValidationError):
        _attestation(
            control_mode="modified_abuse_monitoring_verified", mam_verified=False
        )


def test_contract_integration_verified_zdr_text_only_validates():
    """Classification: contract/integration
    Verified ZDR fixture policy for an approved text-only eligible endpoint
    validates without making a provider request.
    """
    att = _attestation(
        control_mode="zero_data_retention_verified",
        zdr_verified=True,
        application_state="retention_present_or_possible",
        prompt_cache="cache_retention_unverified",
    )
    assert att.actual_provider_request_performed is False
    assert att.actual_external_transmission_performed is False


# ---- Campaign mode refusal tests -------------------------------------


def test_contract_sabotage_provider_context_refused_campaign_refuses():
    """Classification: contract/sabotage
    Provider-context-refused campaign mode refuses admission.
    """
    manifest = _manifest(provider_mode="provider_context_refused")
    att = _attestation(
        campaign_mode="provider_context_refused",
        full_source_approved=False,
        minimized_source_approved=False,
    )
    req = _request(mode="hosted_confidential_full_source_user_approved")
    with pytest.raises(ValidationError):
        # Cannot even construct a request for refused mode
        ProviderContextAdmissionRequest.model_validate({
            "attestation_identity": "att1",
            "campaign_identity": "c1",
            "mission_identity": "m1",
            "requested_provider_context_mode": "provider_context_refused",
            "requested_context_items": [],
            "requested_capabilities": ["plain_text_request_only"],
            "requested_endpoint_family": "responses",
            "minimum_necessary_purpose_label": "test",
            "human_approved_campaign_identity_reference": "c1",
        })

    # For refused-mode manifest, admission must refuse
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_campaign_provider_context_disabled"


def test_contract_sabotage_full_source_without_explicit_approval_refuses():
    """Classification: contract/sabotage
    Full-source request without explicit full-source human approval refuses
    at the model validator level (attestation cannot be constructed).
    """
    manifest = _manifest()
    # Creating an attestation with full_source_approved=False while
    # campaign_approved_provider_mode=full-source should fail model validation
    with pytest.raises(ValidationError):
        _attestation(full_source_approved=False)
    # Now test via admission: attestation mode mismatch with manifest mode
    att = _attestation(
        campaign_mode="hosted_confidential_minimized_user_approved",
        full_source_approved=False,
        minimized_source_approved=True,
    )
    req = _request()
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_mode_not_approved"


def test_contract_sabotage_minimized_source_without_approval_refuses():
    """Classification: contract/sabotage
    Minimized-source request without explicit minimized approval refuses
    at the model validator level.
    """
    # Creating attestation with minimized_source_approved=False while
    # campaign_approved_provider_mode=minimized should fail
    with pytest.raises(ValidationError):
        _attestation(
            campaign_mode="hosted_confidential_minimized_user_approved",
            full_source_approved=False,
            minimized_source_approved=False,
        )
    # Admission service also refuses when modes don't match
    manifest = _manifest(provider_mode="hosted_confidential_minimized_user_approved")
    att = _attestation(
        campaign_mode="hosted_confidential_full_source_user_approved",
        minimized_source_approved=False,
    )
    req = _request(mode="hosted_confidential_minimized_user_approved")
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_mode_not_approved"


# ---- Mission scope containment tests ---------------------------------


def test_contract_sabotage_context_outside_mission_scope_refuses():
    """Classification: contract/sabotage
    Requested provider-context path outside the selected mission's approved
    scope refuses admission.
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(items=[_item("outside_path", "mission_scoped_source_candidate")])
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_mission_scope_expansion"


def test_contract_sabotage_unknown_mission_id_refuses():
    """Classification: contract/sabotage
    An unknown mission ID refuses admission (caller cannot supply forged
    mission authority).
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(mission_id="nonexistent")
    decision = evaluate_provider_context_admission(manifest, "nonexistent", att, req)
    assert decision.admission_outcome == "refused_mission_scope_expansion"


# ---- Exclusion classification tests ----------------------------------


def test_contract_sabotage_each_excluded_classification_halts_campaign():
    """Classification: contract/sabotage
    Request intersecting every absolute exclusion classification is refused
    through the production admission service with halt_campaign outcome.
    """
    excluded_classifications = [
        "credential_or_secret_refused",
        "private_authentication_material_refused",
        "patent_or_counsel_material_refused",
        "legal_strategy_material_refused",
        "confidential_audit_artifact_refused",
        "confidential_sink_descendant_refused",
        "local_crosswalk_refused",
        "provider_policy_evidence_body_refused",
        "encrypted_snapshot_refused",
        "unrelated_repository_content_refused",
        "unclassified_path_refused",
    ]
    manifest = _manifest()
    att = _attestation()
    for classification in excluded_classifications:
        item = _item(f"excluded_{classification}", classification)
        # Add a mission-scoped item too so scope check passes before exclusion
        req = _request(items=[_item("m1_ctx", "mission_scoped_source_candidate"), item])
        decision = evaluate_provider_context_admission(manifest, "m1", att, req)
        assert decision.admission_outcome == (
            "halt_campaign_security_or_confidentiality_boundary"
        ), f"Expected halt for classification '{classification}'"
        assert decision.refusal_category is not None


# ---- Endpoint and capability refusal tests ---------------------------


def test_contract_sabotage_unknown_endpoint_refuses():
    """Classification: contract/sabotage
    Request for unknown endpoint family refuses admission.
    """
    manifest = _manifest()
    att = _attestation()
    req = ProviderContextAdmissionRequest.model_validate({
        "attestation_identity": "att1",
        "campaign_identity": "c1",
        "mission_identity": "m1",
        "requested_provider_context_mode": "hosted_confidential_full_source_user_approved",
        "requested_context_items": [
            _item("m1_ctx", "mission_scoped_source_candidate").model_dump()
        ],
        "requested_capabilities": ["plain_text_request_only"],
        "requested_endpoint_family": "unknown_refused",
        "minimum_necessary_purpose_label": "test",
        "human_approved_campaign_identity_reference": "c1",
    })
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_endpoint_or_capability"


def test_contract_sabotage_non_text_capabilities_refuse():
    """Classification: contract/sabotage
    Request for hosted container, remote MCP, file/image input, background
    mode, stateful conversation, thread/assistant, vector/file store, web
    search/external tool, or unknown capability refuses admission.
    """
    refused_caps = [
        "hosted_container_refused",
        "remote_mcp_refused",
        "file_image_input_refused",
        "background_mode_refused",
        "stateful_conversation_refused",
        "thread_or_assistant_refused",
        "vector_store_or_file_store_refused",
        "web_search_or_external_tool_refused",
        "unknown_capability_refused",
    ]
    manifest = _manifest()
    att = _attestation()
    for cap in refused_caps:
        req = ProviderContextAdmissionRequest.model_validate({
            "attestation_identity": "att1",
            "campaign_identity": "c1",
            "mission_identity": "m1",
            "requested_provider_context_mode": "hosted_confidential_full_source_user_approved",
            "requested_context_items": [
                _item("m1_ctx", "mission_scoped_source_candidate").model_dump()
            ],
            "requested_capabilities": [cap],
            "requested_endpoint_family": "responses",
            "minimum_necessary_purpose_label": "test",
            "human_approved_campaign_identity_reference": "c1",
        })
        decision = evaluate_provider_context_admission(manifest, "m1", att, req)
        assert decision.admission_outcome == ("refused_endpoint_or_capability"), (
            f"Expected refusal for capability '{cap}'"
        )


# ---- Application state / cache retention tests -----------------------


def test_contract_sabotage_unverified_no_application_state_refuses():
    """Classification: contract/sabotage
    Request claiming verified no-application-state behavior without
    supporting endpoint/control attestation refuses admission.
    """
    manifest = _manifest()
    # Create attestation with ZDR verified but application state classification
    # that is valid for ZDR mode
    att = _attestation(
        control_mode="zero_data_retention_verified",
        zdr_verified=True,
        application_state="retention_present_or_possible",
    )
    req = _request()
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "admitted_for_future_transport_layer"

    # Now test: default_api_controls with no_application_state_claim_unverified
    # should be refused by the admission service
    att2 = _attestation(
        control_mode="default_api_controls",
        application_state="no_application_state_claim_unverified",
    )
    req2 = _request()
    decision2 = evaluate_provider_context_admission(manifest, "m1", att2, req2)
    assert decision2.admission_outcome == "refused_unverified_provider_control_claim"


def test_contract_sabotage_unverified_cache_retention_refuses():
    """Classification: contract/sabotage
    Request claiming verified prompt-cache retention or cache eligibility
    without explicit attestation refuses admission.
    """
    manifest = _manifest()
    # Create attestation with cache_retention_verified under default controls
    # This should pass model validation but be refused by admission service
    att = _attestation(
        control_mode="default_api_controls", prompt_cache="cache_retention_verified"
    )
    req = _request()
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "refused_unverified_provider_control_claim"

    # cache_retention_unverified under default controls should be admitted
    att2 = _attestation(prompt_cache="cache_retention_unverified")
    req2 = _request()
    decision2 = evaluate_provider_context_admission(manifest, "m1", att2, req2)
    assert decision2.admission_outcome == "admitted_for_future_transport_layer"


# ---- Successful admission tests --------------------------------------


def test_contract_integration_full_source_within_scope_admitted():
    """Classification: contract/integration
    A properly approved full-source fixture request within one mission's
    declared provider-context scope returns only admitted_for_future_transport_layer.
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(items=[_item("m1_ctx", "mission_scoped_source_candidate")])
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "admitted_for_future_transport_layer"


def test_contract_integration_minimized_source_within_scope_admitted():
    """Classification: contract/integration
    A properly approved minimized-source fixture request within declared
    scope returns only admitted_for_future_transport_layer.
    """
    manifest = _manifest(provider_mode="hosted_confidential_minimized_user_approved")
    att = _attestation(
        campaign_mode="hosted_confidential_minimized_user_approved",
        full_source_approved=False,
        minimized_source_approved=True,
    )
    req = _request(
        mode="hosted_confidential_minimized_user_approved",
        items=[_item("m1_ctx", "mission_scoped_source_candidate")],
    )
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "admitted_for_future_transport_layer"


# ---- Content-light / transmission marker tests -----------------------


def test_contract_adversarial_decision_contains_no_raw_source_or_secret():
    """Classification: contract/adversarial
    Admission decision contains no raw source, prompt, provider-context body,
    secret sentinel, crosswalk, or evidence body.
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(items=[_item("m1_ctx", "mission_scoped_source_candidate")])
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    raw = decision.model_dump_json()
    assert "secret_sentinel" not in raw
    assert "API_KEY" not in raw
    assert "password" not in raw
    assert "BEGIN PRIVATE KEY" not in raw


def test_contract_integration_admission_markers_all_false():
    """Classification: contract/integration
    Successful admission explicitly records all transmission/observation
    markers as false and human transport activation as still required.
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(items=[_item("m1_ctx", "mission_scoped_source_candidate")])
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "admitted_for_future_transport_layer"
    assert decision.provider_request_performed is False
    assert decision.external_transmission_performed is False
    assert decision.source_body_in_decision is False
    assert decision.secret_body_in_decision is False
    assert decision.actual_retention_behavior_observed is False
    assert decision.actual_zdr_operation_observed is False
    assert decision.actual_prompt_cache_behavior_observed is False
    assert decision.human_transport_activation_still_required is True


# ---- Security halt mapping test --------------------------------------


def test_contract_integration_exclusion_decision_maps_to_halt():
    """Classification: contract/integration
    Security/confidentiality exclusion decisions map through the accepted
    campaign halt policy to halt_entire_campaign.
    """
    manifest = _manifest()
    att = _attestation()
    req = _request(
        items=[
            _item("m1_ctx", "mission_scoped_source_candidate"),
            _item("secret_file", "credential_or_secret_refused"),
        ]
    )
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == (
        "halt_campaign_security_or_confidentiality_boundary"
    )
    assert decision.refusal_category is not None


# ---- ZDR does not imply no-application-state test --------------------


def test_contract_sabotage_zdr_does_not_imply_no_application_state():
    """Classification: contract/sabotage
    Verified ZDR fixture admission does not imply observed ZDR behavior
    or no application state.
    """
    manifest = _manifest()
    att = _attestation(
        control_mode="zero_data_retention_verified",
        zdr_verified=True,
        application_state="retention_present_or_possible",
    )
    req = _request(items=[_item("m1_ctx", "mission_scoped_source_candidate")])
    decision = evaluate_provider_context_admission(manifest, "m1", att, req)
    assert decision.admission_outcome == "admitted_for_future_transport_layer"
    assert decision.actual_zdr_operation_observed is False
    assert decision.actual_retention_behavior_observed is False


# ---- Real-artifact schema identity test ------------------------------


def test_integration_real_artifact_provider_policy_schema_identity():
    """Classification: integration/real-artifact
    Deterministically emits provider-policy schema identity/hash.
    """
    from rig_relay.campaign_contract._provider_models import (
        compute_provider_policy_schema_identity,
    )

    identity = compute_provider_policy_schema_identity()
    assert len(identity) == 64  # SHA-256 hex
    assert identity == compute_provider_policy_schema_identity()  # deterministic


# ---- Attestation self-validation extra tests -------------------------


def test_contract_sabotage_default_controls_claiming_mam_fails():
    """Classification: contract/sabotage
    Default API controls claiming MAM verified fails closed.
    """
    with pytest.raises(ValidationError):
        _attestation(control_mode="default_api_controls", mam_verified=True)


def test_contract_sabotage_refused_mode_with_approval_markers_fails():
    """Classification: contract/sabotage
    Provider-context-refused campaign mode cannot have approval markers.
    """
    with pytest.raises(ValidationError):
        _attestation(
            campaign_mode="provider_context_refused",
            full_source_approved=True,
            minimized_source_approved=False,
        )
