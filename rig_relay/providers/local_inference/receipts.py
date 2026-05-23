"""Local inference airlock receipts — ReceiptEnvelope builders using correct API.

Each airlock operation produces a content-light receipt with SHA256 evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptActorTier,
    ReceiptDecision,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.providers.local_inference.models import (
    CapabilityProbeResult,
    RoutingDecision,
)


def build_probe_receipt(
    probe_result: CapabilityProbeResult, *, created_at: str | None = None
) -> dict[str, Any]:
    envelope = build_receipt_envelope(
        receipt_kind="local_inference_probe",
        actor=ReceiptActor(
            actor_id="airlock:local_inference",
            actor_kind=ReceiptActorKind.SYSTEM,
            display_name="Local Inference Airlock",
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        ),
        subject=ReceiptSubject(
            subject_id=probe_result.probe_id,
            subject_kind=ReceiptSubjectKind.RUNTIME_INVOCATION,
        ),
        receipt_payload=probe_result.model_dump(mode="json"),
        decision=ReceiptDecision(
            decision="probed",
            rationale=f"Endpoint probed: {probe_result.runtime_url}",
            gate="local_inference_airlock",
        ),
        created_at=created_at or datetime.now(UTC).isoformat(),
    )
    return envelope.model_dump(mode="json")


def build_routing_receipt(
    routing_decision: RoutingDecision, *, created_at: str | None = None
) -> dict[str, Any]:
    envelope = build_receipt_envelope(
        receipt_kind="local_inference_routing",
        actor=ReceiptActor(
            actor_id="airlock:local_inference",
            actor_kind=ReceiptActorKind.SYSTEM,
            display_name="Local Inference Airlock",
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        ),
        subject=ReceiptSubject(
            subject_id=routing_decision.decision_id,
            subject_kind=ReceiptSubjectKind.GOVERNANCE_DECISION,
        ),
        receipt_payload=routing_decision.model_dump(mode="json"),
        decision=ReceiptDecision(
            decision="selected"
            if routing_decision.confidence.value != "fallback"
            else "fallback",
            rationale=routing_decision.decision_rationale,
            gate="local_inference_airlock",
        ),
        created_at=created_at or datetime.now(UTC).isoformat(),
    )
    return envelope.model_dump(mode="json")


def build_config_receipt(
    config_snapshot: dict[str, Any], *, created_at: str | None = None
) -> dict[str, Any]:
    envelope = build_receipt_envelope(
        receipt_kind="local_inference_config",
        actor=ReceiptActor(
            actor_id="airlock:local_inference",
            actor_kind=ReceiptActorKind.SYSTEM,
            display_name="Local Inference Airlock",
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        ),
        subject=ReceiptSubject(
            subject_id=config_snapshot.get("endpoint_sha256", "config"),
            subject_kind=ReceiptSubjectKind.ARTIFACT,
        ),
        receipt_payload=config_snapshot,
        decision=ReceiptDecision(
            decision="configured"
            if config_snapshot.get("configured")
            else "unconfigured",
            rationale="local_inference_config",
            gate="local_inference_airlock",
        ),
        created_at=created_at or datetime.now(UTC).isoformat(),
    )
    return envelope.model_dump(mode="json")


__all__ = ["build_config_receipt", "build_probe_receipt", "build_routing_receipt"]
