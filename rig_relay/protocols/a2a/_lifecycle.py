"""A2A lifecycle functions — state machine transitions and receipt construction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from rig_relay.protocols.a2a._models import (
    A2AAgentCard,
    A2ADelegationReceipt,
    A2ATaskCard,
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
    return A2ATaskCard(
        task_id=task_id, agent_id=agent_id, description=description, trace_id=trace_id
    )


def transition_task(card: A2ATaskCard, new_status: A2ATaskStatus) -> A2ATaskCard:
    allowed = _VALID_TRANSITIONS.get(card.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid A2A task transition: {card.status.value} -> {new_status.value}"
        )
    now = datetime.now(UTC).isoformat()
    return A2ATaskCard(
        task_id=card.task_id,
        agent_id=card.agent_id,
        status=new_status,
        description=card.description,
        input_hash=card.input_hash,
        output_hash=card.output_hash,
        trace_id=card.trace_id,
        created_at=card.created_at,
        updated_at=now,
        generated_at=now,
        content_light=True,
        schema_version=card.schema_version,
    )


def send_local_task_message(
    card: A2ATaskCard, message: str, trace_id: str = ""
) -> A2ATaskCard:
    now = datetime.now(UTC).isoformat()
    return A2ATaskCard(
        task_id=card.task_id,
        agent_id=card.agent_id,
        status=card.status,
        description=card.description,
        input_hash=card.input_hash,
        output_hash=card.output_hash,
        trace_id=card.trace_id,
        created_at=card.created_at,
        updated_at=now,
        generated_at=now,
        content_light=True,
        schema_version=card.schema_version,
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
    verdict: str = "allowed",
    refusal_code: str = "",
) -> A2ADelegationReceipt:
    return A2ADelegationReceipt(
        receipt_id=f"rcpt_{uuid.uuid4().hex[:16]}",
        delegating_agent_id=delegating_agent_id,
        receiving_agent_id=receiving_agent_id,
        task_id=task_id,
        trace_id=trace_id,
        verdict=verdict,
        refusal_code=refusal_code,
    )
