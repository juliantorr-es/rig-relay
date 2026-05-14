"""Rig Fleet Coordination Models — Design Seam.

Defines the core pydantic models for the Rig Fleet Coordination Plane.
Follows the 'content-light' principle: no raw prompts, secrets, or large blobs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FleetAgentSession(BaseModel):
    """Represents an active agent in the fleet.

    Maps to CoordinationSession in the underlying store.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.agent_session.v1"
    agent_id: str  # Maps to session_id
    mission_id: str
    status: Literal["active", "ended", "crashed"] = "active"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_heartbeat_at: str | None = None


class FleetWorkClaim(BaseModel):
    """A claim on a specific mission, task, or subtask.

    Maps to CoordinationTaskClaim in the underlying store.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.work_claim.v1"
    claim_id: str
    agent_id: str
    mission_id: str
    task_id: str
    status: Literal["active", "released", "done", "failed"] = "active"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class FleetPathLease(BaseModel):
    """Exclusive or shared lease on file paths.

    Maps to CoordinationPathReservation in the underlying store.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.path_lease.v1"
    lease_id: str
    agent_id: str
    mission_id: str
    paths: list[str]  # salted SHA256 hashes for events; stable hashes for store
    mode: Literal["exclusive_write", "shared_read"]
    expires_at: str
    status: Literal["active", "released", "expired", "stale"] = "active"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class FleetAgentMessage(BaseModel):
    """Typed message between agents or with the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.agent_message.v1"
    message_id: str
    from_agent: str
    to_agent: str
    message_kind: Literal[
        "blocker_reported",
        "handoff_requested",
        "handoff_accepted",
        "handoff_rejected",
        "status_update",
        "review_requested",
        "help_needed",
    ]
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mission_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FleetCoordinationEvent(BaseModel):
    """Canonical entry in the fleet event log."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.coordination_event.v1"
    event_id: str
    mission_id: str
    agent_id: str
    event_kind: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    parent_event_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class FleetPatchProposal(BaseModel):
    """A proposed mutation to one or more files."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.patch_proposal.v1"
    proposal_id: str
    agent_id: str
    mission_id: str
    patch_artifact_id: str
    rationale: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: Literal["pending", "applied", "rejected", "revised"] = "pending"


class FleetMergeDecision(BaseModel):
    """The orchestrator's decision on a patch proposal."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.merge_decision.v1"
    decision_id: str
    proposal_id: str
    decision: Literal["applied", "rejected", "revised"]
    reviewer_id: str
    notes: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


__all__ = [
    "FleetAgentMessage",
    "FleetAgentSession",
    "FleetCoordinationEvent",
    "FleetMergeDecision",
    "FleetPatchProposal",
    "FleetPathLease",
    "FleetWorkClaim",
]
