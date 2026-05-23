from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import cast

from rig_relay.campaign_contract._context_classifier_models import (
    ClassificationBasis,
    ClassifiedProviderAdmissionResult,
    ClassifierOutcome,
    ContextClassificationDecision,
    ContextClassificationRequest,
    ProviderAdmissionRequestTemplate,
    SensitivityLabel,
    to_provider_context_item_descriptor,
)
from rig_relay.campaign_contract._provider_admission import (
    evaluate_provider_context_admission,
)
from rig_relay.campaign_contract._provider_models import (
    ProviderContextAdmissionRequest,
    ProviderContextItemClassification,
    ProviderDisclosurePolicyAttestation,
)
from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition

# ---- Constants -------------------------------------------------------

_MAX_FIXTURE_BYTES = 1024 * 1024  # 1 MB
_PERMITTED_SUFFIXES: frozenset[str] = frozenset({".py", ".txt"})

SENSITIVITY_LABEL_TO_CLASSIFICATION: dict[
    SensitivityLabel, ProviderContextItemClassification
] = {
    "credential_or_secret": "credential_or_secret_refused",
    "private_authentication_material": "private_authentication_material_refused",
    "patent_or_counsel_material": "patent_or_counsel_material_refused",
    "legal_strategy_material": "legal_strategy_material_refused",
    "confidential_audit_artifact": "confidential_audit_artifact_refused",
    "local_crosswalk": "local_crosswalk_refused",
    "provider_policy_evidence_body": "provider_policy_evidence_body_refused",
    "encrypted_snapshot": "encrypted_snapshot_refused",
    "unrelated_repository_content": "unrelated_repository_content_refused",
    "unclassified": "unclassified_path_refused",
    "none_declared": "mission_scoped_source_candidate",
}

_LABELS_THAT_REFUSE: frozenset[SensitivityLabel] = frozenset(
    k for k in SENSITIVITY_LABEL_TO_CLASSIFICATION if k != "none_declared"
)

_REFUSED_CONTENT_SIGNAL_PATTERNS: list[
    tuple[str, re.Pattern[str], ProviderContextItemClassification]
] = [
    (
        "private_key_marker",
        re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
        "credential_or_secret_refused",
    ),
    (
        "explicit_fixture_credential_marker",
        re.compile(
            r'(?:API_KEY|api_key|apiKey|apikey|SECRET_KEY|secret_key)\s*[=:]\s*["\']'
        ),
        "credential_or_secret_refused",
    ),
    (
        "explicit_fixture_token_marker",
        re.compile(
            r'(?:ACCESS_TOKEN|access_token|AUTH_TOKEN|auth_token)\s*[=:]\s*["\']'
        ),
        "credential_or_secret_refused",
    ),
    (
        "patent_or_counsel_marker",
        re.compile(r"PATENT_OR_COUNSEL_MATERIAL_MARKER"),
        "patent_or_counsel_material_refused",
    ),
    (
        "legal_strategy_marker",
        re.compile(r"LEGAL_STRATEGY_MATERIAL_MARKER"),
        "legal_strategy_material_refused",
    ),
    (
        "confidential_audit_marker",
        re.compile(r"CONFIDENTIAL_AUDIT_ARTIFACT_MARKER"),
        "confidential_audit_artifact_refused",
    ),
]

_RESIDUAL_SCANNER_NOTE = "non_comprehensive_scanner"


# ---- Helpers ---------------------------------------------------------


def _compute_identity_digest(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _compute_root_digest(root: Path) -> str:
    resolved = root.resolve()
    return hashlib.sha256(
        json.dumps(str(resolved), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _make_decision(
    request: ContextClassificationRequest,
    normalized: str,
    outcome: ClassifierOutcome,
    basis: ClassificationBasis,
    *,
    content_read: bool = False,
    halt: bool = False,
    classification: ProviderContextItemClassification | None = None,
    reason: str | None = None,
    signal_family: str | None = None,
    risk_markers: list[str] | None = None,
) -> ContextClassificationDecision:
    decision_id = hashlib.sha256(
        json.dumps(
            {
                "request": request.classification_request_identity,
                "identity": normalized,
                "outcome": outcome,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ContextClassificationDecision.model_validate({
        "classification_decision_identity": decision_id,
        "campaign_identity": request.campaign_identity,
        "mission_identity": request.mission_identity,
        "normalized_identity": normalized,
        "identity_digest": _compute_identity_digest(normalized),
        "classifier_outcome": outcome,
        "provider_context_item_classification": classification,
        "classification_basis": basis,
        "pre_read_refusal_marker": not content_read,
        "content_read_performed": content_read,
        "content_signal_scan_performed": content_read,
        "campaign_halt_required": halt,
        "residual_risk_markers": risk_markers or [],
        "refusal_reason": reason,
        "signal_family": signal_family,
    })


def _check_labels(
    request: ContextClassificationRequest,
    labels: list[SensitivityLabel],
    normalized: str,
) -> ContextClassificationDecision | None:
    present = [lbl for lbl in labels if lbl in _LABELS_THAT_REFUSE]
    if "unclassified" in present:
        return _make_decision(
            request,
            normalized,
            "halt_security_or_confidentiality_boundary",
            "pre_read_sensitivity_label_refusal",
            halt=True,
            classification="unclassified_path_refused",
            reason="explicit 'unclassified' label — fail closed",
        )
    refused = [lbl for lbl in present if lbl != "unclassified"]
    if refused:
        first = cast(SensitivityLabel, refused[0])
        return _make_decision(
            request,
            normalized,
            "halt_security_or_confidentiality_boundary",
            "pre_read_sensitivity_label_refusal",
            halt=True,
            classification=SENSITIVITY_LABEL_TO_CLASSIFICATION[first],
            reason=f"explicit sensitivity label '{first}'",
        )
    return None


# ---- Public API ------------------------------------------------------


def resolve_and_validate_fixture_candidate_path(
    candidate_path: str, fixture_root_dir: Path
) -> Path:
    if not candidate_path:
        raise ValueError("empty candidate path")
    if Path(candidate_path).is_absolute():
        raise ValueError("absolute candidate path refused")
    if ".." in Path(candidate_path).parts:
        raise ValueError("path traversal refused")
    resolved_root = fixture_root_dir.resolve()
    candidate = (resolved_root / candidate_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise ValueError("candidate resolves outside fixture root") from None
    if not candidate.exists():
        raise ValueError(f"candidate '{candidate_path}' does not exist")
    if not candidate.is_file():
        raise ValueError(f"candidate '{candidate_path}' is not a regular file")
    if candidate.suffix not in _PERMITTED_SUFFIXES:
        raise ValueError(f"unsupported suffix '{candidate.suffix}'")
    if candidate.stat().st_size > _MAX_FIXTURE_BYTES:
        raise ValueError(
            f"candidate size {candidate.stat().st_size} exceeds max {_MAX_FIXTURE_BYTES}"
        )
    return candidate


def compute_fixture_root_digest(root: Path) -> str:
    return _compute_root_digest(root)


def _resolve_mission_from_manifest(
    manifest: CampaignManifest, mission_id: str
) -> MissionDefinition | None:
    candidates = [m for m in manifest.ordered_missions if m.mission_id == mission_id]
    if len(candidates) == 1:
        return candidates[0]
    return None


def classify_context_candidate_pre_read(
    request: ContextClassificationRequest,
    manifest: CampaignManifest,
    mission_id: str,
    fixture_root_dir: Path,
) -> ContextClassificationDecision:
    """Pre-read classification boundary."""
    n = request.candidate_relative_path

    # Mission + root digest: both produce same non-halting refusal
    resolved = _resolve_mission_from_manifest(manifest, mission_id)
    authority_err: tuple[ClassificationBasis, str] | None = None
    if resolved is None:
        cnt = len([m for m in manifest.ordered_missions if m.mission_id == mission_id])
        authority_err = (
            "pre_read_mission_authority_refusal",
            f"mission '{mission_id}' not in manifest"
            if cnt == 0
            else f"duplicate mission id '{mission_id}'",
        )
    elif request.approved_fixture_root_digest != _compute_root_digest(fixture_root_dir):
        authority_err = (
            "pre_read_root_digest_mismatch",
            "fixture root digest mismatch",
        )
    if authority_err:
        return _make_decision(
            request,
            n,
            "refused_mission_scope_expansion",
            authority_err[0],
            halt=False,
            reason=authority_err[1],
        )
    assert resolved is not None  # guaranteed by authority_err None above

    p = Path(n)
    lex_err = (
        "invalid candidate path"
        if (not n or p.is_absolute() or ".." in p.parts)
        else None
    )
    label_d = (
        None
        if lex_err
        else _check_labels(request, request.explicit_sensitivity_labels, n)
    )
    if label_d:
        return label_d
    if lex_err:
        return _make_decision(
            request,
            n,
            "refused_mission_scope_expansion",
            "pre_read_path_integrity_refusal",
            halt=False,
            reason=lex_err,
        )

    try:
        candidate = resolve_and_validate_fixture_candidate_path(n, fixture_root_dir)
    except ValueError as e:
        return _make_decision(
            request,
            n,
            "refused_mission_scope_expansion",
            "pre_read_path_integrity_refusal",
            halt=False,
            reason=str(e),
        )

    sink_err: str | None = None
    try:
        rel = candidate.relative_to(fixture_root_dir.resolve())
        if rel.parts and rel.parts[0] == ".build":
            sink_err = ".build/rig-relay/confidential/ descendant"
    except ValueError:
        sink_err = "candidate resolves outside fixture root"
    if sink_err:
        return _make_decision(
            request,
            n,
            "halt_security_or_confidentiality_boundary",
            "pre_read_confidential_sink_descendant",
            classification="confidential_sink_descendant_refused",
            halt=True,
            reason=sink_err,
        )

    in_scope = n in frozenset(resolved.provider_context_scope)
    return _make_decision(
        request,
        n,
        "eligible_for_fixture_content_scan"
        if in_scope
        else "refused_mission_scope_expansion",
        "pre_read_path_and_scope_approved_no_label"
        if in_scope
        else "pre_read_scope_expansion",
        classification="mission_scoped_source_candidate" if in_scope else None,
        halt=False,
        reason=None if in_scope else f"'{n}' not in mission provider_context_scope",
    )


def scan_fixture_content_signals(
    resolved_path: Path,
) -> tuple[str, ProviderContextItemClassification] | None:
    content = resolved_path.read_text(encoding="utf-8")
    for signal_family, pattern, classification in _REFUSED_CONTENT_SIGNAL_PATTERNS:
        if pattern.search(content):
            return signal_family, classification
    return None


def classify_fixture_context_item(
    request: ContextClassificationRequest,
    manifest: CampaignManifest,
    mission_id: str,
    fixture_root_dir: Path,
) -> ContextClassificationDecision:
    """Full classification pipeline: pre-read + optional post-read scan."""
    pre_read = classify_context_candidate_pre_read(
        request, manifest, mission_id, fixture_root_dir
    )
    if pre_read.classifier_outcome != "eligible_for_fixture_content_scan":
        return pre_read

    candidate = resolve_and_validate_fixture_candidate_path(
        request.candidate_relative_path, fixture_root_dir
    )
    signal = scan_fixture_content_signals(candidate)
    n = request.candidate_relative_path
    if signal:
        return _make_decision(
            request,
            n,
            "halt_security_or_confidentiality_boundary",
            "post_read_content_signal_refusal",
            content_read=True,
            halt=True,
            classification=signal[1],
            signal_family=signal[0],
            reason=f"content signal '{signal[0]}' detected",
        )
    return _make_decision(
        request,
        n,
        "descriptor_ready_for_provider_admission",
        "post_read_no_refusal_signals",
        content_read=True,
        halt=False,
        classification="mission_scoped_source_candidate",
        risk_markers=[_RESIDUAL_SCANNER_NOTE],
    )


def evaluate_classified_fixture_context_for_provider_admission(
    *,
    classification_request: ContextClassificationRequest,
    manifest: CampaignManifest,
    mission_id: str,
    policy_attestation: ProviderDisclosurePolicyAttestation,
    request_template: ProviderAdmissionRequestTemplate,
    fixture_root_dir: Path,
) -> ClassifiedProviderAdmissionResult:
    """Orchestrate classification through to provider admission."""
    cd = classify_fixture_context_item(
        classification_request, manifest, mission_id, fixture_root_dir
    )

    if cd.classifier_outcome == "refused_mission_scope_expansion":
        return ClassifiedProviderAdmissionResult.model_validate({
            "classification_decision": cd.model_dump(),
            "admission_decision": None,
            "provider_admission_performed": False,
            "classification_only_refusal": True,
        })

    descriptor = to_provider_context_item_descriptor(cd)
    if descriptor is None:
        return ClassifiedProviderAdmissionResult.model_validate({
            "classification_decision": cd.model_dump(),
            "admission_decision": None,
            "provider_admission_performed": False,
            "classification_only_refusal": True,
        })

    admission_req = ProviderContextAdmissionRequest.model_validate({
        "attestation_identity": policy_attestation.attestation_identity,
        "campaign_identity": request_template.campaign_identity,
        "mission_identity": mission_id,
        "requested_provider_context_mode": (
            request_template.requested_provider_context_mode
        ),
        "requested_context_items": [descriptor.model_dump()],
        "requested_capabilities": request_template.requested_capabilities,
        "requested_endpoint_family": request_template.requested_endpoint_family,
        "minimum_necessary_purpose_label": (
            request_template.minimum_necessary_purpose_label
        ),
        "human_approved_campaign_identity_reference": (
            request_template.human_approved_campaign_identity_reference
        ),
    })

    ad = evaluate_provider_context_admission(
        manifest, mission_id, policy_attestation, admission_req
    )

    return ClassifiedProviderAdmissionResult.model_validate({
        "classification_decision": cd.model_dump(),
        "admission_decision": ad.model_dump(),
        "provider_admission_performed": True,
        "classification_only_refusal": False,
    })
