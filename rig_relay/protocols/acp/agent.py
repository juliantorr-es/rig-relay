"""Rig Relay ACP Agent — governed coding agent for editors.

Exposes Rig as an ACP-compatible agent that editors (Zed, JetBrains, etc.)
can drive through session management, progress streaming, edit proposals,
and permission requests. All mutations go through Rig's governance layer.

Architecture:
  ACP Session    → Rig mission/session
  ACP Progress   → Rig progress events
  ACP Edit       → Rig patch proposal (never direct write)
  ACP Permission → Rig approval gate
  ACP Terminal   → Rig deterministic execution stream
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══ ACP Session ════════════════════════════════════════════════════════


class ACPSessionStatus(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ACPSessionInfo(BaseModel):
    session_id: str
    status: ACPSessionStatus = ACPSessionStatus.IDLE
    mission_id: str | None = None
    worktree_path: str | None = None
    branch: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ═══ ACP Progress ═══════════════════════════════════════════════════════


class ACPProgressEvent(BaseModel):
    event_id: str
    session_id: str
    phase: str  # planning, exploration, building, validation, review
    status: str  # running, completed, failed, blocked
    message: str = ""
    percent: float | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ═══ ACP Edit Proposal ══════════════════════════════════════════════════


class ACPEditProposal(BaseModel):
    """A proposed edit. Never applied directly — always goes through governance."""

    proposal_id: str
    session_id: str
    title: str
    summary: str
    touched_paths: list[str] = Field(default_factory=list)
    touched_path_hashes: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending, approved, rejected, applied
    diff_sha256: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ACPEditResult(BaseModel):
    proposal_id: str
    status: str
    applied_paths: list[str] = Field(default_factory=list)
    validation_result: str = ""  # passed, failed, skipped
    receipt_sha256: str = ""


# ═══ ACP Permission ═════════════════════════════════════════════════════


class ACPPermissionRequest(BaseModel):
    request_id: str
    session_id: str
    action: str
    rationale: str
    affected_paths: list[str] = Field(default_factory=list)
    risk_level: str = "low"  # low, medium, high, critical
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ACPPermissionResponse(BaseModel):
    request_id: str
    decision: str  # approved, denied, deferred
    rationale: str = ""
    authorization_receipt: str = ""


# ═══ ACP Terminal ═══════════════════════════════════════════════════════


class ACPTerminalOutput(BaseModel):
    session_id: str
    command: str
    exit_code: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    output_sha256: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ═══ ACP Plan ═══════════════════════════════════════════════════════════


class ACPPlan(BaseModel):
    plan_id: str
    session_id: str
    title: str
    phases: list[dict[str, Any]] = Field(default_factory=list)
    estimated_missions: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ═══ ACP Agent ══════════════════════════════════════════════════════════


@dataclass
class ACPAgentCapabilities:
    planning: bool = True
    editing: bool = True
    terminal: bool = True
    progress_streaming: bool = True
    permission_gating: bool = True
    receipt_backing: bool = True
    consultation: bool = True


class RigACPAgent:
    """Rig as an ACP-compatible coding agent.

    Editors connect to this agent to drive missions, receive progress
    events, propose edits, and request permissions. Every mutation
    flows through Rig's patch-proposal → review → apply governance loop.

    Usage:
        agent = RigACPAgent()
        session = await agent.create_session(mission_id="M123")
        await agent.stream_progress(session.session_id, callback)
        proposal = await agent.propose_edit(session_id, title, summary, paths)
        result = await agent.request_permission(action, rationale)
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ACPSessionInfo] = {}
        self._capabilities = ACPAgentCapabilities()

    @property
    def capabilities(self) -> ACPAgentCapabilities:
        return self._capabilities

    async def create_session(self, mission_id: str | None = None) -> ACPSessionInfo:
        session_id = f"acp-{datetime.now(UTC).timestamp():.0f}"
        session = ACPSessionInfo(
            session_id=session_id,
            mission_id=mission_id,
            status=ACPSessionStatus.IDLE,
        )
        self._sessions[session_id] = session
        return session

    async def get_session(self, session_id: str) -> ACPSessionInfo | None:
        return self._sessions.get(session_id)

    async def set_status(self, session_id: str, status: ACPSessionStatus) -> None:
        if session := self._sessions.get(session_id):
            session.status = status

    async def create_plan(self, session_id: str, title: str, phases: list[dict[str, Any]]) -> ACPPlan:
        return ACPPlan(
            plan_id=f"plan-{datetime.now(UTC).timestamp():.0f}",
            session_id=session_id,
            title=title,
            phases=phases,
            estimated_missions=len(phases),
        )

    async def propose_edit(
        self,
        session_id: str,
        title: str,
        summary: str,
        touched_paths: list[str],
    ) -> ACPEditProposal:
        return ACPEditProposal(
            proposal_id=f"prop-{datetime.now(UTC).timestamp():.0f}",
            session_id=session_id,
            title=title,
            summary=summary,
            touched_paths=touched_paths,
        )

    async def request_permission(
        self,
        session_id: str,
        action: str,
        rationale: str,
        affected_paths: list[str] | None = None,
    ) -> ACPPermissionRequest:
        return ACPPermissionRequest(
            request_id=f"perm-{datetime.now(UTC).timestamp():.0f}",
            session_id=session_id,
            action=action,
            rationale=rationale,
            affected_paths=affected_paths or [],
        )

    async def stream_progress(
        self,
        session_id: str,
        phase: str,
        status: str,
        message: str,
        percent: float | None = None,
    ) -> ACPProgressEvent:
        return ACPProgressEvent(
            event_id=f"prog-{datetime.now(UTC).timestamp():.0f}",
            session_id=session_id,
            phase=phase,
            status=status,
            message=message,
            percent=percent,
        )


__all__ = [
    "ACPAgentCapabilities",
    "ACPEditProposal",
    "ACPEditResult",
    "ACPPermissionRequest",
    "ACPPermissionResponse",
    "ACPPlan",
    "ACPProgressEvent",
    "ACPSessionInfo",
    "ACPSessionStatus",
    "ACPTerminalOutput",
    "RigACPAgent",
]
