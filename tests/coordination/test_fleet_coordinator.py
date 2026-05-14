from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.coordination.fleet_coordinator import FleetCoordinator
from rig_relay.coordination.patch_proposal import PatchDecision, PatchProposal
from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionRunner


def _proposal() -> PatchProposal:
    return PatchProposal(
        proposal_id="prop-001",
        mission_id="mission-1",
        agent_id="agent-1",
        title="Update projection",
        summary="Wire fleet projection to coordination root.",
        touched_paths=["rig_relay/coordination/fleet_projection.py"],
        touched_path_hashes=[
            "sha256:0000000000000000000000000000000000000000000000000000000000000001"
        ],
    )


def _decision() -> PatchDecision:
    return PatchDecision(
        decision_id="dec-001",
        proposal_id="prop-001",
        decided_by="orchestrator-1",
        decision="accepted",
        reason="Looks good",
    )


def test_recovery_summary_empty(tmp_path: Path) -> None:
    coordinator = FleetCoordinator(tmp_path, MagicMock(spec=RuntimeToolExecutionRunner))
    summary = coordinator.recovery_summary()
    assert summary.active_items == 0
    assert summary.blocked_items == 0
    assert summary.failed_items == 0
    assert summary.retry_delay_seconds == 0
    assert summary.next_retry_at is None


@pytest.mark.asyncio
async def test_run_once_delegates_to_queue_runner(tmp_path: Path) -> None:
    executor = MagicMock(spec=RuntimeToolExecutionRunner)
    executor.execute_validate = AsyncMock()
    executor.execute_runtime_exec = AsyncMock()
    coordinator = FleetCoordinator(tmp_path, executor)
    result = await coordinator.run_once()
    assert result.decision == "idle"


def test_record_patch_decision_round_trip(tmp_path: Path) -> None:
    root = tmp_path
    proposal = _proposal()
    proposal_path = root / ".fleet" / "patch-proposals" / "prop-001.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")

    coordinator = FleetCoordinator(root, MagicMock(spec=RuntimeToolExecutionRunner))
    proposal_id, decision_id = coordinator.record_patch_decision(_decision())
    assert proposal_id == "prop-001"
    assert decision_id == "dec-001"
