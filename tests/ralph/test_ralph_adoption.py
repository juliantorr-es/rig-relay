from rig_relay.ralph.adoption import (
    RalphAdoptionProposal,
    build_adoption_proposal,
)
from rig_relay.ralph.lane_contracts import RalphLane


def test_adoption_proposal_to_orchestrator():
    lane = RalphLane(
        lane_id="lane-1",
        branch_name="ralph/test-1",
        latest_commit_sha="abc123",
        review_bundle_sha256="sha256:def456",
        status="sealed",
    )
    proposal = build_adoption_proposal(
        lane,
        target_kind="orchestrator_lane",
        target_lane_id="orch-1",
        relevance_score=0.85,
        relevance_reason="Relevant to ToolRuntime extraction",
    )

    assert proposal.source_ralph_lane_id == "lane-1"
    assert proposal.target_kind == "orchestrator_lane"
    assert proposal.merge_enabled is False
    assert proposal.requires_human_approval is True
    assert proposal.requires_orchestrator_acceptance is True


def test_adoption_proposal_to_user_review():
    lane = RalphLane(
        lane_id="lane-2",
        branch_name="ralph/test-2",
        review_bundle_sha256="sha256:ghi",
        status="sealed",
    )
    proposal = build_adoption_proposal(lane)

    assert proposal.target_kind == "user_review"
    assert proposal.source_ralph_lane_id == "lane-2"
    assert proposal.merge_enabled is False
    assert proposal.requires_orchestrator_acceptance is False


def test_merge_always_disabled():
    proposal = RalphAdoptionProposal(
        source_ralph_lane_id="lane-1",
        review_bundle_sha256="sha256:abc",
        status="adoption_approved",
    )
    assert proposal.merge_enabled is False


def test_adoption_status_can_be_represented_without_merge():
    proposal = RalphAdoptionProposal(
        source_ralph_lane_id="lane-1",
        review_bundle_sha256="sha256:abc",
        status="adoption_approved",
    )
    assert proposal.status == "adoption_approved"
    assert proposal.merge_enabled is False
