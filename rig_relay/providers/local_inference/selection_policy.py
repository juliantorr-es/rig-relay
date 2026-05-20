"""Local inference selection policy — governed eligibility evaluation.

Determines whether a local inference endpoint is eligible for agent use.
Never enables automatic execution — only produces policy decisions with
explicit rationale and evidence references.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from typing import Any

from rig_relay.providers.local_inference.models import (
    BenchmarkEvidenceSummary,
    CapabilityMatchResult,
    CapabilityProbeResult,
    ExplanationCode,
    PolicyResultKind,
    TaskProfileSpec,
)

PROBE_STALE_AFTER_DAYS = 7
BENCHMARK_STALE_AFTER_DAYS = 30


def _new_selection_id() -> str:
    return f"sel_{secrets.token_hex(8)}"


def evaluate_selection_policy(
    *,
    endpoint_configured: bool,
    endpoint_sha256: str = "",
    probe_result: CapabilityProbeResult | None = None,
    benchmark_summary: BenchmarkEvidenceSummary | None = None,
    task_profile: TaskProfileSpec | None = None,
    capability_match: CapabilityMatchResult | None = None,
    diagnostics_enabled: bool = True,
    explicit_approval: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    result_kind = PolicyResultKind.NOT_CONFIGURED
    explanation_codes: list[str] = []
    risk_flags: list[str] = []
    confidence = "low"

    if not endpoint_configured:
        explanation_codes.append(ExplanationCode.ENDPOINT_UNCONFIGURED.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            confidence=confidence,
            now=now,
        )

    if probe_result is None:
        result_kind = PolicyResultKind.CONFIGURED_BUT_UNPROBED
        explanation_codes.append(ExplanationCode.PROBE_FAILED.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            confidence=confidence,
            now=now,
        )

    if not probe_result.reachable:
        result_kind = PolicyResultKind.BLOCKED_BY_FAILED_PROBE
        explanation_codes.append(ExplanationCode.PROBE_FAILED.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            confidence=confidence,
            now=now,
        )

    if _is_probe_stale(probe_result, now):
        result_kind = PolicyResultKind.BLOCKED_BY_STALE_EVIDENCE
        explanation_codes.append(ExplanationCode.PROBE_STALE.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            confidence=confidence,
            now=now,
        )

    if not diagnostics_enabled:
        result_kind = PolicyResultKind.BLOCKED_BY_DEGRADED_DIAGNOSTICS
        explanation_codes.append(ExplanationCode.DIAGNOSTICS_DISABLED.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            confidence=confidence,
            now=now,
        )

    if task_profile is not None and capability_match is not None:
        if capability_match.missing_required:
            result_kind = PolicyResultKind.BLOCKED_BY_MISSING_CAPABILITY
            explanation_codes.extend(capability_match.explanation_codes)
            explanation_codes.extend(capability_match.missing_required)
            risk_flags.extend(capability_match.risk_flags)
            return _build_result(
                result_kind=result_kind,
                explanation_codes=explanation_codes,
                risk_flags=risk_flags,
                confidence=confidence,
                now=now,
            )

    has_benchmark = benchmark_summary is not None and benchmark_summary.sample_count > 0
    has_endpoint_match = (
        endpoint_sha256
        and benchmark_summary is not None
        and endpoint_sha256 == benchmark_summary.endpoint_sha256
    )

    if has_benchmark and not has_endpoint_match:
        explanation_codes.append(ExplanationCode.ENDPOINT_HASH_MISMATCH.value)

    if not explicit_approval:
        if has_benchmark and has_endpoint_match:
            result_kind = PolicyResultKind.ELIGIBLE_FOR_MANUAL_SELECTION
        elif probe_result.reachable:
            result_kind = PolicyResultKind.PROBED_BUT_NOT_BENCHMARKED
        explanation_codes.append(ExplanationCode.APPROVAL_MISSING.value)
        return _build_result(
            result_kind=result_kind,
            explanation_codes=explanation_codes,
            risk_flags=risk_flags,
            confidence="medium" if has_benchmark else "low",
            now=now,
        )

    if explicit_approval:
        if has_benchmark and has_endpoint_match:
            result_kind = PolicyResultKind.ELIGIBLE_FOR_POLICY_SELECTION
            confidence = "high"
        elif probe_result.reachable:
            result_kind = PolicyResultKind.PROBED_BUT_NOT_BENCHMARKED
            confidence = "medium"
        else:
            result_kind = PolicyResultKind.BLOCKED_BY_POLICY

    return _build_result(
        result_kind=result_kind,
        explanation_codes=explanation_codes,
        risk_flags=risk_flags,
        confidence=confidence,
        now=now,
    )


def _is_probe_stale(
    probe_result: CapabilityProbeResult, now: str | None = None
) -> bool:
    probed = _parse_iso(probe_result.probed_at)
    if probed is None:
        return False
    if now is not None:
        reference = _parse_iso(now)
        if reference is None:
            return False
    else:
        reference = datetime.now(UTC)
    return (reference - probed) > timedelta(days=PROBE_STALE_AFTER_DAYS)


def _parse_iso(ts: str) -> datetime | None:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _build_result(
    *,
    result_kind: PolicyResultKind,
    explanation_codes: list[str],
    risk_flags: list[str] | None = None,
    confidence: str = "low",
    now: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "rig.local_inference.selection_policy.v1",
        "selection_id": _new_selection_id(),
        "decided_at": now or datetime.now(UTC).isoformat(),
        "result_kind": result_kind.value,
        "confidence": confidence,
        "explanation_codes": explanation_codes,
        "risk_flags": risk_flags or [],
        "diagnostics_enabled": True,
        "manual_selection_allowed": result_kind.value
        in {
            PolicyResultKind.PROBED_BUT_NOT_BENCHMARKED.value,
            PolicyResultKind.ELIGIBLE_FOR_MANUAL_SELECTION.value,
            PolicyResultKind.ELIGIBLE_FOR_POLICY_SELECTION.value,
        },
        "policy_selection_allowed": result_kind.value
        == PolicyResultKind.ELIGIBLE_FOR_POLICY_SELECTION.value,
    }


__all__ = ["evaluate_selection_policy"]
