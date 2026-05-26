"""A2A lifecycle functions — state machine transitions and receipt construction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
import uuid

from rig_relay.protocols.a2a._models import (
    A2AAgentCard,
    A2ADelegationReceipt,
    A2ATaskCard,
    A2ATaskLifecycleEvent,
    A2ATaskStatus,
)

_VALID_TRANSITIONS: dict[A2ATaskStatus, set[A2ATaskStatus]] = {
    A2ATaskStatus.CREATED: {A2ATaskStatus.SUBMITTED},
    A2ATaskStatus.SUBMITTED: {A2ATaskStatus.RUNNING, A2ATaskStatus.CANCELLED},
    A2ATaskStatus.RUNNING: {
        A2ATaskStatus.INPUT_REQUIRED,
        A2ATaskStatus.COMPLETED,
        A2ATaskStatus.FAILED,
        A2ATaskStatus.CANCELLED,
    },
    A2ATaskStatus.INPUT_REQUIRED: {A2ATaskStatus.RUNNING, A2ATaskStatus.CANCELLED},
    A2ATaskStatus.COMPLETED: set(),
    A2ATaskStatus.FAILED: set(),
    A2ATaskStatus.CANCELLED: set(),
}

_TERMINAL_STATUSES: set[A2ATaskStatus] = {
    A2ATaskStatus.COMPLETED,
    A2ATaskStatus.FAILED,
    A2ATaskStatus.CANCELLED,
}


def delegation_allowed_by_governance(
    delegating_agent_id: str, receiving_agent_id: str, task_description: str = ""
) -> tuple[bool, str]:
    """Check whether A2A task delegation is allowed by governance.

    Per cross_surface_authority_spine v1, A2A is inter-agent delegation
    with explicit trust tier requirements. Remote federation is not
    supported (local_only: true). Delegation is blocked until Agent Card
    attestation and trust tier enforcement exist.

    Returns (allowed: bool, reason: str).
    """
    return (
        False,
        "A2A operational task delegation blocked: cross_surface_authority_spine v1 "
        "requires Agent Card attestation, trust tier enforcement, and governance "
        "decision spine before delegation is enabled. A2A is currently local-only "
        "no-op. See docs/json/governance/cross_surface_authority_spine_v1.v1.json.",
    )


def build_agent_card(
    agent_id: str,
    name: str,
    description: str = "",
    capabilities: list[str] | None = None,
    supported_task_types: list[str] | None = None,
) -> A2AAgentCard:
    return A2AAgentCard(
        agent_id=agent_id,
        name=name,
        description=description,
        capabilities=capabilities or [],
        supported_task_types=supported_task_types or [],
    )


def build_task_card(
    task_id: str, agent_id: str, description: str = "", trace_id: str = ""
) -> A2ATaskCard:
    now = datetime.now(UTC).isoformat()
    card = A2ATaskCard(
        task_id=task_id,
        agent_id=agent_id,
        description=description,
        trace_id=trace_id,
        seq=1,
    )
    card.events.append(
        A2ATaskLifecycleEvent(
            event_type=A2ATaskStatus.CREATED,
            timestamp=now,
            task_id=task_id,
            trace_id=trace_id,
            seq=1,
        )
    )
    return card


def transition_task(card: A2ATaskCard, new_status: A2ATaskStatus) -> A2ATaskCard:
    allowed = _VALID_TRANSITIONS.get(card.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid A2A task transition: {card.status.value} -> {new_status.value}"
        )
    now = datetime.now(UTC).isoformat()
    new_seq = card.seq + 1
    new_card = A2ATaskCard(
        task_id=card.task_id,
        agent_id=card.agent_id,
        status=new_status,
        description=card.description,
        input_hash=card.input_hash,
        output_hash=card.output_hash,
        trace_id=card.trace_id,
        messages=list(card.messages),
        events=list(card.events),
        seq=new_seq,
        created_at=card.created_at,
        updated_at=now,
        generated_at=now,
        content_light=True,
        schema_version=card.schema_version,
        artifact_refs=list(card.artifact_refs),
        extensions=dict(card.extensions) if card.extensions is not None else None,
        cancellation_reason=card.cancellation_reason,
        refusal_reason=card.refusal_reason,
        trust_tier=card.trust_tier,
        integrity_digest=card.integrity_digest,
    )
    new_card.events.append(
        A2ATaskLifecycleEvent(
            event_type=new_status,
            timestamp=now,
            task_id=card.task_id,
            trace_id=card.trace_id,
            seq=new_seq,
        )
    )
    return new_card


def send_local_task_message(
    card: A2ATaskCard, message: str, trace_id: str = ""
) -> A2ATaskCard:
    now = datetime.now(UTC).isoformat()
    new_messages = list(card.messages)
    new_messages.append(message)
    return A2ATaskCard(
        task_id=card.task_id,
        agent_id=card.agent_id,
        status=card.status,
        description=card.description,
        input_hash=card.input_hash,
        output_hash=card.output_hash,
        trace_id=card.trace_id,
        messages=new_messages,
        events=list(card.events),
        seq=card.seq,
        created_at=card.created_at,
        updated_at=now,
        generated_at=now,
        content_light=True,
        schema_version=card.schema_version,
        artifact_refs=list(card.artifact_refs),
        extensions=dict(card.extensions) if card.extensions is not None else None,
        cancellation_reason=card.cancellation_reason,
        refusal_reason=card.refusal_reason,
        trust_tier=card.trust_tier,
        integrity_digest=card.integrity_digest,
    )


def cancel_task(card: A2ATaskCard) -> A2ATaskCard:
    if card.status in _TERMINAL_STATUSES:
        return card
    return transition_task(card, A2ATaskStatus.CANCELLED)


def build_delegation_receipt(
    delegating_agent_id: str,
    receiving_agent_id: str,
    task_id: str,
    trace_id: str = "",
    verdict: Literal["allowed", "refused", "completed"] = "allowed",
    refusal_code: str = "",
) -> A2ADelegationReceipt:
    allowed, reason = delegation_allowed_by_governance(
        delegating_agent_id, receiving_agent_id, task_id
    )
    if not allowed:
        return A2ADelegationReceipt(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:16]}",
            delegating_agent_id=delegating_agent_id,
            receiving_agent_id=receiving_agent_id,
            task_id=task_id,
            trace_id=trace_id,
            verdict="refused",
            refusal_code="governance_blocked",
        )
    return A2ADelegationReceipt(
        receipt_id=f"rcpt_{uuid.uuid4().hex[:16]}",
        delegating_agent_id=delegating_agent_id,
        receiving_agent_id=receiving_agent_id,
        task_id=task_id,
        trace_id=trace_id,
        verdict=verdict,
        refusal_code=refusal_code,
    )
