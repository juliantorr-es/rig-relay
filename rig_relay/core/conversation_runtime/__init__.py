"""ConversationRuntime — turn state machine for agent conversation loops.

Public API:
  ConversationRuntime — owns phase order, loop policy, failure classification
  ConversationRuntimeCallbacks — Protocol for AgentLoop adapter
  ConversationRuntimeRequest / ConversationRuntimeResult / ConversationRuntimeStatus / ConversationRuntimePhaseEvent — models
  PhaseTraceAttributes / PhaseTraceHook — trace evidence interface
"""

from __future__ import annotations

from rig_relay.core.conversation_runtime.models import (
    ConversationLoopDecision,
    ConversationLoopDecisionKind,
    ConversationRuntimeCallbacks,
    ConversationRuntimePhaseEvent,
    ConversationRuntimeRequest,
    ConversationRuntimeResult,
    ConversationRuntimeStatus,
    PhaseTraceAttributes,
    PhaseTraceHook,
)
from rig_relay.core.conversation_runtime.runtime import ConversationRuntime

__all__ = [
    "ConversationLoopDecision",
    "ConversationLoopDecisionKind",
    "ConversationRuntime",
    "ConversationRuntimeCallbacks",
    "ConversationRuntimePhaseEvent",
    "ConversationRuntimeRequest",
    "ConversationRuntimeResult",
    "ConversationRuntimeStatus",
    "PhaseTraceAttributes",
    "PhaseTraceHook",
]
