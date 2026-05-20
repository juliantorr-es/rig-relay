"""Automatic routing decision engine for local inference.

Extends selection policy with runtime orchestration awareness.
Default: auto_routing_disabled. Requires explicit evidence to route.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    AutoRoutingDecision,
    AutoRoutingStatus,
)


def _new_decision_id() -> str:
    return f"ard_{secrets.token_hex(8)}"


def evaluate_auto_routing(
    *,
    backend_id: str = "",
    model_id_hash: str = "",
    endpoint_url: str = "",
    health_check_passed: bool = False,
    capability_match_passed: bool = False,
    benchmark_evidence_available: bool = False,
    shadow_evidence_available: bool = False,
    task_profile: str = "",
    diagnostics_enabled: bool = True,
    routing_enabled: bool = False,
    now: str | None = None,
) -> AutoRoutingDecision:
    receipt = AutoRoutingDecision(
        decision_id=_new_decision_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        status=AutoRoutingStatus.AUTO_ROUTING_DISABLED.value,
        backend_id=backend_id,
        model_id_hash=model_id_hash,
        endpoint_url=endpoint_url,
        task_profile=task_profile,
        fallback_required=True,
    )

    if not routing_enabled:
        receipt.blocked_reasons.append("auto_routing_disabled_by_policy")
        return receipt

    if not backend_id:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_NO_RUNTIME.value
        receipt.blocked_reasons.append("no_backend_selected")
        return receipt

    if not model_id_hash:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_MODEL_MISSING.value
        receipt.blocked_reasons.append("model_missing")
        return receipt

    if not health_check_passed:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_FAILED_HEALTH.value
        receipt.blocked_reasons.append("health_check_failed")
        return receipt

    if not diagnostics_enabled:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_POLICY.value
        receipt.blocked_reasons.append("diagnostics_disabled")
        return receipt

    if not capability_match_passed:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_MISSING_CAPABILITY.value
        receipt.blocked_reasons.append("capability_mismatch")
        return receipt

    if not diagnostics_enabled:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_POLICY.value
        receipt.blocked_reasons.append("diagnostics_disabled")
        return receipt

    if not benchmark_evidence_available:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_MISSING_BENCHMARK.value
        receipt.blocked_reasons.append("benchmark_evidence_missing")
        return receipt

    if not shadow_evidence_available and task_profile in {
        "tool_planning",
        "structured_json",
    }:
        receipt.status = AutoRoutingStatus.BLOCKED_BY_MISSING_SHADOW_EVIDENCE.value
        receipt.blocked_reasons.append("shadow_evidence_required_for_high_risk")
        return receipt

    receipt.status = AutoRoutingStatus.ELIGIBLE_FOR_AUTO_ROUTING.value
    receipt.fallback_required = False
    receipt.health_check_passed = True
    receipt.capability_match_passed = True
    receipt.benchmark_evidence_available = True
    receipt.shadow_evidence_available = True
    receipt.routing_confidence = "high"
    return receipt


__all__ = ["evaluate_auto_routing"]
