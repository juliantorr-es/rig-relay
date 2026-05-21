from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.core.trace_runtime import TraceRuntime


@dataclass(slots=True)
class TurnEnvelope:
    turn_id: str
    trace_id: str
    outcome: str
    phase_count: int
    tool_call_count: int
    tool_success_count: int
    tool_failure_count: int
    tool_refusal_count: int
    budget_decision: str
    duration_ms: int
    summary_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.summary_hash:
            self.summary_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = (
            f"{self.turn_id}|{self.trace_id}|{self.outcome}|"
            f"{self.phase_count}|{self.tool_call_count}|"
            f"{self.tool_success_count}|{self.tool_failure_count}|"
            f"{self.tool_refusal_count}|{self.budget_decision}|"
            f"{self.duration_ms}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def emit(self, trace_runtime: TraceRuntime) -> None:
        trace_runtime.emit_lifecycle_event("turn.completed", self.to_dict())

    def to_dict(self) -> dict[str, str | int]:
        return {
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "outcome": self.outcome,
            "phase_count": self.phase_count,
            "tool_call_count": self.tool_call_count,
            "tool_success_count": self.tool_success_count,
            "tool_failure_count": self.tool_failure_count,
            "tool_refusal_count": self.tool_refusal_count,
            "budget_decision": self.budget_decision,
            "duration_ms": self.duration_ms,
            "summary_hash": self.summary_hash,
        }


__all__ = ["TurnEnvelope"]
