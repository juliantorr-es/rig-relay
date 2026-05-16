"""Tests for Rig Fleet Coordination models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from pydantic import ValidationError
import pytest

pytestmark = [pytest.mark.integration]


from rig_relay.coordination.fleet_models import (
    FleetAgentMessage,
    FleetAgentSession,
    FleetCoordinationEvent,
    FleetMergeDecision,
    FleetPatchProposal,
    FleetPathLease,
    FleetWorkClaim,
)


def test_fleet_agent_session_instantiation() -> None:
    session = FleetAgentSession(agent_id="agent-001", mission_id="mission-001")
    assert session.agent_id == "agent-001"
    assert session.status == "active"
    assert session.schema_version == "rig.fleet.agent_session.v1"


def test_fleet_work_claim_instantiation() -> None:
    claim = FleetWorkClaim(
        claim_id=str(uuid.uuid4()),
        agent_id="agent-001",
        mission_id="mission-001",
        task_id="task-001",
    )
    assert claim.task_id == "task-001"
    assert claim.status == "active"


def test_fleet_path_lease_instantiation() -> None:
    expires_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    lease = FleetPathLease(
        lease_id=str(uuid.uuid4()),
        agent_id="agent-001",
        mission_id="mission-001",
        paths=["sha256:path1", "sha256:path2"],
        mode="exclusive_write",
        expires_at=expires_at,
    )
    assert lease.mode == "exclusive_write"
    assert len(lease.paths) == 2


def test_fleet_agent_message_instantiation() -> None:
    msg = FleetAgentMessage(
        message_id=str(uuid.uuid4()),
        from_agent="agent-001",
        to_agent="orchestrator",
        message_kind="blocker_reported",
        mission_id="mission-001",
        payload={"reason": "Need human approval for security-sensitive change"},
    )
    assert msg.message_kind == "blocker_reported"
    assert msg.payload["reason"] == "Need human approval for security-sensitive change"


def test_fleet_coordination_event_instantiation() -> None:
    event = FleetCoordinationEvent(
        event_id=str(uuid.uuid4()),
        mission_id="mission-001",
        agent_id="agent-001",
        event_kind="path_lease_granted",
        payload={"lease_id": "lease-001"},
    )
    assert event.event_kind == "path_lease_granted"


def test_fleet_patch_proposal_instantiation() -> None:
    proposal = FleetPatchProposal(
        proposal_id=str(uuid.uuid4()),
        agent_id="agent-001",
        mission_id="mission-001",
        patch_artifact_id="artifact-001",
        rationale="Fixes a race condition in the auth middleware",
    )
    assert proposal.status == "pending"
    assert proposal.patch_artifact_id == "artifact-001"


def test_fleet_merge_decision_instantiation() -> None:
    decision = FleetMergeDecision(
        decision_id=str(uuid.uuid4()),
        proposal_id="proposal-001",
        decision="applied",
        reviewer_id="human-operator",
        notes="Validated on staging environment.",
    )
    assert decision.decision == "applied"
    assert decision.reviewer_id == "human-operator"


def test_fleet_agent_session_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        FleetAgentSession(
            agent_id="agent-001",
            mission_id="mission-001",
            extra_field="not allowed",  # type: ignore
        )
