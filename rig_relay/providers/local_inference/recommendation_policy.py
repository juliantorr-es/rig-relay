"""Capability recommendation policy — routes based on evidence rows."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    CapabilityEvidenceRow,
    CapabilityRecommendation,
    RecommendedRoute,
)


def recommend(
    *, row: CapabilityEvidenceRow, now: str | None = None
) -> CapabilityRecommendation:
    return CapabilityRecommendation(
        recommendation_id=f"cr_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        task_profile=row.task_profile,
        request_class=row.request_class,
        recommended_route=row.recommended_route,
        confidence=row.confidence,
        reasons=_build_reasons(row),
    )


def _build_reasons(row: CapabilityEvidenceRow) -> list[str]:
    reasons: list[str] = []
    r = row.recommended_route
    if r == RecommendedRoute.LOCAL_FIRST.value:
        reasons.append("contract_evidence_present")
        reasons.append("acceptable_operational_metrics")
    elif r == RecommendedRoute.SHADOW_FIRST.value:
        reasons.append("promising_but_insufficient_evidence")
    elif r == RecommendedRoute.CLOUD_ESCALATION.value:
        reasons.append("contracts_not_met_or_capacity_exceeded")
    elif r == RecommendedRoute.HUMAN_REVIEW_REQUIRED.value:
        reasons.append(f"mutation_risk_{row.mutation_risk}")
    elif r == RecommendedRoute.INSUFFICIENT_EVIDENCE.value:
        reasons.append("not_enough_evidence_rows")
    return reasons


__all__ = ["recommend"]
