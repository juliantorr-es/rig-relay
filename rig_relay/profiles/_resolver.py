"""Profile resolution logic.

Matches a provider/model/role combination to the best-fitting
harness compatibility profile from the built-in registry.
"""

from __future__ import annotations

from collections.abc import Sequence
import re
from uuid import uuid4

from rig_relay.profiles.models import (
    HarnessCompatibilityProfile,
    ProfileResolutionError,
    ProfileResolutionInput,
    ProfileResolutionResult,
    ProfileStatus,
)

_CONFIDENCE_HIGH_THRESHOLD = 5
_CONFIDENCE_MEDIUM_THRESHOLD = 3


def _determine_confidence(score: int) -> str:
    if score >= _CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= _CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


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

    alternatives_considered: list[str] = []
    alternatives_rejected: dict[str, str] = {}

    if input.prefer_profile_id is not None:
        for p in profiles:
            if p.profile_id == input.prefer_profile_id:
                if _capabilities_satisfied(p, input):
                    return ProfileResolutionResult(
                        resolution_id=str(uuid4()),
                        provider=input.provider,
                        model_id=input.model_id,
                        task_role=input.task_role,
                        selected_profile=p,
                        selected_reason=f"User override: prefer_profile_id={input.prefer_profile_id}",
                        confidence="high",
                        alternatives_considered=[],
                        is_user_override=True,
                        override_source_profile_id=input.prefer_profile_id,
                    )
                alternatives_rejected[p.profile_id] = (
                    "User override requested but capabilities not satisfied"
                )
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
    best_score, best_profile = scored[0]

    confidence = _determine_confidence(best_score)

    all_rejected: dict[str, str] = {}
    for pid in alternatives_considered:
        if pid != best_profile.profile_id and pid in alternatives_rejected:
            all_rejected[pid] = alternatives_rejected[pid]
    for pid, reason in alternatives_rejected.items():
        if pid not in alternatives_considered and pid not in all_rejected:
            all_rejected[pid] = reason

    warnings: list[str] = []
    cap_warnings = _check_capabilities(best_profile, input)
    if cap_warnings:
        warnings = cap_warnings

    return ProfileResolutionResult(
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
        warnings=warnings,
    )


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
