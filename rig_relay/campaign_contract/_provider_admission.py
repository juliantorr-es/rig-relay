from __future__ import annotations

import hashlib
import json

from rig_relay.campaign_contract._provider_models import (
    EXCLUDED_ITEM_CLASSIFICATIONS,
    PERMITTED_CAPABILITIES,
    AdmissionOutcome,
    ProviderContextAdmissionDecision,
    ProviderContextAdmissionRequest,
    ProviderContextItemDescriptor,
    ProviderDisclosurePolicyAttestation,
)
from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
from rig_relay.campaign_contract.validation import validate_refusal_disposition

_PERMITTED_ENDPOINTS: frozenset[str] = frozenset({"responses", "chat_completions"})

_VALID_DEFAULT_APP_STATE: frozenset[str] = frozenset({
    "retention_present_or_possible",
    "application_state_use_refused",
    "unclassified_refused",
})

_VALID_ZDR_APP_STATE: frozenset[str] = frozenset({
    "retention_present_or_possible",
    "no_application_state_claim_unverified",
    "application_state_use_refused",
})


def _compute_scope_digest(items: list[ProviderContextItemDescriptor]) -> str:
    payload = json.dumps([i.normalized_identity for i in items], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_mode_consistency(
    manifest_mode: str,
    attestation_mode: str,
    request_mode: str,
    full_source_marker: bool,
    minimized_source_marker: bool,
) -> str | None:
    """Return refusal reason or None if modes are consistent."""
    if manifest_mode == "provider_context_refused":
        return "campaign provider mode is provider_context_refused"
    if attestation_mode != manifest_mode:
        return "attestation mode does not match manifest mode"
    if request_mode != manifest_mode:
        return "request mode does not match manifest mode"
    if manifest_mode == "hosted_confidential_full_source_user_approved":
        if not full_source_marker:
            return "full_source_approved_marker must be true"
    elif manifest_mode == "hosted_confidential_minimized_user_approved":
        if not minimized_source_marker:
            return "minimized_source_approved_marker must be true"
    return None


def _resolve_mission(
    manifest: CampaignManifest, mission_id: str, request_mission_id: str
) -> tuple[MissionDefinition | None, str | None]:
    """Resolve mission from manifest. Returns (mission, refusal_reason)."""
    candidates = [m for m in manifest.ordered_missions if m.mission_id == mission_id]
    if not candidates:
        return None, f"mission '{mission_id}' not in manifest"
    if len(candidates) > 1:
        return None, f"duplicate mission id '{mission_id}'"
    if request_mission_id != mission_id:
        return None, "request.mission_identity mismatch"
    return candidates[0], None


def _check_items(
    items: list[ProviderContextItemDescriptor], approved_scope: frozenset[str]
) -> str | None:
    """Return refusal reason or None. Halts on excluded; refuses on scope."""
    for item in items:
        if item.context_classification in EXCLUDED_ITEM_CLASSIFICATIONS:
            validate_refusal_disposition(
                "provider_disclosure_outside_approved_scope", "halt_entire_campaign"
            )
            return (
                f"halt: item '{item.normalized_identity}' classified as "
                f"'{item.context_classification}'"
            )
        if item.context_classification == "mission_scoped_source_candidate":
            if item.normalized_identity not in approved_scope:
                return (
                    f"item '{item.normalized_identity}' not in "
                    "mission provider_context_scope"
                )
    return None


def _check_control_claims(policy: ProviderDisclosurePolicyAttestation) -> str | None:
    """Return refusal reason or None if control claims are valid."""
    pc = policy.provider_control_mode
    if pc == "default_api_controls":
        if policy.application_state_classification not in _VALID_DEFAULT_APP_STATE:
            return "default_api_controls cannot claim no application state"
        if policy.prompt_cache_retention_classification == "cache_retention_verified":
            return "default_api_controls cannot claim verified prompt-cache retention"
    elif pc == "zero_data_retention_verified":
        if policy.application_state_classification not in _VALID_ZDR_APP_STATE:
            return (
                "ZDR attestation cannot claim verified no application state "
                "in this fixture-only slice"
            )
    return None


def evaluate_provider_context_admission(
    manifest: CampaignManifest,
    mission_id: str,
    policy_attestation: ProviderDisclosurePolicyAttestation,
    request: ProviderContextAdmissionRequest,
) -> ProviderContextAdmissionDecision:
    """Evaluate a provider-context admission request against the campaign."""
    campaign_mode = manifest.provider_disclosure_attestation.mode
    scope_digest = _compute_scope_digest(request.requested_context_items)
    cid = request.campaign_identity
    control_mode = policy_attestation.provider_control_mode
    endpoint = request.requested_endpoint_family
    caps = request.requested_capabilities

    def _decide(
        outcome: AdmissionOutcome,
        *,
        admitted_digest: str | None = None,
        refusal_category: str | None = None,
        refusal_reason: str | None = None,
    ) -> ProviderContextAdmissionDecision:
        decision_id = hashlib.sha256(
            json.dumps(
                {
                    "campaign": cid,
                    "mission": mission_id,
                    "outcome": outcome,
                    "scope": scope_digest,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return ProviderContextAdmissionDecision.model_validate({
            "decision_identity": decision_id,
            "campaign_identity": cid,
            "mission_identity": mission_id,
            "admission_outcome": outcome,
            "refusal_category": refusal_category,
            "refusal_reason": refusal_reason,
            "approved_mode": str(campaign_mode),
            "attested_provider_control_mode": control_mode,
            "requested_scope_digest": scope_digest,
            "admitted_scope_digest": admitted_digest,
            "endpoint_family": endpoint,
            "capability_classifications": list(caps),
        })

    # Check mode consistency
    mode_err = _check_mode_consistency(
        str(campaign_mode),
        policy_attestation.campaign_approved_provider_mode,
        request.requested_provider_context_mode,
        policy_attestation.full_source_approved_marker,
        policy_attestation.minimized_source_approved_marker,
    )
    if mode_err:
        outcome: AdmissionOutcome = (
            "refused_campaign_provider_context_disabled"
            if campaign_mode == "provider_context_refused"
            else "refused_mode_not_approved"
        )
        return _decide(outcome, refusal_reason=mode_err)

    # Resolve mission from manifest
    resolved, mission_err = _resolve_mission(
        manifest, mission_id, request.mission_identity
    )
    if mission_err:
        return _decide("refused_mission_scope_expansion", refusal_reason=mission_err)

    # Check context items
    assert resolved is not None  # guaranteed by mission_err is None above
    approved_scope = frozenset(resolved.provider_context_scope)
    item_err = _check_items(request.requested_context_items, approved_scope)
    if item_err:
        return _decide(
            "halt_campaign_security_or_confidentiality_boundary"
            if item_err.startswith("halt:")
            else "refused_mission_scope_expansion",
            refusal_category=(
                "provider_disclosure_outside_approved_scope"
                if item_err.startswith("halt:")
                else None
            ),
            refusal_reason=item_err,
        )

    # Check endpoint and capabilities together
    endpoint_cap_err: str | None = None
    if endpoint not in _PERMITTED_ENDPOINTS:
        endpoint_cap_err = f"endpoint '{endpoint}' unknown or refused"
    else:
        for cap in caps:
            if cap not in PERMITTED_CAPABILITIES:
                endpoint_cap_err = f"capability '{cap}' not permitted"
                break
    if endpoint_cap_err:
        return _decide(
            "refused_endpoint_or_capability", refusal_reason=endpoint_cap_err
        )

    # Check control claims
    ctrl_err = _check_control_claims(policy_attestation)
    if ctrl_err:
        return _decide(
            "refused_unverified_provider_control_claim", refusal_reason=ctrl_err
        )

    # Admitted
    return _decide("admitted_for_future_transport_layer", admitted_digest=scope_digest)
