"""Governance adapter for Y3 profile selection admission.

Routes a profile resolution through governance, determining whether
the selected profile is admissible for the intended provider/model/role.
Never grants file/tool/publication authority — only admits or refuses
profile+envelope use.
"""

from __future__ import annotations

import hashlib
import json

from rig_relay.profiles.models import (
    GovernanceAdmissionState,
    ProfileResolutionResult,
    ProfileStatus,
    ResolutionOutcome,
)

_ADMISSION_STATE_CACHE: dict[str, str] = {}


def admit_profile_selection(
    resolution: ProfileResolutionResult,
    provider: str,
    model_id: str,
    task_role: str,
    session_id: str = "",
) -> tuple[str, str | None]:
    """Route a profile selection through governance.

    Returns (admission_state: str, admission_digest: sha256:... or None).
    """
    profile = resolution.selected_profile
    profile_id = profile.profile_id

    cache_key = f"{session_id}:{provider}:{model_id}:{task_role}:{profile_id}"
    if cache_key in _ADMISSION_STATE_CACHE:
        cached_state = _ADMISSION_STATE_CACHE[cache_key]
        payload = json.dumps(
            {"state": cached_state, "cache_hit": True},
            sort_keys=True,
            separators=(",", ":"),
        )
        return cached_state, f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    state: str | None = None

    try:
        from rig_relay.governance.governance_engine import GovernanceEngine

        decision = GovernanceEngine.evaluate_action_legality(
            intent_id=f"profile_selection:{profile_id}",
            intent_kind="profile_selection",
            requested_capabilities=["context_envelope_assembly"],
            evidence_available=True,
            session_id=session_id,
        )

        match decision.decision.value:
            case "allowed":
                state = GovernanceAdmissionState.ADMITTED.value
            case "requires_review":
                state = GovernanceAdmissionState.REQUIRES_REVIEW.value
            case "blocked":
                state = GovernanceAdmissionState.REFUSED.value
            case _:
                state = GovernanceAdmissionState.NOT_EVALUATED.value
    except Exception:
        state = None

    if state is None:
        state = _local_admission_rules(resolution, provider, model_id, task_role)

    _ADMISSION_STATE_CACHE[cache_key] = state

    payload = json.dumps(
        {
            "state": state,
            "profile_id": profile_id,
            "provider": provider,
            "model_id": model_id,
            "task_role": task_role,
            "session_id": session_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    return state, digest


_REFUSED_OUTCOMES: frozenset[str] = frozenset({
    ResolutionOutcome.REFUSED_MISSING_CAPABILITY_EVIDENCE.value,
    ResolutionOutcome.REFUSED_CONFLICTING_CAPABILITY_EVIDENCE.value,
    ResolutionOutcome.REFUSED_UNSUPPORTED_CAPABILITY.value,
})


def _local_admission_rules(
    resolution: ProfileResolutionResult, provider: str, _model_id: str, _task_role: str
) -> str:
    profile = resolution.selected_profile
    profile_id = profile.profile_id
    outcome = resolution.outcome
    user_override = resolution.is_user_override
    is_experimental = profile.evaluation_status == ProfileStatus.EXPERIMENTAL
    is_restricted = outcome == ResolutionOutcome.SELECTED_RESTRICTED.value
    is_candidate = profile.evaluation_status == ProfileStatus.CANDIDATE
    is_rig_native = profile_id == "rig.native.governed.v1"
    evidence_clean = outcome not in _REFUSED_OUTCOMES

    match (
        not provider,
        outcome in _REFUSED_OUTCOMES,
        user_override and (is_experimental or is_restricted),
    ):
        case (True, _, _):
            state = GovernanceAdmissionState.NOT_EVALUATED.value
        case (_, True, _):
            state = GovernanceAdmissionState.REFUSED.value
        case (_, _, True):
            state = GovernanceAdmissionState.REQUIRES_REVIEW.value
        case _:
            if is_candidate and evidence_clean:
                state = GovernanceAdmissionState.ADMITTED.value
            elif is_rig_native and evidence_clean:
                state = GovernanceAdmissionState.ADMITTED.value
            else:
                state = GovernanceAdmissionState.NOT_EVALUATED.value

    return state
