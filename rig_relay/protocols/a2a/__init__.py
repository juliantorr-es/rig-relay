"""rig_relay.protocols.a2a — content-light agent-to-agent delegation protocol."""

from __future__ import annotations

from rig_relay.protocols.a2a._identity import (
    A2ALocalIdentity,
    A2ASecurityScheme,
    build_agent_card_with_security,
    build_identity_metadata,
)
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
from rig_relay.protocols.a2a.server import serve_agent_card, serve_agent_card_json

__all__ = [
    "A2AAgentCard",
    "A2ADelegationReceipt",
    "A2ALocalIdentity",
    "A2ASecurityScheme",
    "A2ATaskCard",
    "A2ATaskLifecycle",
    "A2ATaskLifecycleEvent",
    "A2ATaskStatus",
    "build_agent_card",
    "build_agent_card_with_security",
    "build_delegation_receipt",
    "build_identity_metadata",
    "build_task_card",
    "cancel_task",
    "send_local_task_message",
    "serve_agent_card",
    "serve_agent_card_json",
    "transition_task",
]
