"""Profile evaluation harness.

Tests each profile against a validation suite: context assembly,
tool authority preservation, deterministic resolution, capability
refusal, receipt reconstructability, evidence-based selection,
governance integration, persistence integrity, and downstream contracts.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from rig_relay.profiles._capability_evidence import (
    BUILTIN_CAPABILITY_EVIDENCE,
    CapabilityEvidenceItem,
    validate_profile_requirements_against_evidence,
)
from rig_relay.profiles._context_envelope import build_context_envelope
from rig_relay.profiles._evidence_ledger import (
    Y3ProfileEvent,
    Y3ProfileEventKind,
    load_y3_events,
    persist_y3_event,
    verify_y3_ledger_integrity,
)
from rig_relay.profiles._governance_adapter import admit_profile_selection
from rig_relay.profiles._resolver import resolve_profile
from rig_relay.profiles._session_receipt import build_session_resolution_receipt
from rig_relay.profiles._tool_dialect import (
    adapt_tool_description,
    assert_tool_dialect_authority_preserved,
)
from rig_relay.profiles.models import (
    HarnessCompatibilityProfile,
    ProfileEvaluationInput,
    ProfileEvaluationResult,
    ProfileResolutionInput,
    ProfileResolutionResult,
    TaskRole,
)


def evaluate_profile(
    profile: HarnessCompatibilityProfile, input: ProfileEvaluationInput
) -> ProfileEvaluationResult:
    warnings: list[str] = []

    ctx_ok = _eval_context_assembly(profile, input, warnings)
    tool_ok = _eval_tool_authority(profile, input, warnings)
    det_ok = _eval_deterministic(profile, input, warnings)
    cap_ok = _eval_capability_refusal(profile, input, warnings)
    rcpt_ok = _eval_receipt(profile, input, warnings)

    evidence_based = _eval_evidence_based_selection(profile, input, warnings)
    authority_ok = _eval_capability_authority(profile, input, warnings)
    gov_ok = _eval_governance_integration(profile, input, warnings)
    persist_ok = _eval_evidence_persistence_check(profile, input, warnings)
    ledger_ok = _eval_ledger_integrity_check(profile, input, warnings)
    contracts_ok = _eval_downstream_contracts_check(warnings)

    return ProfileEvaluationResult(
        evaluation_id=str(uuid4()),
        profile_id=input.profile_id,
        task_role=input.task_role,
        provider=input.provider,
        model_id=input.model_id,
        context_assembly_correct=ctx_ok,
        tool_authority_preserved=tool_ok,
        deterministic_resolution=det_ok,
        unsupported_capability_refused=cap_ok,
        receipt_reconstructable=rcpt_ok,
        evidence_based_selection=evidence_based,
        capability_authority_valid=authority_ok,
        governance_integration_tested=gov_ok,
        evidence_persistence_tested=persist_ok,
        ledger_integrity_tested=ledger_ok,
        downstream_contracts_valid=contracts_ok,
        warnings=warnings,
    )


def evaluate_all_profiles(
    profiles: Sequence[HarnessCompatibilityProfile] | None = None,
    evidence_sources: tuple | None = None,
) -> list[ProfileEvaluationResult]:
    if profiles is None:
        from rig_relay.profiles._profile_registry import BUILTIN_PROFILES

        profiles = BUILTIN_PROFILES

    if evidence_sources is None:
        evidence_sources = BUILTIN_CAPABILITY_EVIDENCE

    results: list[ProfileEvaluationResult] = []
    for prof in profiles:
        for role in prof.supported_roles:
            for provider in prof.provider_families:
                test_input = ProfileEvaluationInput(
                    profile_id=prof.profile_id,
                    task_role=role,
                    provider=provider,
                    model_id=f"{provider}-test-model-{prof.model_patterns[0].replace('.*', '')}",
                    test_fixture_sha256=None,
                )
                results.append(evaluate_profile(prof, test_input))
    return results


def evaluate_profile_with_evidence(
    profile: HarnessCompatibilityProfile,
    provider: str,
    model_id: str,
    role: TaskRole,
    evidence_sources: tuple,
) -> dict[str, object]:
    satisfied, evidence_map, warnings = validate_profile_requirements_against_evidence(
        profile, provider, model_id, evidence_sources
    )
    return {
        "satisfied": satisfied,
        "evidence_checks": len(evidence_map),
        "warnings_count": len(warnings),
        "has_evidence_map": bool(evidence_map),
    }


def evaluate_capability_evidence_authority(
    evidence: CapabilityEvidenceItem,
) -> dict[str, object]:
    from rig_relay.profiles._capability_evidence import CapabilityEvidenceSourceClass

    valid_source = evidence.source_class in {
        CapabilityEvidenceSourceClass.VERIFIED_LIVE_PROVIDER_RESPONSE,
        CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
        CapabilityEvidenceSourceClass.LOCAL_RUNTIME_PUBLIC_PROJECTION,
        CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION,
        CapabilityEvidenceSourceClass.UNKNOWN,
        CapabilityEvidenceSourceClass.CONFLICTING,
        CapabilityEvidenceSourceClass.UNAVAILABLE_WITHOUT_CREDENTIALS,
    }
    has_digest = bool(evidence.evidence_digest) and evidence.evidence_digest.startswith(
        "sha256:"
    )
    recomputed = evidence.compute_digest()
    digest_matches = evidence.evidence_digest == recomputed

    return {
        "valid": valid_source and has_digest and digest_matches,
        "source_class": evidence.source_class.value,
        "has_digest": has_digest,
        "confidence": evidence.confidence,
    }


def evaluate_governance_integration(
    resolution: ProfileResolutionResult, provider: str, model_id: str
) -> dict[str, object]:
    state, digest = admit_profile_selection(
        resolution, provider, model_id, resolution.task_role.value
    )

    evaluated = state != "not_evaluated"

    return {
        "admission_evaluated": evaluated,
        "admission_state": state,
        "has_digest": digest is not None and digest.startswith("sha256:"),
    }


def evaluate_evidence_persistence(
    event: Y3ProfileEvent, store_root: str | Path | None = None
) -> dict[str, object]:
    if store_root is None:
        td = tempfile.TemporaryDirectory()
        store_root = td.name

    digest = persist_y3_event(event, store_root)
    loaded = load_y3_events(store_root)
    match = any(e.event_id == event.event_id for e in loaded)
    digest_match = any(
        e.event_id == event.event_id and e.event_digest == digest for e in loaded
    )

    return {
        "persisted": bool(digest),
        "loaded_count": len(loaded),
        "event_id_match": match,
        "digest_match": digest_match,
    }


def evaluate_ledger_integrity(
    events: list[Y3ProfileEvent], store_root: str | Path | None = None
) -> dict[str, object]:
    if store_root is None:
        td = tempfile.TemporaryDirectory()
        store_root = td.name

    for event in events:
        persist_y3_event(event, store_root)

    ok, corrupt = verify_y3_ledger_integrity(store_root)

    return {
        "integrity_ok": ok,
        "corrupt_count": len(corrupt),
        "events_persisted": len(events),
    }


def evaluate_downstream_contracts() -> dict[str, object]:
    from rig_relay.profiles._downstream_contracts import (
        ContextCapsuleBindingReceipt,
        ContextCapsuleBindingRequest,
        HarnessProfileStatusProjection,
        ProfileEvaluationObservation,
        ProfileSelectionMetrics,
        RuntimeProfileCapabilityObservation,
        WorkspaceProfileAssignmentReceipt,
        WorkspaceProfileAssignmentRequest,
    )

    models: list[tuple[str, object]] = [
        (
            "HarnessProfileStatusProjection",
            HarnessProfileStatusProjection(
                selected_profile_id="rig.native.governed.v1",
                selected_profile_display_name="Rig Native Governed",
                selected_profile_status="candidate",
                provider="openai",
                model_id="gpt-4o",
                task_role="implementation",
                resolution_outcome="selected",
            ),
        ),
        (
            "WorkspaceProfileAssignmentRequest",
            WorkspaceProfileAssignmentRequest(
                request_id="req-1",
                workspace_id_ref="ws-1",
                agent_role="implementation",
                provider="openai",
                model_id="gpt-4o",
                selected_profile_digest="sha256:abc",
            ),
        ),
        (
            "WorkspaceProfileAssignmentReceipt",
            WorkspaceProfileAssignmentReceipt(
                receipt_id="rec-1",
                request_id="req-1",
                workspace_id_ref="ws-1",
                assignment_accepted=True,
                assignment_digest="sha256:abc",
            ),
        ),
        (
            "ContextCapsuleBindingRequest",
            ContextCapsuleBindingRequest(
                request_id="req-1", context_capsule_digest="sha256:abc"
            ),
        ),
        (
            "ContextCapsuleBindingReceipt",
            ContextCapsuleBindingReceipt(
                receipt_id="rec-1",
                request_id="req-1",
                capsule_bound=True,
                binding_digest="sha256:abc",
            ),
        ),
        (
            "RuntimeProfileCapabilityObservation",
            RuntimeProfileCapabilityObservation(
                observation_id="obs-1",
                runtime_provider="openai",
                runtime_model="gpt-4o",
                selected_profile_id="rig.native.governed.v1",
                observed_outcome="success",
            ),
        ),
        (
            "ProfileEvaluationObservation",
            ProfileEvaluationObservation(
                observation_id="obs-1",
                profile_id="rig.native.governed.v1",
                provider="openai",
                model_id="gpt-4o",
                task_role="implementation",
                evaluation_checks_passed=5,
            ),
        ),
        ("ProfileSelectionMetrics", ProfileSelectionMetrics(total_selections=1)),
    ]

    valid_count = 0
    for _name, model in models:
        try:
            js = model.model_dump_json()
            json.loads(js)
            valid_count += 1
        except Exception:
            pass

    return {
        "models_checked": len(models),
        "models_valid": valid_count,
        "all_valid": valid_count == len(models),
    }


def _eval_context_assembly(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        envelope = build_context_envelope(
            profile=profile,
            role=input.task_role,
            workspace_root=Path.cwd(),
            session_id=f"eval-{uuid4().hex[:8]}",
        )
        if not envelope.rendered_prompt:
            warnings.append("rendered_prompt is empty")
            return False
        if not envelope.receipt_sha256:
            warnings.append("receipt_sha256 is empty")
            return False
        if envelope.section_count <= 0:
            warnings.append("section_count is zero")
            return False
        return True
    except Exception as exc:
        warnings.append(f"context_assembly raised: {exc}")
        return False


def _eval_tool_authority(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    original = "Writes content to a file at the specified path."
    adapted = adapt_tool_description(
        "write_file", original, profile.tool_dialect_strategy, profile.profile_id
    )
    if original not in adapted:
        warnings.append("Original tool description not preserved in adaptation")
        return False
    if not assert_tool_dialect_authority_preserved(adapted, original, profile):
        warnings.append("Tool authority assertion failed")
        return False
    return True


def _eval_deterministic(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        inp = ProfileResolutionInput(
            provider=input.provider,
            model_id=input.model_id,
            task_role=input.task_role,
            prefer_profile_id=input.profile_id,
            model_capabilities={"supports_tools": True},
        )
        r1 = resolve_profile(inp, [profile])
        r2 = resolve_profile(inp, [profile])
        if r1.selected_profile.profile_id != r2.selected_profile.profile_id:
            warnings.append("Non-deterministic resolution")
            return False
        return True
    except Exception as exc:
        warnings.append(f"deterministic_resolution raised: {exc}")
        return False


def _eval_capability_refusal(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        inp = ProfileResolutionInput(
            provider=input.provider,
            model_id=input.model_id,
            task_role=input.task_role,
            prefer_profile_id=input.profile_id,
            model_capabilities={"supports_tools": False, "context_window": 5000},
        )
        resolve_profile(inp, [profile])
        warnings.append("Should have rejected model with incompatible capabilities")
        return False
    except Exception:
        return True


def _eval_receipt(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        inp = ProfileResolutionInput(
            provider=input.provider,
            model_id=input.model_id,
            task_role=input.task_role,
            prefer_profile_id=input.profile_id,
            model_capabilities={"supports_tools": True},
        )
        resolution = resolve_profile(inp, [profile])
        receipt = build_session_resolution_receipt(
            resolution, f"eval-{uuid4().hex[:8]}"
        )
        if not receipt.get("receipt_digest") or not receipt.get("receipt_id"):
            warnings.append("Receipt missing required fields")
            return False
        if "sha256:" not in str(receipt.get("receipt_digest", "")):
            warnings.append("Receipt digest malformed")
            return False
        return True
    except Exception as exc:
        warnings.append(f"receipt_reconstructable raised: {exc}")
        return False


def _eval_evidence_based_selection(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        result = evaluate_profile_with_evidence(
            profile,
            input.provider,
            input.model_id,
            input.task_role,
            BUILTIN_CAPABILITY_EVIDENCE,
        )
        return bool(result.get("satisfied", False))
    except Exception as exc:
        warnings.append(f"evidence_based_selection raised: {exc}")
        return False


def _eval_capability_authority(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        all_valid = True
        for evidence in BUILTIN_CAPABILITY_EVIDENCE:
            authority = evaluate_capability_evidence_authority(evidence)
            if not authority.get("valid", False):
                all_valid = False
        return all_valid
    except Exception as exc:
        warnings.append(f"capability_authority raised: {exc}")
        return False


def _eval_governance_integration(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        resolution_input = ProfileResolutionInput(
            provider=input.provider, model_id=input.model_id, task_role=input.task_role
        )
        result = resolve_profile(resolution_input, [profile])
        gov = evaluate_governance_integration(result, input.provider, input.model_id)
        return bool(gov.get("admission_evaluated", False))
    except Exception as exc:
        warnings.append(f"governance_integration raised: {exc}")
        return False


def _eval_evidence_persistence_check(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        event = Y3ProfileEvent(
            event_id=f"eval-persist-{uuid4().hex[:8]}",
            event_kind=Y3ProfileEventKind.PROFILE_SELECTED,
            provider=input.provider,
            model_id=input.model_id,
            profile_id=input.profile_id,
            task_role=input.task_role.value,
            resolution_outcome="selected",
        )
        result = evaluate_evidence_persistence(event)
        return bool(result.get("persisted", False))
    except Exception as exc:
        warnings.append(f"evidence_persistence raised: {exc}")
        return False


def _eval_ledger_integrity_check(
    profile: HarnessCompatibilityProfile,
    input: ProfileEvaluationInput,
    warnings: list[str],
) -> bool:
    try:
        events = [
            Y3ProfileEvent(
                event_id=f"eval-ledger-{uuid4().hex[:8]}",
                event_kind=Y3ProfileEventKind.PROFILE_SELECTED,
                provider=input.provider,
                model_id=input.model_id,
                profile_id=input.profile_id,
            )
        ]
        result = evaluate_ledger_integrity(events)
        return bool(result.get("integrity_ok", False))
    except Exception as exc:
        warnings.append(f"ledger_integrity raised: {exc}")
        return False


def _eval_downstream_contracts_check(warnings: list[str]) -> bool:
    try:
        result = evaluate_downstream_contracts()
        return bool(result.get("all_valid", False))
    except Exception as exc:
        warnings.append(f"downstream_contracts raised: {exc}")
        return False
