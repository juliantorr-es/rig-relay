from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
import uuid

from pydantic import BaseModel, ConfigDict, Field


class OperatorSessionStatus(StrEnum):
    """Operator session lifecycle states."""

    OPENED = auto()
    INVESTIGATING = auto()
    AWAITING_PROPOSAL = auto()
    PROPOSAL_GENERATED = auto()
    COMPLETED = auto()
    BLOCKED = auto()
    REFUSED = auto()
    INFERENCE_NEEDED = auto()
    FAILED = auto()


class ProposalDisposition(StrEnum):
    """Disposition of a governed proposal."""

    PROPOSED = auto()
    ADMITTED = auto()
    REFUSED = auto()
    DEFERRED = auto()
    BLOCKED_BY_DIRTY_WORKSPACE = auto()
    BLOCKED_BY_PERMISSION = auto()


class ToolActivity(BaseModel):
    """Content-light summary of a tool's activity in the session."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    refusal_count: int = 0
    last_call_at: str | None = None


class ProposalResult(BaseModel):
    """A governed proposal artifact produced by the operator session."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    scope: str
    description: str
    disposition: ProposalDisposition = ProposalDisposition.PROPOSED
    affected_paths_sha256: list[str] = Field(default_factory=list)
    evidence_sha256: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    disposition_at: str | None = None


class OperatorSession(BaseModel):
    """A bounded operator investigation session over an imported workspace."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex[:12]}")
    workspace_root: str
    workspace_digest: str
    repository_label: str
    purpose: str
    status: OperatorSessionStatus = OperatorSessionStatus.OPENED
    agent_profile_name: str = "plan"
    tool_activities: list[ToolActivity] = Field(default_factory=list)
    proposals: list[ProposalResult] = Field(default_factory=list)
    refusal_count: int = 0
    evidence_sha256: str | None = None
    error_message: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed_at: str | None = None

    @staticmethod
    def digest_path(path: str) -> str:
        """Content-light SHA256 of a workspace path."""
        return f"sha256:{hashlib.sha256(path.encode()).hexdigest()}"


class OperatorSessionProjection(BaseModel):
    """Content-light projection for Gridline rendering.

    Never includes raw file contents, prompts, model outputs, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    repository_label: str
    purpose: str
    status: str
    phase: str = "idle"
    tool_summary: list[ToolActivity] = Field(default_factory=list)
    proposal_count: int = 0
    proposal_dispositions: dict[str, int] = Field(default_factory=dict)
    refusal_count: int = 0
    pending_decisions: list[str] = Field(default_factory=list)
    blocked_capabilities: list[str] = Field(default_factory=list)
    deferred_integrations: list[str] = Field(default_factory=list)
    recovery_materialization_available: bool = False
    evidence_integrity: str = "ok"
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""
