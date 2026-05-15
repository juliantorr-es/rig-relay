"""Receipt and evidence event types for the agent loop.

Surface receipt IDs, council findings, and desktop intent results
as first-class events the agent can reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReceiptEvent:
    """Emitted when a tool call produces a receipt."""
    tool_call_id: str
    tool_name: str
    receipt_id: str
    receipt_kind: str
    sha256: str = ""


@dataclass
class CouncilFindingsEvent:
    """Emitted when Council consultation completes."""
    receipt_id: str
    provider_count: int
    consensus_findings: list[str] = field(default_factory=list)
    disagreement_findings: list[str] = field(default_factory=list)
    decision: str = ""


@dataclass
class DesktopIntentEvent:
    """Emitted when a desktop intent completes (fleet cycle, worktree op, etc.)."""
    intent_id: str
    intent_kind: str
    status: str
    summary: str = ""
    receipt_ids: list[str] = field(default_factory=list)
