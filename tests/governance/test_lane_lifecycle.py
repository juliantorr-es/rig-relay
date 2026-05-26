"""Tests for lane and promotion lifecycle authority.

Tests valid transitions, invalid transition refusal, duplicate event
idempotency, conflicting terminal states, corrupt event/chain refusal,
stale base/evidence-reference mismatch, ready-without-proof refusal,
promoted-without-acceptance refusal, consumed-without-promotion refusal,
parked-lane preservation, and schema validation against real emitted events.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.governance.lane_lifecycle import (
    LaneLifecycleEventKind,
    LaneLifecycleState,
    LaneTransitionOutcome,
    TERMINAL_STATES,
    _ledger_path,
    _store_root,
    current_state,
    transition_lane,
)

LANE = "lane-test-001"


def _clean_store():
    root = _store_root()
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _claim(lane_id=LANE):
    _clean_store()
    result = transition_lane(lane_id, LaneLifecycleEventKind.LANE_CLAIMED)
    assert result.succeeded, f"CLAIM failed: {result.error_detail}"
    return result


# ── Valid transitions ────────────────────────────────────────────────────────


def test_claim_creates_first_event():
    _clean_store()
    result = transition_lane(LANE, LaneLifecycleEventKind.LANE_CLAIMED)
    assert result.succeeded
    assert current_state(LANE) == LaneLifecycleState.CLAIMED


def test_claimed_to_ready_requested():
    _claim()
    result = transition_lane(
        LANE,
        LaneLifecycleEventKind.READY_REQUESTED,
        proof_bundle_sha256="sha256:deadbeef",
    )
    assert result.succeeded


def test_ready_to_validated():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    result = transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    assert result.succeeded
    assert current_state(LANE) == LaneLifecycleState.VALIDATED


def test_validated_to_accepted():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    result = transition_lane(LANE, LaneLifecycleEventKind.ACCEPTED)
    assert result.succeeded


def test_accepted_to_promoted():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    transition_lane(LANE, LaneLifecycleEventKind.ACCEPTED)
    result = transition_lane(LANE, LaneLifecycleEventKind.PROMOTED)
    assert result.succeeded
    assert current_state(LANE) == LaneLifecycleState.PROMOTED


def test_promoted_to_consumed():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    transition_lane(LANE, LaneLifecycleEventKind.ACCEPTED)
    transition_lane(LANE, LaneLifecycleEventKind.PROMOTED)
    result = transition_lane(LANE, LaneLifecycleEventKind.CONSUMED)
    assert result.succeeded
    assert current_state(LANE) == LaneLifecycleState.CONSUMED


def test_claimed_to_parked():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.PARKED)
    assert result.succeeded
    assert current_state(LANE) == LaneLifecycleState.PARKED


def test_claimed_to_failed():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.FAILED)
    assert result.succeeded


# ── Invalid transitions ──────────────────────────────────────────────────────


def test_first_event_must_be_claimed():
    _clean_store()
    result = transition_lane(LANE, LaneLifecycleEventKind.READY_REQUESTED)
    assert not result.succeeded
    assert result.outcome == LaneTransitionOutcome.INVALID_TRANSITION


def test_claimed_to_accepted_invalid():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.ACCEPTED)
    assert not result.succeeded
    assert result.outcome == LaneTransitionOutcome.INVALID_TRANSITION


def test_claimed_to_promoted_invalid():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.PROMOTED)
    assert not result.succeeded


def test_claimed_to_consumed_invalid():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.CONSUMED)
    assert not result.succeeded


# ── Terminal states block further transitions ──────────────────────────────


def test_consumed_refuses_transition():
    _claim()
    for kind in [
        LaneLifecycleEventKind.READY_REQUESTED,
        LaneLifecycleEventKind.VALIDATION_PASSED,
        LaneLifecycleEventKind.ACCEPTED,
        LaneLifecycleEventKind.PROMOTED,
        LaneLifecycleEventKind.CONSUMED,
    ]:
        transition_lane(LANE, kind, proof_bundle_sha256="sha256:proof")
    result = transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    assert result.outcome == LaneTransitionOutcome.ALREADY_TERMINAL


def test_refused_blocks_transitions():
    _claim()
    transition_lane(LANE, LaneLifecycleEventKind.REFUSED)
    result = transition_lane(LANE, LaneLifecycleEventKind.READY_REQUESTED)
    assert result.outcome == LaneTransitionOutcome.ALREADY_TERMINAL


def test_failed_blocks_transitions():
    _claim()
    transition_lane(LANE, LaneLifecycleEventKind.FAILED)
    result = transition_lane(LANE, LaneLifecycleEventKind.READY_REQUESTED)
    assert result.outcome == LaneTransitionOutcome.ALREADY_TERMINAL


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_duplicate_claimed_is_idempotent():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.LANE_CLAIMED)
    assert result.outcome == LaneTransitionOutcome.DUPLICATE_ALREADY_CURRENT


# ── Evidence requirements ────────────────────────────────────────────────────


def test_ready_without_proof_refused():
    _claim()
    result = transition_lane(LANE, LaneLifecycleEventKind.READY_REQUESTED)
    assert result.outcome == LaneTransitionOutcome.MISSING_REQUIRED_EVIDENCE


# ── Promotion/consumption gate checks ────────────────────────────────────────


def test_promoted_without_acceptance_refused():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    # Skip ACCEPTED, go directly to PROMOTED
    result = transition_lane(LANE, LaneLifecycleEventKind.PROMOTED)
    assert result.outcome == LaneTransitionOutcome.PROMOTED_WITHOUT_ACCEPTANCE


def test_consumed_without_promotion_refused():
    _claim()
    transition_lane(
        LANE, LaneLifecycleEventKind.READY_REQUESTED, proof_bundle_sha256="sha256:proof"
    )
    transition_lane(LANE, LaneLifecycleEventKind.VALIDATION_PASSED)
    transition_lane(LANE, LaneLifecycleEventKind.ACCEPTED)
    # Skip PROMOTED, go directly to CONSUMED
    result = transition_lane(LANE, LaneLifecycleEventKind.CONSUMED)
    assert result.outcome == LaneTransitionOutcome.CONSUMED_WITHOUT_PROMOTION


# ── Parked lane preservation ─────────────────────────────────────────────────


def test_parked_to_claimed_refused():
    _claim()
    transition_lane(LANE, LaneLifecycleEventKind.PARKED)
    result = transition_lane(LANE, LaneLifecycleEventKind.READY_REQUESTED)
    assert result.outcome == LaneTransitionOutcome.PARKED_LANE_PRESERVED


# ── Stale base check ─────────────────────────────────────────────────────────


def test_stale_base_refuses_transition():
    _clean_store()
    result = transition_lane(
        LANE, LaneLifecycleEventKind.LANE_CLAIMED, base_revision="sha256:original_base"
    )
    assert result.succeeded
    result = transition_lane(
        LANE,
        LaneLifecycleEventKind.READY_REQUESTED,
        proof_bundle_sha256="sha256:proof",
        base_revision="sha256:different",
    )
    assert result.outcome == LaneTransitionOutcome.STALE_BASE


# ── Terminal states are canonical ────────────────────────────────────────────


def test_terminal_states_cover_expected():
    assert LaneLifecycleState.CONSUMED.value in TERMINAL_STATES
    assert LaneLifecycleState.REFUSED.value in TERMINAL_STATES
    assert LaneLifecycleState.FAILED.value in TERMINAL_STATES
    assert LaneLifecycleState.PARKED.value in TERMINAL_STATES
    assert LaneLifecycleState.CLAIMED.value not in TERMINAL_STATES


# ── current_state on empty lane returns None ─────────────────────────────────


def test_current_state_none_on_empty_lane():
    _clean_store()
    assert current_state("nonexistent-lane") is None


# ── Schema validation against real emitted events ────────────────────────────


def test_emitted_event_validates_against_schema():
    """Real emitted events must conform to the canonical lane lifecycle schema."""
    import json
    import jsonschema

    import os

    schema_path = (
        Path(os.path.dirname(__file__)).parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.lane_lifecycle_event.v1.schema.json"
    )
    assert schema_path.exists(), f"Lane lifecycle schema missing at {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    _clean_store()
    result = transition_lane(
        "lane-schema-test",
        LaneLifecycleEventKind.LANE_CLAIMED,
        base_revision="sha256:base",
    )
    assert result.succeeded

    # Read event directly from the ledger
    ledger = _ledger_path("lane-schema-test")
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event_dict = json.loads(lines[0])
    jsonschema.validate(instance=event_dict, schema=schema)


def test_readiness_event_without_proof_rejected_by_schema():
    """Schema enforces proof_bundle_sha256 requirement on ready_requested."""
    import json
    import jsonschema

    import os

    schema_path = (
        Path(os.path.dirname(__file__)).parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.lane_lifecycle_event.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    from rig_relay.governance.lane_lifecycle import LaneLifecycleEvent

    event = LaneLifecycleEvent(
        event_kind=LaneLifecycleEventKind.READY_REQUESTED,
        lane_id="test",
        proof_bundle_sha256=None,
    )
    event.seal()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=json.loads(event.model_dump_json()), schema=schema)


def test_corrupt_ledger_line_refused():
    """A corrupt line in the ledger must cause _load_events to return None."""
    _clean_store()
    result = transition_lane("lane-c", LaneLifecycleEventKind.LANE_CLAIMED)
    assert result.succeeded

    ledger = _ledger_path("lane-c")
    with open(ledger, "a") as f:
        f.write("not json at all\n")
    # Verify the corrupt state prevents transitions
    result2 = transition_lane(
        "lane-c",
        LaneLifecycleEventKind.READY_REQUESTED,
        proof_bundle_sha256="sha256:proof",
    )
    assert not result2.succeeded
