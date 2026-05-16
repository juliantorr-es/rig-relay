from __future__ import annotations

import pytest

from rig_relay.ralph.lane_events import LaneEvent, LaneEventStore, LaneReceipt

pytestmark = [pytest.mark.integration]


def test_proposed_event():
    event = LaneEvent(
        event_kind="ralph.lane.proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_after="proposed",
    )
    assert event.event_kind == "ralph.lane.proposed"
    assert event.execution_enabled is False
    assert event.merge_enabled is False


def test_seal_event():
    event = LaneEvent(
        event_kind="ralph.lane.sealed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_before="active",
        status_after="sealed",
        review_bundle_sha256="sha256:abc",
    )
    assert event.status_after == "sealed"


def test_adoption_proposed_event():
    event = LaneEvent(
        event_kind="ralph.lane.adoption_proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_before="sealed",
        status_after="adoption_proposed",
        adoption_proposal_id="adopt-1",
    )
    assert event.adoption_proposal_id == "adopt-1"


def test_event_sha256_stable():
    e1 = LaneEvent(
        event_id="fixed-id",
        event_kind="ralph.lane.proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_after="proposed",
    )
    e2 = LaneEvent(
        event_id="fixed-id",
        event_kind="ralph.lane.proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_after="proposed",
    )
    assert e1.compute_sha256() == e2.compute_sha256()


def test_event_and_receipt_hashes_differ():
    event = LaneEvent(
        event_kind="ralph.lane.proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_after="proposed",
    )
    event.event_sha256 = event.compute_sha256()

    receipt = LaneReceipt(
        event_id=event.event_id,
        event_sha256=event.event_sha256,
        lane_id=event.lane_id,
        mission_id=event.mission_id,
        event_kind=event.event_kind,
        status_after="proposed",
    )
    receipt.receipt_sha256 = receipt.compute_sha256()

    assert event.event_sha256 != receipt.receipt_sha256


def test_append_event_to_store(tmp_path):
    root = tmp_path / ".rig" / "ralph" / "lanes"
    store = LaneEventStore(root=root)

    event = LaneEvent(
        event_kind="ralph.lane.proposed",
        lane_id="lane-1",
        mission_id="mission-1",
        status_after="proposed",
    )
    store.append_event(event)

    receipt = store.create_receipt(event)
    assert receipt.receipt_sha256 != ""
    assert receipt.execution_enabled is False
    assert receipt.merge_enabled is False


def test_all_events_disabled():
    event = LaneEvent(
        event_kind="ralph.lane.adoption_approved",
        lane_id="lane-1",
        mission_id="mission-1",
    )
    assert event.execution_enabled is False
    assert event.merge_enabled is False
    assert event.push_enabled is False
