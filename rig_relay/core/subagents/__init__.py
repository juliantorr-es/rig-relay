"""SubagentRuntime — bounded mission execution without full AgentLoop.

Public API:
  SubagentRuntime — execute one bounded mission, return one bounded result
  SubagentMission — input contract (task, scope, budget, profile)
  SubagentResult — output contract (status, summary, errors, artifacts)
  SubagentRuntimeError — structured runtime error
  SubagentRuntimeTrace — trace evidence payload
  SubagentProfileKind / SubagentTrustTier — profile classifications
"""

from __future__ import annotations

from rig_relay.core.subagents.models import (
    SubagentMission,
    SubagentProfileKind,
    SubagentResult,
    SubagentRuntimeError,
    SubagentRuntimeTrace,
    SubagentTrustTier,
)
from rig_relay.core.subagents.runtime import SubagentRuntime

__all__ = [
    "SubagentMission",
    "SubagentProfileKind",
    "SubagentResult",
    "SubagentRuntime",
    "SubagentRuntimeError",
    "SubagentRuntimeTrace",
    "SubagentTrustTier",
]
