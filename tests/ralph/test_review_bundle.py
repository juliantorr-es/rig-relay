from __future__ import annotations

import pytest

from rig_relay.ralph.lane_contracts import RalphLane
from rig_relay.ralph.review_bundle import build_review_bundle, build_review_projection

pytestmark = [pytest.mark.integration]


def test_bundle_from_lane():
    lane = RalphLane(
        lane_id="lane-1",
        branch_name="ralph/test-abc12345",
        base_head="abc123",
        latest_commit_sha="def456",
        status="sealed",
    )
    execution = {
        "commit_shas": ["def456"],
        "changed_files": ["src/a.py"],
        "validation_results": ["ruff: 0"],
    }
    bundle = build_review_bundle(lane, execution_result=execution, objective="Fix seam")

    assert bundle.lane_id == "lane-1"
    assert bundle.head_sha == "def456"
    assert "src/a.py" in bundle.changed_files
    assert len(bundle.bundle_sha256) == 64


def test_bundle_hash_stable():
    lane = RalphLane(
        lane_id="lane-1", branch_name="ralph/test", base_head="abc", status="sealed"
    )
    b1 = build_review_bundle(lane, objective="test")
    b2 = build_review_bundle(lane, objective="test")
    assert b1.compute_sha256() == b2.compute_sha256()


def test_review_projection_from_bundles():
    lane = RalphLane(
        lane_id="lane-1", branch_name="ralph/test", base_head="abc", status="sealed"
    )
    bundle = build_review_bundle(lane, objective="test")
    proj = build_review_projection([bundle])

    assert proj.pending_lane_count == 1
    assert proj.execution_enabled is False
    assert proj.merge_enabled is False
    assert len(proj.available_actions) == 3


def test_bundle_includes_evidence_refs():
    lane = RalphLane(
        lane_id="lane-1", branch_name="ralph/test", base_head="abc", status="sealed"
    )
    bundle = build_review_bundle(lane, source_findings=["finding-1", "finding-2"])
    assert len(bundle.evidence_refs) == 2
    assert bundle.evidence_refs[0]["kind"] == "finding"
