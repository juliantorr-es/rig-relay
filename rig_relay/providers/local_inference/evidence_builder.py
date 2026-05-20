"""Capability evidence row builder — content-light JSONL output."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    CapabilityEvidenceRow,
    RecommendedRoute,
)


def _new_id() -> str:
    return f"ev_{secrets.token_hex(8)}"


def build_evidence_row(
    *,
    machine_class: str = "",
    runtime_backend_id: str = "",
    runtime_kind: str = "",
    model_family: str = "",
    model_size_class: str = "",
    task_profile: str = "",
    context_bucket: str = "",
    output_contract: str = "",
    contract_passed: bool = False,
    local_latency_ms: int = 0,
    local_ttft_ms: int = 0,
    local_tokens_per_sec: float = 0.0,
    local_input_tokens: int = 0,
    local_output_tokens: int = 0,
    proposal_type: str = "",
    mutation_risk: str = "low",
    cloud_reference_available: bool = False,
    cloud_contract_passed: bool | None = None,
    cloud_latency_ms: int | None = None,
    shadow_passed: bool = False,
    benchmark_available: bool = False,
    now: str | None = None,
) -> CapabilityEvidenceRow:
    row = CapabilityEvidenceRow(
        evidence_id=_new_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        machine_class=machine_class,
        runtime_backend_id=runtime_backend_id,
        runtime_kind=runtime_kind,
        model_family=model_family,
        model_size_class=model_size_class,
        task_profile=task_profile,
        context_bucket=context_bucket,
        output_contract=output_contract,
        contract_passed=contract_passed,
        local_latency_ms=local_latency_ms,
        local_ttft_ms=local_ttft_ms,
        local_tokens_per_sec=local_tokens_per_sec,
        local_input_tokens=local_input_tokens,
        local_output_tokens=local_output_tokens,
        proposal_type=proposal_type,
        mutation_risk=mutation_risk,
        cloud_reference_available=cloud_reference_available,
        cloud_contract_passed=cloud_contract_passed,
        cloud_latency_ms=cloud_latency_ms,
    )

    ev = int(contract_passed) + int(shadow_passed) + int(benchmark_available)
    if ev >= 2 and contract_passed:
        row.recommended_route = RecommendedRoute.LOCAL_FIRST.value
        row.confidence = "high" if ev >= 3 else "medium"
    elif shadow_passed and not contract_passed:
        row.recommended_route = RecommendedRoute.SHADOW_FIRST.value
        row.confidence = "medium"
    elif ev >= 1 and not contract_passed:
        row.recommended_route = RecommendedRoute.CLOUD_ESCALATION.value
        row.confidence = "medium"
    elif mutation_risk in ("high", "critical"):
        row.recommended_route = RecommendedRoute.HUMAN_REVIEW_REQUIRED.value
        row.confidence = "medium"
    else:
        row.recommended_route = RecommendedRoute.INSUFFICIENT_EVIDENCE.value
        row.confidence = "low"
    return row


__all__ = ["build_evidence_row"]
