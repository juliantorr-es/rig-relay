from __future__ import annotations

from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract._context_classifier import (
    classify_fixture_context_item,
    compute_fixture_root_digest,
    evaluate_classified_fixture_context_for_provider_admission,
)
from rig_relay.campaign_contract._context_classifier_models import (
    ContextClassificationRequest,
    ProviderAdmissionRequestTemplate,
    generate_context_classifier_schema,
    to_provider_context_item_descriptor,
)
from rig_relay.campaign_contract._provider_models import (
    ProviderDisclosurePolicyAttestation,
)
from rig_relay.campaign_contract.models import CampaignManifest

# ---- Helpers ---------------------------------------------------------

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
        "provider_context_scope": provider_scope or ["scoped.py"],
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


def _template(
    mode: str = "hosted_confidential_full_source_user_approved",
) -> ProviderAdmissionRequestTemplate:
    return ProviderAdmissionRequestTemplate.model_validate({
        "campaign_identity": "c1",
        "requested_provider_context_mode": mode,
        "requested_capabilities": ["plain_text_request_only"],
        "requested_endpoint_family": "responses",
        "minimum_necessary_purpose_label": "test",
        "human_approved_campaign_identity_reference": "c1",
    })


def _attestation(
    campaign_mode: str = "hosted_confidential_full_source_user_approved",
    control_mode: str = "default_api_controls",
    full_source: bool = True,
    minimized_source: bool = False,
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
        "full_source_approved_marker": full_source,
        "minimized_source_approved_marker": minimized_source,
        "zero_data_retention_verified_marker": False,
        "modified_abuse_monitoring_verified_marker": False,
        "abuse_monitoring_retention_classification": "default_30_day",
        "application_state_classification": "retention_present_or_possible",
        "prompt_cache_retention_classification": "cache_retention_unverified",
        "permitted_capabilities": ["plain_text_request_only"],
        "refused_capabilities": [],
        "attestation_source_class": "fixture",
        "no_real_provider_request_in_this_slice_marker": True,
        "actual_provider_request_performed": False,
        "actual_external_transmission_performed": False,
    })


def _classification_request(
    root_digest: str,
    path: str = "scoped.py",
    labels: list[str] | None = None,
    mission_id: str = "m1",
) -> ContextClassificationRequest:
    return ContextClassificationRequest.model_validate({
        "classification_request_identity": "req1",
        "campaign_identity": "c1",
        "mission_identity": mission_id,
        "candidate_relative_path": path,
        "approved_fixture_root_digest": root_digest,
        "explicit_sensitivity_labels": labels or ["none_declared"],
        "minimum_necessary_purpose_label": "test",
        "fixture_only_marker": True,
        "real_confidential_source_processing_performed": False,
        "provider_request_performed": False,
        "external_transmission_performed": False,
    })


def _setup_fixture_root(
    tmp_path: Path, files: dict[str, str] | None = None
) -> tuple[Path, str]:
    """Create a temp fixture root with optional files. Returns (root, digest)."""
    root = tmp_path / "fixture_root"
    root.mkdir(parents=True, exist_ok=True)
    if files:
        for name, content in files.items():
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
    return root, compute_fixture_root_digest(root)


# ---- Schema tests -----------------------------------------------------


def test_contract_substrate_classifier_schema_self_validates():
    """Classification: contract/substrate
    Separate classifier schema validates as Draft 2020-12 and exposes
    reachable request and decision models.
    """
    schema = generate_context_classifier_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    defs = schema.get("$defs", {})
    for surface in [
        "ContextClassificationRequest",
        "ContextClassificationDecision",
        "ClassifiedProviderAdmissionResult",
    ]:
        assert surface in defs, f"Missing $def: {surface}"


def test_contract_adversarial_request_rejects_raw_body_fields(tmp_path):
    """Classification: contract/adversarial
    Request/decision models reject raw-source, prompt-body, credential-body,
    crosswalk-body, or evidence-body extra fields.
    """
    root, digest = _setup_fixture_root(tmp_path)
    base = {
        "classification_request_identity": "r1",
        "campaign_identity": "c1",
        "mission_identity": "m1",
        "candidate_relative_path": "f.py",
        "approved_fixture_root_digest": digest,
        "explicit_sensitivity_labels": ["none_declared"],
        "minimum_necessary_purpose_label": "test",
        "fixture_only_marker": True,
        "real_confidential_source_processing_performed": False,
        "provider_request_performed": False,
        "external_transmission_performed": False,
    }
    valid = dict(base)
    ContextClassificationRequest.model_validate(valid)
    for extra in ["raw_source", "prompt_body", "credential_body", "crosswalk_body"]:
        invalid = dict(base)
        invalid[extra] = "sensitive_content"
        with pytest.raises(ValidationError):
            ContextClassificationRequest.model_validate(invalid)


# ---- Pre-read refusal tests ------------------------------------------


def test_contract_sabotage_fixture_root_digest_mismatch_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Fixture-root digest mismatch refuses before read.
    """
    root1, correct_digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    root2 = tmp_path / "other_root"
    root2.mkdir(parents=True, exist_ok=True)
    wrong_digest = compute_fixture_root_digest(root2)
    manifest = _manifest()
    request = _classification_request(wrong_digest)
    decision = classify_fixture_context_item(request, manifest, "m1", root1)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.classification_basis == "pre_read_root_digest_mismatch"
    assert decision.content_read_performed is False
    assert decision.campaign_halt_required is False


def test_contract_sabotage_absolute_candidate_path_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Absolute candidate path refuses before read.
    """
    root, digest = _setup_fixture_root(tmp_path)
    manifest = _manifest()
    request = _classification_request(digest, path="/absolute/path.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_path_traversal_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Path traversal escape is refused before read.
    """
    root, digest = _setup_fixture_root(tmp_path)
    manifest = _manifest()
    request = _classification_request(digest, path="../outside.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_symlink_escape_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Symlink escape is refused before read.
    """
    root, digest = _setup_fixture_root(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("x=1")
    symlink = root / "link.py"
    symlink.symlink_to(outside)
    manifest = _manifest()
    request = _classification_request(digest, path="link.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_confidential_sink_descendant_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    .build/rig-relay/confidential/ descendant is refused before read.
    """
    root, digest = _setup_fixture_root(tmp_path)
    (root / ".build").mkdir()
    (root / ".build" / "confidential.py").write_text("x=1")
    manifest = _manifest()
    request = _classification_request(digest, path=".build/confidential.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.content_read_performed is False
    assert decision.campaign_halt_required is True


def test_contract_sabotage_outside_mission_scope_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Candidate path outside manifest-resolved mission provider-context scope
    is refused before read.  Non-halting ordinary refusal.
    """
    root, digest = _setup_fixture_root(tmp_path, {"outside.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(digest, path="outside.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.campaign_halt_required is False
    assert decision.content_read_performed is False


def test_contract_sabotage_unknown_mission_refuses_before_read(tmp_path):
    """Classification: contract/sabotage
    Unknown mission identity refuses before read.
    """
    root, digest = _setup_fixture_root(tmp_path)
    manifest = _manifest()
    request = _classification_request(digest, mission_id="nonexistent")
    decision = classify_fixture_context_item(request, manifest, "nonexistent", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_missing_file_refuses_before_scan(tmp_path):
    """Classification: contract/sabotage
    Missing file refuses before post-read scan.
    """
    root, digest = _setup_fixture_root(tmp_path)
    manifest = _manifest()
    request = _classification_request(digest, path="missing.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_directory_refuses_before_scan(tmp_path):
    """Classification: contract/sabotage
    Directory/non-regular-file candidate refuses before post-read scan.
    """
    root, digest = _setup_fixture_root(tmp_path)
    (root / "subdir").mkdir()
    manifest = _manifest()
    request = _classification_request(digest, path="subdir")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_oversized_fixture_refuses_before_scan(tmp_path):
    """Classification: contract/sabotage
    Oversized fixture candidate refuses before post-read scan.
    """
    root, digest = _setup_fixture_root(tmp_path, {"big.py": "x" * (1024 * 1024 + 1)})
    manifest = _manifest()
    request = _classification_request(digest, path="big.py")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


def test_contract_sabotage_unsupported_suffix_refuses_before_scan(tmp_path):
    """Classification: contract/sabotage
    Unsupported suffix refuses before post-read scan.
    """
    root, digest = _setup_fixture_root(tmp_path, {"data.json": "{}"})
    manifest = _manifest()
    request = _classification_request(digest, path="data.json")
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    assert decision.content_read_performed is False


# ---- Explicit classification label tests -----------------------------

_EXCLUDED_LABELS = [
    ("credential_or_secret", "credential_or_secret_refused"),
    ("private_authentication_material", "private_authentication_material_refused"),
    ("patent_or_counsel_material", "patent_or_counsel_material_refused"),
    ("legal_strategy_material", "legal_strategy_material_refused"),
    ("confidential_audit_artifact", "confidential_audit_artifact_refused"),
    ("local_crosswalk", "local_crosswalk_refused"),
    ("provider_policy_evidence_body", "provider_policy_evidence_body_refused"),
    ("encrypted_snapshot", "encrypted_snapshot_refused"),
    ("unrelated_repository_content", "unrelated_repository_content_refused"),
]


def test_contract_sabotage_each_excluded_label_halts_before_read(tmp_path):
    """Classification: contract/sabotage
    Each explicit refused sensitivity label maps to the correct refused
    provider descriptor and requires campaign halt without reading content.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    for label, expected_class in _EXCLUDED_LABELS:
        request = _classification_request(digest, path="scoped.py", labels=[label])
        decision = classify_fixture_context_item(request, manifest, "m1", root)
        assert (
            decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
        )
        assert decision.provider_context_item_classification == expected_class
        assert decision.content_read_performed is False
        assert decision.campaign_halt_required is True


def test_contract_sabotage_unclassified_label_fails_closed_before_read(tmp_path):
    """Classification: contract/sabotage
    'unclassified' label fails closed before read.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(digest, path="scoped.py", labels=["unclassified"])
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.provider_context_item_classification == "unclassified_path_refused"
    assert decision.content_read_performed is False


def test_contract_integration_none_declared_permits_fixture_scan(tmp_path):
    """Classification: contract/integration
    'none_declared' does not admit provider use directly; it permits only
    fixture content-signal scanning after path and scope checks pass.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "descriptor_ready_for_provider_admission"
    assert decision.content_read_performed is True
    assert "non_comprehensive_scanner" in decision.residual_risk_markers


# ---- Post-read fixture signal tests ----------------------------------


def test_contract_sabotage_private_key_marker_refused_after_read(tmp_path):
    """Classification: contract/sabotage
    Fixture private-key marker is refused after permitted read without
    emitting matched content.
    """
    root, digest = _setup_fixture_root(
        tmp_path, {"scoped.py": "x=1\n-----BEGIN RSA PRIVATE KEY-----\ny=2\n"}
    )
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.content_read_performed is True
    assert decision.signal_family == "private_key_marker"


def test_contract_sabotage_credential_marker_refused_after_read(tmp_path):
    """Classification: contract/sabotage
    Fixture explicit credential/token marker is refused after permitted
    read without emitting matched content.
    """
    root, digest = _setup_fixture_root(
        tmp_path, {"scoped.py": 'API_KEY = "sk-test123"\n'}
    )
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.content_read_performed is True
    assert decision.signal_family == "explicit_fixture_credential_marker"


def test_contract_sabotage_patent_counsel_marker_refused_after_read(tmp_path):
    """Classification: contract/sabotage
    Fixture explicit patent/counsel marker is refused after permitted read.
    """
    root, digest = _setup_fixture_root(
        tmp_path, {"scoped.py": "x=1\n# PATENT_OR_COUNSEL_MATERIAL_MARKER\n"}
    )
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.signal_family == "patent_or_counsel_marker"


def test_contract_sabotage_confidential_audit_marker_refused_after_read(tmp_path):
    """Classification: contract/sabotage
    Fixture explicit confidential-audit marker is refused after permitted read.
    """
    root, digest = _setup_fixture_root(
        tmp_path, {"scoped.py": "# CONFIDENTIAL_AUDIT_ARTIFACT_MARKER\nx=1"}
    )
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "halt_security_or_confidentiality_boundary"
    assert decision.signal_family == "confidential_audit_marker"


def test_contract_integration_clean_fixture_becomes_candidate(tmp_path):
    """Classification: contract/integration
    Approved mission-scoped fixture source containing none of the refused
    markers becomes mission_scoped_source_candidate, while recording the
    non-comprehensive-scanner residual-risk marker.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x = 1\ny = 2\n"})
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "descriptor_ready_for_provider_admission"
    assert (
        decision.provider_context_item_classification
        == "mission_scoped_source_candidate"
    )
    assert decision.campaign_halt_required is False
    assert "non_comprehensive_scanner" in decision.residual_risk_markers


# ---- Descriptor conversion tests -------------------------------------


def test_contract_integration_descriptor_conversion_for_valid_decision(tmp_path):
    """Classification: contract/integration
    A descriptor-ready decision converts to a ProviderContextItemDescriptor.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    desc = to_provider_context_item_descriptor(decision)
    assert desc is not None
    assert desc.context_classification == "mission_scoped_source_candidate"


def test_contract_sabotage_scope_refusal_does_not_become_security_descriptor(tmp_path):
    """Classification: contract/integration
    Ordinary mission-scope refusal is non-halting and is not converted into
    a sensitive refused descriptor.
    """
    root, digest = _setup_fixture_root(tmp_path, {"outside.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(
        digest, path="outside.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    assert decision.classifier_outcome == "refused_mission_scope_expansion"
    desc = to_provider_context_item_descriptor(decision)
    assert desc is None  # scope refusal does not produce a descriptor
    assert decision.campaign_halt_required is False


# ---- Provider admission orchestration tests --------------------------


def test_integration_real_artifact_full_source_admitted_via_orchestrator(tmp_path):
    """Classification: integration/real-artifact
    A permitted classified full-source fixture item converts into the
    accepted descriptor and receives only admitted_for_future_transport_layer
    from the existing provider-admission service.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    att = _attestation()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(),
        fixture_root_dir=root,
    )
    assert result.provider_admission_performed is True
    assert result.admission_decision is not None
    assert (
        result.admission_decision.admission_outcome
        == "admitted_for_future_transport_layer"
    )


def test_integration_real_artifact_minimized_source_admitted(tmp_path):
    """Classification: integration/real-artifact
    A permitted classified minimized-source fixture item converts into the
    accepted descriptor and receives only admitted_for_future_transport_layer.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest(provider_mode="hosted_confidential_minimized_user_approved")
    att = _attestation(
        campaign_mode="hosted_confidential_minimized_user_approved",
        full_source=False,
        minimized_source=True,
    )
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(mode="hosted_confidential_minimized_user_approved"),
        fixture_root_dir=root,
    )
    assert result.provider_admission_performed is True
    assert result.admission_decision is not None
    assert (
        result.admission_decision.admission_outcome
        == "admitted_for_future_transport_layer"
    )


def test_integration_sabotage_label_refused_halts_campaign(tmp_path):
    """Classification: integration/sabotage
    An explicitly refused descriptor is passed through the real admission
    service and produces campaign halt.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    att = _attestation()
    request = _classification_request(
        digest, path="scoped.py", labels=["credential_or_secret"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(),
        fixture_root_dir=root,
    )
    assert result.provider_admission_performed is True
    assert result.admission_decision is not None
    assert result.admission_decision.admission_outcome == (
        "halt_campaign_security_or_confidentiality_boundary"
    )


def test_integration_sabotage_signal_refused_halts_campaign(tmp_path):
    """Classification: integration/sabotage
    A signal-detected refused descriptor is passed through the real admission
    service and produces campaign halt.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": 'API_KEY = "sk-test"\n'})
    manifest = _manifest()
    att = _attestation()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(),
        fixture_root_dir=root,
    )
    assert result.provider_admission_performed is True
    assert result.admission_decision is not None
    assert result.admission_decision.admission_outcome == (
        "halt_campaign_security_or_confidentiality_boundary"
    )


def test_integration_sabotage_scope_refusal_skips_provider_admission(tmp_path):
    """Classification: integration/sabotage
    Ordinary scope refusal does not flow through provider admission.
    """
    root, digest = _setup_fixture_root(tmp_path, {"outside.py": "x=1"})
    manifest = _manifest()
    att = _attestation()
    request = _classification_request(
        digest, path="outside.py", labels=["none_declared"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(),
        fixture_root_dir=root,
    )
    assert result.provider_admission_performed is False
    assert result.classification_only_refusal is True
    assert result.admission_decision is None


# ---- Content-light / no-transmission tests ---------------------------


def test_contract_adversarial_no_source_or_absolute_path_in_decision(tmp_path):
    """Classification: contract/adversarial
    Classification decision contains no absolute fixture-root path or
    absolute lane-root path.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    decision = classify_fixture_context_item(request, manifest, "m1", root)
    raw = decision.model_dump_json()
    abs_root = str(root.resolve())
    assert abs_root not in raw
    assert "SECRET" not in raw
    assert "PRIVATE KEY" not in raw


def test_contract_integration_orchestration_all_false_markers(tmp_path):
    """Classification: contract/integration
    Successful orchestration explicitly records all false markers.
    """
    root, digest = _setup_fixture_root(tmp_path, {"scoped.py": "x=1"})
    manifest = _manifest()
    att = _attestation()
    request = _classification_request(
        digest, path="scoped.py", labels=["none_declared"]
    )
    result = evaluate_classified_fixture_context_for_provider_admission(
        classification_request=request,
        manifest=manifest,
        mission_id="m1",
        policy_attestation=att,
        request_template=_template(),
        fixture_root_dir=root,
    )
    decision = result.classification_decision
    assert decision.source_body_in_decision is False
    assert decision.secret_body_in_decision is False
    assert decision.provider_request_performed is False
    assert decision.external_transmission_performed is False
    assert decision.human_transport_activation_still_required is True


# ---- No-transport substrate test -------------------------------------


def test_substrate_sabotage_classifier_imports_no_network(tmp_path):
    """Classification: substrate/sabotage
    Structural scan of new classifier source confirms it imports no HTTP
    client, socket, provider SDK, browser, subprocess-based upload path,
    MCP transport, or telemetry export path.
    """
    import rig_relay.campaign_contract._context_classifier as mod

    source = mod.__file__
    assert source is not None
    content = Path(source).read_text()
    forbidden = [
        "aiohttp",
        "urllib",
        "socket",
        "openai",
        "anthropic",
        "google.generativeai",
        "subprocess",
        "browser",
        "mcp",
        "telemetry",
        "upload",
        "httpx",
    ]
    for term in forbidden:
        assert term not in content.lower(), f"Forbidden import: {term}"


# ---- Real artifact schema identity test -----------------------------


def test_integration_real_artifact_classifier_schema_identity():
    """Classification: integration/real-artifact
    Deterministically emits classifier schema identity/hash.
    """
    from rig_relay.campaign_contract._context_classifier_models import (
        compute_context_classifier_schema_identity,
    )

    identity = compute_context_classifier_schema_identity()
    assert len(identity) == 64
    assert identity == compute_context_classifier_schema_identity()
