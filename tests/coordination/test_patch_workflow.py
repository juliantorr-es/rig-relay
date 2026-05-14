from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import (
    PatchProposalNotFoundError,
    PatchProposalStateError,
    create_patch_decision,
    record_patch_decision,
)


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


def test_record_patch_decision_updates_proposal_and_writes_decision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "coordination"
    proposal = _proposal()
    proposal_path = root / ".fleet" / "patch-proposals" / "prop-001.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")

    decision = create_patch_decision(
        proposal_id="prop-001",
        decided_by="orchestrator-1",
        decision="accepted",
        reason="Looks good",
        decision_id="dec-001",
    )

    updated, recorded = record_patch_decision(root, decision)

    assert updated.status == "accepted"
    assert recorded.decision == "accepted"

    on_disk = PatchProposal.model_validate_json(
        proposal_path.read_text(encoding="utf-8")
    )
    assert on_disk.status == "accepted"

    decision_path = root / ".fleet" / "patch-decisions" / "dec-001.json"
    assert decision_path.is_file()
    saved = json.loads(decision_path.read_text(encoding="utf-8"))
    assert saved["proposal_id"] == "prop-001"


def test_record_patch_decision_refuses_missing_proposal(tmp_path: Path) -> None:
    root = tmp_path / "coordination"
    decision = create_patch_decision(
        proposal_id="missing",
        decided_by="orchestrator-1",
        decision="accepted",
        reason="Looks good",
        decision_id="dec-001",
    )

    with pytest.raises(PatchProposalNotFoundError):
        record_patch_decision(root, decision)


def test_record_patch_decision_refuses_non_pending(tmp_path: Path) -> None:
    root = tmp_path / "coordination"
    proposal = _proposal().model_copy(update={"status": "accepted"})
    proposal_path = root / ".fleet" / "patch-proposals" / "prop-001.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")

    decision = create_patch_decision(
        proposal_id="prop-001",
        decided_by="orchestrator-1",
        decision="accepted",
        reason="Already applied",
        decision_id="dec-001",
    )

    with pytest.raises(PatchProposalStateError):
        record_patch_decision(root, decision)
