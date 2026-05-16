from __future__ import annotations

import pytest

from rig_relay.ralph.lane_contracts import RalphLane
from rig_relay.ralph.lane_store import (
    FilesystemRalphLaneStore,
    InMemoryRalphLaneStore,
    RalphLaneStore,
)

pytestmark = [pytest.mark.integration]

def test_lane_save_load_roundtrip():
    store = InMemoryRalphLaneStore()
    lane = RalphLane(
        lane_id="lane-1",
        branch_name="ralph/test-abc12345",
        worktree_path=".rig/worktrees/ralph/lane-1",
        status="proposed",
    )
    store.save_lane(lane)
    loaded = store.load_lane("lane-1")
    assert loaded is not None
    assert loaded.lane_id == "lane-1"
    assert loaded.branch_name == "ralph/test-abc12345"


def test_lane_list_by_status():
    store = InMemoryRalphLaneStore()
    store.save_lane(RalphLane(lane_id="l1", status="active"))
    store.save_lane(RalphLane(lane_id="l2", status="sealed"))
    store.save_lane(RalphLane(lane_id="l3", status="active"))

    active = store.list_lanes(status="active")
    assert len(active) == 2

    sealed = store.list_lanes(status="sealed")
    assert len(sealed) == 1


def test_lane_seal():
    store = InMemoryRalphLaneStore()
    lane = RalphLane(lane_id="lane-1", status="active")
    store.save_lane(lane)

    sealed = store.seal_lane("lane-1", "sha256:abc123")
    assert sealed is not None
    assert sealed.status == "sealed"
    assert sealed.review_bundle_sha256 == "sha256:abc123"
    assert sealed.sealed_at is not None


def test_lane_adoption_proposed():
    store = InMemoryRalphLaneStore()
    lane = RalphLane(lane_id="lane-1", status="sealed")
    store.save_lane(lane)

    updated = store.mark_adoption_proposed("lane-1", "adopt-1")
    assert updated is not None
    assert updated.status == "adoption_proposed"


def test_lane_expire():
    store = InMemoryRalphLaneStore()
    lane = RalphLane(lane_id="lane-1", status="active")
    store.save_lane(lane)

    store.expire_lane("lane-1", "test")
    loaded = store.load_lane("lane-1")
    assert loaded.status == "expired"


def test_lane_defaults_disabled():
    lane = RalphLane()
    assert lane.execution_enabled is False
    assert lane.merge_enabled is False
    assert lane.push_enabled is False
    assert lane.status == "proposed"


def test_branch_name_sanitization():
    lane = RalphLane()
    name = lane.sanitize_branch_name("Fix DirtyFileGuard singleton ownership across forked agents!!!", "abc12345")
    assert name.startswith("ralph/")
    assert "!!!" not in name
    assert "abc12345" in name


def test_worktree_path_does_not_escape():
    lane = RalphLane(worktree_path=".rig/worktrees/ralph/lane-1")
    assert lane.worktree_path.startswith(".rig/worktrees/ralph/")


def test_filesystem_save_load_roundtrip(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = FilesystemRalphLaneStore(root=root)

    lane = RalphLane(
        lane_id="fs-lane-1",
        branch_name="ralph/test-1",
        status="proposed",
    )
    store.save_lane(lane)

    loaded = store.load_lane("fs-lane-1")
    assert loaded is not None
    assert loaded.lane_id == "fs-lane-1"


def test_store_protocol():
    store = InMemoryRalphLaneStore()
    assert isinstance(store, RalphLaneStore)
