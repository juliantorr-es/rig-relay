from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


from rig_relay.ralph.decision_events import (
    DecisionEvent,
    DecisionEventStore,
    DecisionReceipt,
)


def test_approval_event_created():
    event = DecisionEvent(
        event_kind="ralph.decision.approved",
        run_id="run-1",
        scan_id="scan-1",
        panel_sha256="a" * 64,
        mission_candidate_sha256="b" * 64,
        decision_action="approve_read_only_mission",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )

    assert event.event_kind == "ralph.decision.approved"
    assert event.execution_enabled is False
    assert event.run_id == "run-1"


def test_refusal_event_created():
    event = DecisionEvent(
        event_kind="ralph.decision.refused",
        run_id="run-1",
        decision_action="ralph_approve",
        status="refused",
        error_code="stale_panel_hash",
        execution_enabled=False,
    )

    assert event.status == "refused"
    assert event.error_code == "stale_panel_hash"


def test_decline_event_created():
    event = DecisionEvent(
        event_kind="ralph.decision.declined",
        run_id="run-1",
        scan_id="scan-1",
        panel_sha256="a" * 64,
        mission_candidate_sha256="b" * 64,
        decision_action="decline",
        approval_state_before="pending",
        approval_state_after="declined",
        status="completed",
        execution_enabled=False,
    )

    assert event.event_kind == "ralph.decision.declined"


def test_event_sha256_stable():
    event1 = DecisionEvent(
        event_id="fixed-id",
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )
    event2 = DecisionEvent(
        event_id="fixed-id",
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )

    assert event1.compute_sha256() == event2.compute_sha256()


def test_event_and_receipt_hashes_are_distinct():
    event = DecisionEvent(
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )
    event.event_sha256 = event.compute_sha256()

    receipt = DecisionReceipt(
        event_id=event.event_id,
        event_sha256=event.event_sha256,
        run_id=event.run_id,
        decision_action=event.decision_action,
        status=event.status,
        execution_enabled=False,
    )
    receipt.receipt_sha256 = receipt.compute_sha256()

    assert event.event_sha256 != receipt.receipt_sha256


def test_append_event_to_store(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = DecisionEventStore(root=root)

    event = DecisionEvent(
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )

    result = store.append_event(event)
    assert result.event_sha256 != ""
    assert result.event_sha256 == event.event_sha256


def test_create_receipt_from_event(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = DecisionEventStore(root=root)

    event = DecisionEvent(
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        approval_state_before="pending",
        approval_state_after="approved",
        status="completed",
        execution_enabled=False,
    )
    event = store.append_event(event)

    receipt = store.create_receipt(event)
    assert receipt.receipt_sha256 != ""
    assert receipt.event_sha256 == event.event_sha256
    assert receipt.execution_enabled is False


def test_event_ledger_grows(tmp_path):
    root = tmp_path / ".rig" / "ralph"
    store = DecisionEventStore(root=root)

    for i in range(3):
        store.append_event(
            DecisionEvent(
                event_kind="ralph.decision.approved",
                run_id=f"run-{i}",
                decision_action="approve",
                approval_state_before="pending",
                approval_state_after="approved",
                status="completed",
                execution_enabled=False,
            )
        )

    events = store.list_events()
    assert len(events) == 3


def test_execution_always_disabled_in_events():
    """Decision events: execution_enabled defaults to False."""
    event = DecisionEvent(
        event_kind="ralph.decision.approved",
        run_id="run-1",
        decision_action="approve",
        status="completed",
    )
    assert event.execution_enabled is False
