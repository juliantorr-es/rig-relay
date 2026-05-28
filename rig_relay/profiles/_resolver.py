"""Profile resolution logic.

Matches a provider/model/role combination to the best-fitting
harness compatibility profile from the built-in registry.

Now includes capability evidence layer — profiles are admitted only when
required capabilities are supported by admissible evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import re
from typing import cast
from uuid import uuid4

from rig_relay.profiles._capability_evidence import (
    BUILTIN_CAPABILITY_EVIDENCE,
    CapabilityEvidenceItem,
    CapabilityEvidenceSourceClass,
    CapabilityPosture,
    validate_profile_requirements_against_evidence,
)
from rig_relay.profiles._evidence_ledger import (
    Y3ProfileEvent,
    Y3ProfileEventKind,
    persist_y3_event,
)
from rig_relay.profiles._governance_adapter import admit_profile_selection
from rig_relay.profiles.models import (
    GovernanceAdmissionState,
    HarnessCompatibilityProfile,
    ProfileResolutionError,
    ProfileResolutionInput,
    ProfileResolutionResult,
    ProfileStatus,
    ResolutionOutcome,
)

_CONFIDENCE_HIGH_THRESHOLD = 5
_CONFIDENCE_MEDIUM_THRESHOLD = 3


def _determine_confidence(score: int) -> str:
    if score >= _CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= _CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _load_evidence_sources(
    input: ProfileResolutionInput,
) -> tuple[CapabilityEvidenceItem, ...]:
    if input.capability_evidence_sources is None:
        return BUILTIN_CAPABILITY_EVIDENCE
    filtered: list[CapabilityEvidenceItem] = []
    for eid in input.capability_evidence_sources:
        for item in BUILTIN_CAPABILITY_EVIDENCE:
            if item.evidence_id == eid:
                filtered.append(item)
                break
    if not filtered:
        return BUILTIN_CAPABILITY_EVIDENCE
    return tuple(filtered)


def _resolve_evidence_map(
    profile: HarnessCompatibilityProfile,
    provider: str,
    model_id: str,
    sources: tuple[CapabilityEvidenceItem, ...],
) -> tuple[ResolutionOutcome | None, dict[str, object], list[str]]:
    satisfied, evidence_items, warnings = (
        validate_profile_requirements_against_evidence(
            profile, provider, model_id, sources
        )
    )

    map_for_result: dict[str, object] = {}
    for cap_name, evidence in evidence_items.items():
        if evidence is None:
            map_for_result[cap_name] = {
                "posture": CapabilityPosture.UNKNOWN.value,
                "source_class": CapabilityEvidenceSourceClass.UNKNOWN.value,
            }
        else:
            map_for_result[cap_name] = {
                "posture": evidence.posture.value,
                "source_class": evidence.source_class.value,
                "evidence_digest": evidence.evidence_digest,
            }

    outcome: ResolutionOutcome | None = None

    if not satisfied:
        has_unsupported = any(
            w.startswith("Required capability")
            and ("unsupported" in w or "unavailable" in w)
            for w in warnings
        )
        has_conflicting = any("conflicting" in w for w in warnings)
        has_missing = any("has no evidence" in w for w in warnings)

        if has_conflicting:
            outcome = ResolutionOutcome.REFUSED_CONFLICTING_CAPABILITY_EVIDENCE
        elif has_unsupported:
            outcome = ResolutionOutcome.REFUSED_UNSUPPORTED_CAPABILITY
        elif has_missing:
            outcome = ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE
        else:
            outcome = ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE
        return outcome, map_for_result, warnings

    has_user_only = any(
        e is not None
        and e.source_class == CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION
        for e in evidence_items.values()
    )
    all_user_only = has_user_only and all(
        e is None
        or e.source_class == CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION
        for e in evidence_items.values()
        if e is not None
    )

    if all_user_only:
        outcome = ResolutionOutcome.SELECTED_RESTRICTED
    elif profile.evaluation_status == ProfileStatus.EXPERIMENTAL:
        outcome = ResolutionOutcome.SELECTED_EXPERIMENTAL
    else:
        outcome = ResolutionOutcome.SELECTED

    return outcome, map_for_result, warnings


def _compute_evidence_map_digest(evidence_map: dict[str, object]) -> str:
    canonical = json.dumps(evidence_map, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _classify_and_score_profiles(
    input: ProfileResolutionInput,
    profiles: Sequence[HarnessCompatibilityProfile],
    alternatives_considered: list[str],
    alternatives_rejected: dict[str, str],
) -> list[tuple[int, HarnessCompatibilityProfile]]:
    scored: list[tuple[int, HarnessCompatibilityProfile]] = []

    for prof in profiles:
        if input.provider not in prof.provider_families:
            alternatives_rejected[prof.profile_id] = (
                f"Provider {input.provider} not in {prof.provider_families}"
            )
            continue

        if not _model_matches(prof.model_patterns, input.model_id):
            alternatives_rejected[prof.profile_id] = (
                f"Model {input.model_id} does not match patterns {prof.model_patterns}"
            )
            continue

        if input.task_role not in prof.supported_roles:
            alternatives_rejected[prof.profile_id] = (
                f"Role {input.task_role.value} not in supported_roles"
            )
            continue

        cap_check = _check_capabilities(prof, input)
        if cap_check is None:
            alternatives_rejected[prof.profile_id] = "Required capability not available"
            continue

        warnings_from_cap = cap_check
        score = _score_profile(prof, input)

        scored.append((score, prof))
        alternatives_considered.append(prof.profile_id)

        if warnings_from_cap:
            reason = "; ".join(warnings_from_cap)
            if prof.profile_id in alternatives_rejected:
                alternatives_rejected[prof.profile_id] += (
                    f"\nCapability warnings: {reason}"
                )
            else:
                alternatives_rejected[prof.profile_id] = (
                    f"Capability warnings: {reason}"
                )

    return scored


def resolve_profile(
    input: ProfileResolutionInput,
    profiles: Sequence[HarnessCompatibilityProfile] | None = None,
) -> ProfileResolutionResult:
    if profiles is None:
        from rig_relay.profiles._profile_registry import BUILTIN_PROFILES

        profiles = BUILTIN_PROFILES

    evidence_sources = _load_evidence_sources(input)
    alternatives_considered: list[str] = []
    alternatives_rejected: dict[str, str] = {}
    governance_state: str = GovernanceAdmissionState.NOT_EVALUATED.value

    if input.require_governance_admission:
        governance_state = GovernanceAdmissionState.REQUIRES_REVIEW.value

    if input.prefer_profile_id is not None:
        for p in profiles:
            if p.profile_id == input.prefer_profile_id:
                if not _capabilities_satisfied(p, input):
                    alternatives_rejected[p.profile_id] = (
                        "User override requested but capabilities not satisfied"
                    )
                    msg = (
                        f"No profile matches prefer_profile_id "
                        f"'{input.prefer_profile_id}'"
                    )
                    raise ProfileResolutionError(
                        msg,
                        provider=input.provider,
                        model_id=input.model_id,
                        reasons=list(alternatives_rejected.values()),
                    )

                evidence_outcome, evidence_map, evidence_warnings = (
                    _resolve_evidence_map(
                        p, input.provider, input.model_id, evidence_sources
                    )
                )
                evidence_digest = _compute_evidence_map_digest(evidence_map)

                if evidence_outcome in {
                    ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE,
                    ResolutionOutcome.REFUSED_CONFLICTING_CAPABILITY_EVIDENCE,
                    ResolutionOutcome.REFUSED_UNSUPPORTED_CAPABILITY,
                }:
                    outcome_val = cast(ResolutionOutcome, evidence_outcome)
                    alternatives_rejected[p.profile_id] = (
                        f"User override: evidence check failed — {outcome_val.value}"
                    )
                    msg = (
                        f"No profile matches prefer_profile_id "
                        f"'{input.prefer_profile_id}'"
                    )
                    raise ProfileResolutionError(
                        msg,
                        provider=input.provider,
                        model_id=input.model_id,
                        reasons=list(alternatives_rejected.values()),
                    )

                result = ProfileResolutionResult(
                    resolution_id=str(uuid4()),
                    provider=input.provider,
                    model_id=input.model_id,
                    task_role=input.task_role,
                    selected_profile=p,
                    selected_reason=(
                        f"User override: prefer_profile_id={input.prefer_profile_id}"
                    ),
                    confidence="high",
                    alternatives_considered=[],
                    is_user_override=True,
                    override_source_profile_id=input.prefer_profile_id,
                    outcome=(
                        evidence_outcome.value if evidence_outcome else "selected"
                    ),
                    capability_evidence_map=evidence_map,
                    capability_evidence_digest=evidence_digest,
                    governance_admission_state=governance_state,
                    warnings=evidence_warnings,
                )

                admission_state, admission_digest = admit_profile_selection(
                    result,
                    input.provider,
                    input.model_id,
                    input.task_role.value,
                    session_id=input.session_id,
                )
                result.governance_admission_state = admission_state
                result.governance_admission_digest = admission_digest or ""

                outcome_val = result.outcome
                event_kind = {
                    "selected": Y3ProfileEventKind.PROFILE_SELECTED,
                    "selected_experimental": Y3ProfileEventKind.PROFILE_SELECTED,
                    "selected_restricted": Y3ProfileEventKind.PROFILE_SELECTED,
                    "refused_missing_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
                    "refused_conflicting_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
                    "refused_unsupported_capability": Y3ProfileEventKind.PROFILE_REFUSED,
                    "fallback_rig_native": Y3ProfileEventKind.PROFILE_SELECTED,
                    "unavailable_provider_capability_resolution": Y3ProfileEventKind.PROFILE_REFUSED,
                }.get(outcome_val, Y3ProfileEventKind.PROFILE_RESOLUTION_ATTEMPTED)

                event = Y3ProfileEvent(
                    event_id=str(uuid4()),
                    event_kind=event_kind,
                    session_id=input.session_id,
                    provider=input.provider,
                    model_id=input.model_id,
                    profile_id=result.selected_profile.profile_id,
                    profile_digest=result.selected_profile.profile_digest,
                    task_role=input.task_role.value,
                    resolution_outcome=outcome_val,
                    capability_evidence_digest=result.capability_evidence_digest,
                    context_envelope_digest="",
                    governance_admission_digest=result.governance_admission_digest,
                    warnings=list(result.warnings),
                )
                persist_y3_event(event)

                return result

        msg = f"No profile matches prefer_profile_id '{input.prefer_profile_id}'"
        raise ProfileResolutionError(
            msg,
            provider=input.provider,
            model_id=input.model_id,
            reasons=list(alternatives_rejected.values()),
        )

    scored = _classify_and_score_profiles(
        input, profiles, alternatives_considered, alternatives_rejected
    )

    if not scored:
        rig_native_result = _try_rig_native_fallback(
            input, profiles, alternatives_rejected, evidence_sources, governance_state
        )
        if rig_native_result is not None:
            return rig_native_result

        msg = (
            f"No profile found for provider={input.provider}, "
            f"model={input.model_id}, role={input.task_role.value}"
        )
        raise ProfileResolutionError(
            msg,
            provider=input.provider,
            model_id=input.model_id,
            reasons=list(alternatives_rejected.values()),
        )

    scored.sort(key=lambda item: item[0], reverse=True)

    for _, candidate in scored:
        evidence_outcome, evidence_map, evidence_warnings = _resolve_evidence_map(
            candidate, input.provider, input.model_id, evidence_sources
        )

        if evidence_outcome in {
            ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE,
            ResolutionOutcome.REFUSED_CONFLICTING_CAPABILITY_EVIDENCE,
            ResolutionOutcome.REFUSED_UNSUPPORTED_CAPABILITY,
        }:
            outcome_val = cast(ResolutionOutcome, evidence_outcome)
            alternatives_rejected[candidate.profile_id] = (
                f"Evidence check failed: {outcome_val.value}"
            )
            continue

        evidence_digest = _compute_evidence_map_digest(evidence_map)
        best_score, best_profile = scored[0]
        confidence = _determine_confidence(best_score)

        all_rejected: dict[str, str] = {}
        for pid in alternatives_considered:
            if pid != best_profile.profile_id and pid in alternatives_rejected:
                all_rejected[pid] = alternatives_rejected[pid]
        for pid, reason in alternatives_rejected.items():
            if pid not in alternatives_considered and pid not in all_rejected:
                all_rejected[pid] = reason

        all_warnings: list[str] = []
        cap_warnings = _check_capabilities(best_profile, input)
        if cap_warnings:
            all_warnings.extend(cap_warnings)
        all_warnings.extend(evidence_warnings)

        if (
            evidence_outcome
            in {
                ResolutionOutcome.SELECTED_EXPERIMENTAL,
                ResolutionOutcome.SELECTED_RESTRICTED,
            }
            and not all_warnings
        ):
            outcome_val = cast(ResolutionOutcome, evidence_outcome)
            all_warnings.append(
                f"Selected with restricted evidence: {outcome_val.value}"
            )

        result = ProfileResolutionResult(
            resolution_id=str(uuid4()),
            provider=input.provider,
            model_id=input.model_id,
            task_role=input.task_role,
            selected_profile=best_profile,
            selected_reason=(
                f"Best match: score={best_score}, provider={input.provider}, "
                f"model={input.model_id}, role={input.task_role.value}"
            ),
            confidence=confidence,
            alternatives_considered=alternatives_considered,
            alternatives_rejected_reasons=all_rejected,
            warnings=all_warnings,
            outcome=evidence_outcome.value if evidence_outcome else "selected",
            capability_evidence_map=evidence_map,
            capability_evidence_digest=evidence_digest,
            governance_admission_state=governance_state,
        )

        admission_state, admission_digest = admit_profile_selection(
            result,
            input.provider,
            input.model_id,
            input.task_role.value,
            session_id=input.session_id,
        )
        result.governance_admission_state = admission_state
        result.governance_admission_digest = admission_digest or ""

        outcome_val = result.outcome
        event_kind = {
            "selected": Y3ProfileEventKind.PROFILE_SELECTED,
            "selected_experimental": Y3ProfileEventKind.PROFILE_SELECTED,
            "selected_restricted": Y3ProfileEventKind.PROFILE_SELECTED,
            "refused_missing_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
            "refused_conflicting_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
            "refused_unsupported_capability": Y3ProfileEventKind.PROFILE_REFUSED,
            "fallback_rig_native": Y3ProfileEventKind.PROFILE_SELECTED,
            "unavailable_provider_capability_resolution": Y3ProfileEventKind.PROFILE_REFUSED,
        }.get(outcome_val, Y3ProfileEventKind.PROFILE_RESOLUTION_ATTEMPTED)

        event = Y3ProfileEvent(
            event_id=str(uuid4()),
            event_kind=event_kind,
            session_id=input.session_id,
            provider=input.provider,
            model_id=input.model_id,
            profile_id=result.selected_profile.profile_id,
            profile_digest=result.selected_profile.profile_digest,
            task_role=input.task_role.value,
            resolution_outcome=outcome_val,
            capability_evidence_digest=result.capability_evidence_digest,
            context_envelope_digest="",
            governance_admission_digest=result.governance_admission_digest,
            warnings=list(result.warnings),
        )
        persist_y3_event(event)

        return result

    rig_native_result = _try_rig_native_fallback(
        input, profiles, alternatives_rejected, evidence_sources, governance_state
    )
    if rig_native_result is not None:
        return rig_native_result

    msg = (
        f"No profile found for provider={input.provider}, "
        f"model={input.model_id}, role={input.task_role.value}"
    )
    raise ProfileResolutionError(
        msg,
        provider=input.provider,
        model_id=input.model_id,
        reasons=list(alternatives_rejected.values()),
    )


def _try_rig_native_fallback(
    input: ProfileResolutionInput,
    profiles: Sequence[HarnessCompatibilityProfile],
    alternatives_rejected: dict[str, str],
    evidence_sources: tuple[CapabilityEvidenceItem, ...],
    governance_state: str,
) -> ProfileResolutionResult | None:
    for p in profiles:
        if p.profile_id != "rig.native.governed.v1":
            continue
        if input.provider not in p.provider_families:
            alternatives_rejected[p.profile_id] = (
                "rig.native fallback: provider not supported"
            )
            return None

        evidence_outcome, evidence_map, evidence_warnings = _resolve_evidence_map(
            p, input.provider, input.model_id, evidence_sources
        )
        evidence_digest = _compute_evidence_map_digest(evidence_map)

        if evidence_outcome in {
            ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE,
            ResolutionOutcome.REFUSED_UNSUPPORTED_CAPABILITY,
        }:
            outcome_val = cast(ResolutionOutcome, evidence_outcome)
            alternatives_rejected[p.profile_id] = "rig.native fallback: " + (
                "evidence missing"
                if outcome_val == ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE
                else "capability unsupported"
            )
            return None

        result = ProfileResolutionResult(
            resolution_id=str(uuid4()),
            provider=input.provider,
            model_id=input.model_id,
            task_role=input.task_role,
            selected_profile=p,
            selected_reason=(
                f"Fallback rig.native: no specialized profile passed "
                f"evidence checks for {input.provider}/{input.model_id}"
            ),
            confidence="low",
            alternatives_considered=[],
            alternatives_rejected_reasons=alternatives_rejected,
            warnings=evidence_warnings,
            outcome=ResolutionOutcome.FALLBACK_RIG_NATIVE.value,
            capability_evidence_map=evidence_map,
            capability_evidence_digest=evidence_digest,
            governance_admission_state=governance_state,
        )

        admission_state, admission_digest = admit_profile_selection(
            result,
            input.provider,
            input.model_id,
            input.task_role.value,
            session_id=input.session_id,
        )
        result.governance_admission_state = admission_state
        result.governance_admission_digest = admission_digest or ""

        outcome_val = result.outcome
        event_kind = {
            "selected": Y3ProfileEventKind.PROFILE_SELECTED,
            "selected_experimental": Y3ProfileEventKind.PROFILE_SELECTED,
            "selected_restricted": Y3ProfileEventKind.PROFILE_SELECTED,
            "refused_missing_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
            "refused_conflicting_capability_evidence": Y3ProfileEventKind.PROFILE_REFUSED,
            "refused_unsupported_capability": Y3ProfileEventKind.PROFILE_REFUSED,
            "fallback_rig_native": Y3ProfileEventKind.PROFILE_SELECTED,
            "unavailable_provider_capability_resolution": Y3ProfileEventKind.PROFILE_REFUSED,
        }.get(outcome_val, Y3ProfileEventKind.PROFILE_RESOLUTION_ATTEMPTED)

        event = Y3ProfileEvent(
            event_id=str(uuid4()),
            event_kind=event_kind,
            session_id=input.session_id,
            provider=input.provider,
            model_id=input.model_id,
            profile_id=result.selected_profile.profile_id,
            profile_digest=result.selected_profile.profile_digest,
            task_role=input.task_role.value,
            resolution_outcome=outcome_val,
            capability_evidence_digest=result.capability_evidence_digest,
            context_envelope_digest="",
            governance_admission_digest=result.governance_admission_digest,
            warnings=list(result.warnings),
        )
        persist_y3_event(event)

        return result

    return None


def resolve_profiles_batch(
    inputs: list[ProfileResolutionInput],
    profiles: Sequence[HarnessCompatibilityProfile] | None = None,
) -> list[ProfileResolutionResult]:
    results: list[ProfileResolutionResult] = []
    for inp in inputs:
        results.append(resolve_profile(inp, profiles))
    return results


def _model_matches(patterns: list[str], model_id: str) -> bool:
    for pat in patterns:
        if re.fullmatch(pat, model_id):
            return True
    return False


def _capabilities_satisfied(
    profile: HarnessCompatibilityProfile, input: ProfileResolutionInput
) -> bool:
    return _check_capabilities(profile, input) is not None


def _check_capabilities(
    profile: HarnessCompatibilityProfile, input: ProfileResolutionInput
) -> list[str] | None:
    req = profile.required_capabilities
    caps = input.model_capabilities or {}
    warnings: list[str] = []

    has_requirements = any([
        req.requires_tool_use,
        req.requires_streaming,
        req.requires_structured_output,
        req.requires_thinking,
        req.requires_vision,
        req.requires_embeddings,
    ])

    if not caps:
        return None if has_requirements else warnings

    checks: list[tuple[str, bool, str]] = [
        ("tool_use", req.requires_tool_use, "supports_tools"),
        ("streaming", req.requires_streaming, "supports_streaming"),
        (
            "structured_output",
            req.requires_structured_output,
            "supports_structured_output",
        ),
        ("thinking", req.requires_thinking, "supports_thinking"),
        ("vision", req.requires_vision, "supports_vision"),
        ("embeddings", req.requires_embeddings, "supports_embeddings"),
    ]

    rejection = False
    for check_key, required, field in checks:
        if not required:
            continue
        if field not in caps:
            warnings.append(
                f"Required capability {check_key} unknown for model "
                f"{input.model_id} (field '{field}' not in capabilities)"
            )
            continue
        if caps[field] is False or caps[field] is None:
            rejection = True

    if not rejection:
        context_win = caps.get("context_window")
        if context_win is not None and isinstance(context_win, (int, float)):
            if float(context_win) < req.min_context_window:
                rejection = True

        output_tok = caps.get("max_output_tokens")
        if output_tok is not None and isinstance(output_tok, (int, float)):
            if float(output_tok) < req.min_output_tokens:
                rejection = True

        if req.max_input_price_per_million > 0:
            price = caps.get("input_price_per_million")
            if price is not None and isinstance(price, (int, float)):
                if float(price) > req.max_input_price_per_million:
                    rejection = True

    if rejection:
        return None
    return warnings


def _score_profile(
    profile: HarnessCompatibilityProfile, input: ProfileResolutionInput
) -> int:
    score = 0

    for pat in profile.model_patterns:
        if re.fullmatch(pat, input.model_id):
            if pat == ".*":
                pass
            else:
                score += 3
            break

    if input.task_role in profile.supported_roles:
        score += 1

    match profile.evaluation_status:
        case ProfileStatus.VERIFIED:
            score += 3
        case ProfileStatus.CANDIDATE:
            score += 2
        case ProfileStatus.EXPERIMENTAL:
            score += 1
        case _:
            pass

    return score
