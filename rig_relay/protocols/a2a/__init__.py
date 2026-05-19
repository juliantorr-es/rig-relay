"""rig_relay.protocols.a2a — content-light agent-to-agent delegation protocol."""

from __future__ import annotations

from rig_relay.protocols.a2a._lifecycle import (
    build_agent_card,
    build_delegation_receipt,
    build_task_card,
    cancel_task,
    send_local_task_message,
    transition_task,
)
from rig_relay.protocols.a2a._models import (
    A2AAgentCard,
    A2ADelegationReceipt,
    A2ATaskCard,
    A2ATaskLifecycle,
    A2ATaskLifecycleEvent,
    A2ATaskStatus,
)

__all__ = [
    "A2AAgentCard",
    "A2ADelegationReceipt",
    "A2ATaskCard",
    "A2ATaskLifecycle",
    "A2ATaskLifecycleEvent",
    "A2ATaskStatus",
    "build_agent_card",
    "build_delegation_receipt",
    "build_task_card",
    "cancel_task",
    "send_local_task_message",
    "transition_task",
]
