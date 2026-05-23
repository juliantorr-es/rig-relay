from __future__ import annotations

import hashlib
from pathlib import Path

from rig_relay.context_egress.boundary import (
    refuse_provider_context_input,
    validate_confidential_output_sink,
)
from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    CacheReadinessStatus,
    ContextClassification,
    ContextEfficiencyEvidence,
    ContextSectionKind,
    EgressCandidate,
    EgressCandidateSection,
    EgressCrosswalk,
    EgressReceipt,
    ProviderMode,
    ProviderPolicyAttestation,
    RetentionMode,
)
from rig_relay.context_egress.projection import project_python_source
from rig_relay.context_egress.residual_scanner import scan_for_residual_risks
from rig_relay.core.paths._confidential_artifacts import (
    resolve_confidential_artifact_root,
)


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _validate_request_and_policy(
    manifest: BoundedMissionManifest,
    attestation: ProviderPolicyAttestation,
    receipt: EgressReceipt,
) -> bool:
    # 1. ZDR constraint
    if (
        manifest.provider_mode
        == ProviderMode.HOSTED_PROVIDER_ZDR_CONFIDENTIAL_MINIMIZED
    ):
        if attestation.retention_mode != RetentionMode.ZERO_DATA_RETENTION:
            receipt.refusal_reason_codes.append("zdr_mode_requires_zdr_attestation")
            receipt.output_status = "refused"
            return False
    return True


def _classify_and_prepare_blocks(
    input_path: Path, manifest: BoundedMissionManifest, receipt: EgressReceipt
) -> str | None:
    # 2. Boundary Refusals
    refused, reason, classification = refuse_provider_context_input(
        input_path, "candidate_generation", manifest
    )
    if refused:
        receipt.refusal_reason_codes.append(reason)
        receipt.excluded_material_counts[classification] = (
            receipt.excluded_material_counts.get(classification, 0) + 1
        )
        receipt.output_status = "refused"
        return None

    # Only support python for projection
    if input_path.suffix != ".py":
        receipt.refusal_reason_codes.append("unsupported_content_type")
        receipt.output_status = "refused"
        return None

    try:
        source_code = input_path.read_text(encoding="utf-8")
    except Exception:
        receipt.refusal_reason_codes.append("read_error")
        receipt.output_status = "refused"
        return None

    receipt.source_scope_hash = _hash_str(source_code)
    return source_code


def _build_base_efficiency_evidence(
    source_code: str, minimized: str
) -> ContextEfficiencyEvidence:
    in_chars = len(source_code)
    out_chars = len(minimized)
    in_bytes = len(source_code.encode("utf-8"))
    out_bytes = len(minimized.encode("utf-8"))
    return ContextEfficiencyEvidence(
        projection_input_character_count=in_chars,
        projection_output_character_count=out_chars,
        projection_input_utf8_byte_count=in_bytes,
        projection_output_utf8_byte_count=out_bytes,
        projection_character_reduction_ratio=(in_chars - out_chars) / max(1, in_chars),
        projection_utf8_byte_reduction_ratio=(in_bytes - out_bytes) / max(1, in_bytes),
    )


def _project_approved_blocks(
    source_code: str, receipt: EgressReceipt
) -> tuple[str | None, dict[str, str] | None, ContextEfficiencyEvidence]:
    minimized, crosswalk_map, projection_refused = project_python_source(source_code)
    evidence = _build_base_efficiency_evidence(source_code, minimized)

    if projection_refused:
        receipt.refusal_reason_codes.append(
            "projection_refused_due_to_sensitive_semantics"
        )
        receipt.output_status = "refused"
        evidence.cache_readiness_status = CacheReadinessStatus.REFUSED
        evidence.refused_block_count = 1
        return None, None, evidence

    has_residual, findings = scan_for_residual_risks(minimized, crosswalk_map)
    if has_residual:
        receipt.refusal_reason_codes.append("residual_risk_detected")
        receipt.refusal_reason_codes.extend(findings)
        receipt.residual_scan_status = "failed"
        receipt.output_status = "refused"
        evidence.cache_readiness_status = CacheReadinessStatus.REFUSED
        evidence.refused_block_count = 1
        return None, None, evidence

    receipt.residual_scan_status = "passed"
    return minimized, crosswalk_map, evidence


def _assemble_candidate_sections(
    manifest: BoundedMissionManifest,
    attestation: ProviderPolicyAttestation,
    minimized: str,
    evidence: ContextEfficiencyEvidence,
) -> tuple[EgressCandidate, str]:
    prefix_content = (
        f"ProviderMode: {manifest.provider_mode}\n"
        f"PolicyVersion: {attestation.schema_version}\n"
    )

    prefix_section = EgressCandidateSection(
        section_kind=ContextSectionKind.STABLE_APPROVED_PREFIX,
        opaque_identity=_hash_str(prefix_content)[:16],
        minimized_content=prefix_content,
        classification=ContextClassification.PUBLIC_VERIFIED_CONTEXT,
    )

    suffix_section = EgressCandidateSection(
        section_kind=ContextSectionKind.DYNAMIC_MINIMIZED_SUFFIX,
        opaque_identity=_hash_str(minimized)[:16],
        minimized_content=minimized,
        classification=ContextClassification.CONFIDENTIAL_MINIMIZED_PROVIDER_CONTEXT,
    )

    candidate = EgressCandidate(
        sections=[prefix_section, suffix_section],
        provider_mode=manifest.provider_mode,
        generic_purpose_metadata=manifest.minimum_necessary_purpose_label,
    )

    evidence.stable_prefix_sha256 = _hash_str(prefix_content)
    evidence.dynamic_suffix_sha256 = _hash_str(minimized)
    evidence.stable_prefix_reusable = True
    evidence.approved_block_count = 1
    evidence.cache_readiness_status = CacheReadinessStatus.STABLE_PREFIX_LAYOUT_PROVEN

    return candidate, prefix_content


def compile_egress_candidate(
    input_path: Path | str,
    manifest: BoundedMissionManifest,
    attestation: ProviderPolicyAttestation,
    egress_decision_id: str,
    repo_root: Path | None = None,
) -> tuple[
    EgressCandidate | None,
    EgressCrosswalk | None,
    EgressReceipt,
    ContextEfficiencyEvidence | None,
]:
    input_path = Path(input_path).resolve()

    receipt = EgressReceipt(
        egress_decision_id=egress_decision_id,
        mission_id=manifest.mission_id,
        provider_mode=manifest.provider_mode,
        provider_family=attestation.provider_family,
        endpoint_family_classification=attestation.endpoint_family,
        retention_mode_attested=attestation.retention_mode,
        policy_version=attestation.schema_version,
        source_scope_hash="",
        crosswalk_artifact_hash="",
        residual_scan_status="pending",
        output_status="pending",
    )

    if not _validate_request_and_policy(manifest, attestation, receipt):
        return None, None, receipt, None

    source_code = _classify_and_prepare_blocks(input_path, manifest, receipt)
    if source_code is None:
        return None, None, receipt, None

    minimized, crosswalk_map, evidence = _project_approved_blocks(source_code, receipt)
    if minimized is None or crosswalk_map is None:
        return None, None, receipt, evidence

    candidate, prefix_content = _assemble_candidate_sections(
        manifest, attestation, minimized, evidence
    )

    crosswalk = EgressCrosswalk(original_to_opaque_mapping=crosswalk_map)

    candidate_hash = _hash_str(candidate.model_dump_json())
    crosswalk_hash = _hash_str(crosswalk.model_dump_json())

    crosswalk.egress_candidate_hash = candidate_hash
    receipt.egress_candidate_hash = candidate_hash
    receipt.crosswalk_artifact_hash = crosswalk_hash
    receipt.output_status = "success"
    receipt.classification_counts[
        ContextClassification.CONFIDENTIAL_MINIMIZED_PROVIDER_CONTEXT
    ] = 1

    return candidate, crosswalk, receipt, evidence


def write_local_artifacts(
    candidate: EgressCandidate | None,
    crosswalk: EgressCrosswalk | None,
    receipt: EgressReceipt,
    evidence: ContextEfficiencyEvidence | None,
    egress_decision_id: str,
    repo_root: Path | None = None,
) -> None:
    base_dir = (
        resolve_confidential_artifact_root(repo_root)
        / "context_egress"
        / egress_decision_id
    )
    base_dir.mkdir(parents=True, exist_ok=True)

    valid, err = validate_confidential_output_sink(
        base_dir, egress_decision_id, repo_root
    )
    if not valid:
        raise ValueError(err)

    if candidate:
        (base_dir / "egress_candidate.json").write_text(
            candidate.model_dump_json(indent=2)
        )
    if crosswalk:
        (base_dir / "local_crosswalk.json").write_text(
            crosswalk.model_dump_json(indent=2)
        )
    if evidence:
        (base_dir / "efficiency_evidence.json").write_text(
            evidence.model_dump_json(indent=2)
        )

    (base_dir / "egress_receipt.json").write_text(receipt.model_dump_json(indent=2))
