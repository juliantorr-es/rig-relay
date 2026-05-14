"""Rig Relay Governance Decision Models — Ported from Rig domain/governance/decisions.py.

Provides the decision and reason models for the governance engine:
- GovernanceDecisionKind (allowed, blocked, requires_review, not_applicable)
- GovernanceReasonSeverity (info, warning, error, critical)
- DecisionReason, BlockedIntent, AllowedIntent, GateDecision

Provenance (Rig-to-Relay porting doctrine):
  Porting status: port_direct (Rig source: rig/domain/governance/decisions.py).
  Deviations: Pydantic BaseModel with extra="forbid" instead of frozen dataclass;
  added AllowedIntent model (Rig used plain str list); added GovernanceReasonSeverity.CRITICAL;
  added schema_version field.
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class GovernanceDecisionKind(StrEnum):
    """Possible outcomes of a governance gate evaluation."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    REQUIRES_REVIEW = "requires_review"
    NOT_APPLICABLE = "not_applicable"


class GovernanceReasonSeverity(StrEnum):
    """Severity levels for governance decision reasons.

    Rig relay adds CRITICAL (Rig only had info/warning/error).
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DecisionReason(BaseModel):
    """A single reason contributing to a governance decision.

    Fields:
        code: Machine-readable reason code (e.g. "provider_blocked").
        message: Human-readable explanation.
        severity: Severity of this reason.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: GovernanceReasonSeverity = GovernanceReasonSeverity.INFO


class BlockedIntent(BaseModel):
    """An intent that was blocked by a governance gate.

    Fields:
        intent_id: Identifier of the blocked intent.
        reason: Human-readable explanation of why it was blocked.
        code: Optional machine-readable reason code.
    """

    model_config = ConfigDict(extra="forbid")

    intent_id: str
    reason: str
    code: str | None = None


class AllowedIntent(BaseModel):
    """An intent that was allowed by a governance gate.

    Fields:
        intent_id: Identifier of the allowed intent.
        reason: Optional human-readable explanation.
    """

    model_config = ConfigDict(extra="forbid")

    intent_id: str
    reason: str | None = None


class GateDecision(BaseModel):
    """The result of evaluating an action against a governance gate.

    Fields:
        schema_version: Schema version identifier.
        workspace_id: Optional workspace context identifier.
        decision: The governance decision outcome.
        gate: Name of the gate that produced this decision.
        reasons: List of reasons contributing to the decision.
        allowed_intents: Intents explicitly allowed by this decision.
        blocked_intents: Intents explicitly blocked by this decision.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.governance_decision.v1"
    workspace_id: str | None = None
    decision: GovernanceDecisionKind
    gate: str
    reasons: list[DecisionReason] = []
    allowed_intents: list[AllowedIntent] = []
    blocked_intents: list[BlockedIntent] = []


__all__ = [
    "AllowedIntent",
    "BlockedIntent",
    "DecisionReason",
    "GateDecision",
    "GovernanceDecisionKind",
    "GovernanceReasonSeverity",
]
