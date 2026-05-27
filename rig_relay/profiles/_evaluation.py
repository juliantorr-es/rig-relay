"""Profile evaluation harness.

Tests each profile against a validation suite: context assembly,
tool authority preservation, deterministic resolution, capability
refusal, and receipt reconstructability.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from rig_relay.profiles._context_envelope import build_context_envelope
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
        warnings=warnings,
    )


def evaluate_all_profiles(
    profiles: Sequence[HarnessCompatibilityProfile],
) -> list[ProfileEvaluationResult]:
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
