"""Capability-to-task matching for local inference selection policy.

Compares endpoint probe capabilities against task profile requirements.
Produces structured match results with explanation codes.
"""

from __future__ import annotations

from rig_relay.providers.local_inference.models import (
    CapabilityMatchResult,
    CapabilityProbeCapabilities,
    CapabilityStatus,
    ExplanationCode,
    RoutingConfidence,
    TaskProfileSpec,
)

CAPABILITY_FIELD_MAP: dict[str, str] = {
    "chat_completions": "chat_completions",
    "completions": "completions",
    "embeddings": "embeddings",
    "tool_calling": "tool_calling",
    "structured_json_output": "structured_json_output",
    "streaming": "streaming",
    "vision": "vision",
    "reranking": "reranking",
    "models_list": "models_list",
    "health_endpoint": "health_endpoint",
    "metrics_endpoint": "metrics_endpoint",
}


def match_capabilities(
    capabilities: CapabilityProbeCapabilities, task_profile: TaskProfileSpec
) -> CapabilityMatchResult:
    matched_required: list[str] = []
    missing_required: list[str] = []
    missing_preferred: list[str] = []
    risk_flags: list[str] = []
    explanation_codes: list[str] = []

    SUPPORTED_SET = {CapabilityStatus.SUPPORTED, CapabilityStatus.PARTIAL}

    for cap_name in task_profile.required_capabilities:
        field_name = CAPABILITY_FIELD_MAP.get(cap_name, cap_name)
        status = getattr(capabilities, field_name, None)
        if status in SUPPORTED_SET:
            matched_required.append(cap_name)
        else:
            missing_required.append(cap_name)
            explanation_codes.append(_missing_code_for_capability(cap_name))

    for cap_name in task_profile.preferred_capabilities:
        field_name = CAPABILITY_FIELD_MAP.get(cap_name, cap_name)
        status = getattr(capabilities, field_name, None)
        if status not in SUPPORTED_SET:
            missing_preferred.append(cap_name)

    if task_profile.structured_output_required:
        if "structured_json_output" not in matched_required:
            explanation_codes.append(ExplanationCode.STRUCTURED_JSON_MISSING.value)

    if task_profile.tool_call_required:
        if "tool_calling" not in matched_required:
            explanation_codes.append(ExplanationCode.TOOL_CALLING_MISSING.value)

    if task_profile.min_context_window_tokens > 0:
        explanation_codes.append(ExplanationCode.CONTEXT_WINDOW_UNKNOWN.value)
        risk_flags.append("context_window_not_verified")

    if capabilities.streaming == CapabilityStatus.NOT_TESTED:
        explanation_codes.append(ExplanationCode.STREAMING_UNVERIFIED.value)

    confidence = _compute_confidence(
        len(missing_required),
        len(missing_preferred),
        len(task_profile.required_capabilities),
    )

    return CapabilityMatchResult(
        profile_name=task_profile.profile_name,
        matched_required=matched_required,
        missing_required=missing_required,
        missing_preferred=missing_preferred,
        risk_flags=risk_flags,
        confidence=confidence,
        explanation_codes=explanation_codes,
    )


def _missing_code_for_capability(cap_name: str) -> str:
    mapping: dict[str, str] = {
        "chat_completions": ExplanationCode.FALLBACK_REQUIRED.value,
        "embeddings": ExplanationCode.EMBEDDINGS_MISSING.value,
        "vision": ExplanationCode.VISION_MISSING.value,
        "tool_calling": ExplanationCode.TOOL_CALLING_MISSING.value,
        "structured_json_output": ExplanationCode.STRUCTURED_JSON_MISSING.value,
        "streaming": ExplanationCode.STREAMING_UNVERIFIED.value,
    }
    return mapping.get(cap_name, ExplanationCode.FALLBACK_REQUIRED.value)


def _compute_confidence(
    missing_required: int, missing_preferred: int, total_required: int
) -> RoutingConfidence:
    if missing_required > 0:
        return RoutingConfidence.FALLBACK
    if missing_preferred > 2:
        return RoutingConfidence.LOW
    if missing_preferred > 0:
        return RoutingConfidence.MEDIUM
    return RoutingConfidence.HIGH


__all__ = ["CAPABILITY_FIELD_MAP", "match_capabilities"]
