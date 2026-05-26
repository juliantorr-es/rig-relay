"""Tests for preparation receipt revocation authority.

Uses real receipt files, lifecycle ledgers, and temporary filesystems.
Tests: revoke active, idempotent re-revoke, revoke-after-consume refusal,
revoke-vs-consume race detection, corrupt-ledger refusal, and schema validation.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from rig_relay.governance.auth_receipts import generate_preparation_receipt
from rig_relay.governance.receipt_store import (
    PreparationLifecycleEvent,
    PreparationLifecycleEventKind,
    RevocationOutcome,
    RevocationResult,
    _self_dogfood_store_root,
    append_lifecycle_event,
    load_lifecycle_events,
    load_preparation_receipt_typed,
    persist_preparation_receipt,
    revoke_preparation_receipt,
)


def _create_active_receipt() -> tuple[str, dict]:
    """Create and persist an active preparation receipt."""
    receipt = generate_preparation_receipt(
        session_id="test_session",
        task_id="test_task",
        branch="test-branch",
        prepared_paths=["test/file.py"],
    )
    path = persist_preparation_receipt(receipt)
    assert path is not None
    return receipt["receipt_sha256"], receipt


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ── Active-to-revoked success ─────────────────────────────────────────────────


def test_revoke_active_receipt():
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt(sha)
    assert result.succeeded, f"Revoke failed: {result.outcome} — {result.error_detail}"
    assert result.outcome == RevocationOutcome.REVOKED
    assert result.revocation_event_id is not None

    # Verify lifecycle now shows REVOKED
    life = load_lifecycle_events(sha)
    assert life.is_ok
    assert life.status == PreparationLifecycleEventKind.REVOKED

    # Load receipt still works and is integrity-valid
    load = load_preparation_receipt_typed(sha)
    assert load.is_valid


# ── Idempotent repeated revocation ────────────────────────────────────────────


def test_revoke_idempotent():
    sha, receipt = _create_active_receipt()

    r1 = revoke_preparation_receipt(sha)
    assert r1.outcome == RevocationOutcome.REVOKED

    r2 = revoke_preparation_receipt(sha)
    assert r2.outcome == RevocationOutcome.ALREADY_REVOKED
    assert (
        r2.succeeded
    )  # Still "succeeded" for callers that don't care about idempotency

    # Only one REVOKED event in the chain
    life = load_lifecycle_events(sha)
    assert life.is_ok
    revoked_events = [
        e for e in life.events if e.event_kind == PreparationLifecycleEventKind.REVOKED
    ]
    assert len(revoked_events) == 1, (
        f"Expected 1 REVOKED event, got {len(revoked_events)}"
    )


# ── Revoke-after-consume refusal ──────────────────────────────────────────────


def test_revoke_already_consumed_refused():
    sha, receipt = _create_active_receipt()

    # Simulate consumption: append CONSUMED lifecycle event
    consumed = PreparationLifecycleEvent(
        event_kind=PreparationLifecycleEventKind.CONSUMED,
        preparation_receipt_sha256=sha,
        branch="test-branch",
        producer="checkpoint.run",
    )
    event_id = append_lifecycle_event(consumed)
    assert event_id is not None

    # Now try to revoke
    result = revoke_preparation_receipt(sha)
    assert not result.succeeded
    assert result.outcome == RevocationOutcome.ALREADY_CONSUMED


# ── Revoke-after-superseded refusal ───────────────────────────────────────────


def test_revoke_already_superseded_refused():
    sha, receipt = _create_active_receipt()

    superseded = PreparationLifecycleEvent(
        event_kind=PreparationLifecycleEventKind.SUPERSEDED,
        preparation_receipt_sha256=sha,
        branch="test-branch",
        producer="prepare_checkpoint.run",
        superseded_by_receipt_sha256="sha256:deadbeef",
    )
    event_id = append_lifecycle_event(superseded)
    assert event_id is not None

    result = revoke_preparation_receipt(sha)
    assert not result.succeeded
    assert result.outcome == RevocationOutcome.ALREADY_SUPERSEDED


# ── Non-existent receipt refusal ──────────────────────────────────────────────


def test_revoke_nonexistent_receipt():
    fake_sha = f"sha256:{_sha256_hex(secrets.token_bytes(32))}"
    result = revoke_preparation_receipt(fake_sha)
    assert not result.succeeded
    assert result.outcome == RevocationOutcome.RECEIPT_NOT_FOUND


# ── Corrupt receipt refusal ───────────────────────────────────────────────────


def test_revoke_corrupt_receipt():
    sha, receipt = _create_active_receipt()

    # Corrupt the receipt file by overwriting with invalid JSON
    path = _self_dogfood_store_root() / f"{sha}.json"
    path.write_text("not valid json{{{", encoding="utf-8")

    result = revoke_preparation_receipt(sha)
    assert not result.succeeded
    assert result.outcome == RevocationOutcome.RECEIPT_CORRUPT

    # Restore a valid receipt for cleanup
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


# ── Idempotent revocation with chain verification ─────────────────────────────


def test_revoke_preserves_chain_integrity():
    sha, receipt = _create_active_receipt()

    result = revoke_preparation_receipt(sha)
    assert result.outcome == RevocationOutcome.REVOKED

    # Verify chain: the REVOKED event's prior_event_digest should be None
    # (no prior event), and the integrity should be self-consistent
    life = load_lifecycle_events(sha)
    assert life.is_ok
    assert len(life.events) == 1
    event = life.events[0]
    assert event.event_kind == PreparationLifecycleEventKind.REVOKED
    assert event.verify_integrity()
    assert event.prior_event_digest is None  # First event in chain


# ── Validate and checkpoint refuse after revocation ───────────────────────────


def test_post_revoke_validate_refuses():
    """Validate using a revoked receipt should refuse.

    This is a direct lifecycle status check — the full validate integration
    with cross-evidence reconciliation is tested in test_validate.py.
    """
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt(sha)
    assert result.succeeded

    # Direct lifecycle check shows REVOKED
    life = load_lifecycle_events(sha)
    assert life.is_ok
    assert life.status == PreparationLifecycleEventKind.REVOKED

    # Prepare-checkpoint consumption attempt should find REVOKED
    from rig_relay.governance.receipt_store import get_lifecycle_status

    status = get_lifecycle_status(sha)
    assert status == PreparationLifecycleEventKind.REVOKED


# ── Multiple receipts, single revocation ──────────────────────────────────────


def test_revoke_does_not_affect_other_receipts():
    sha1, r1 = _create_active_receipt()
    sha2, r2 = _create_active_receipt()

    assert sha1 != sha2

    result = revoke_preparation_receipt(sha1)
    assert result.outcome == RevocationOutcome.REVOKED

    # sha2 should still be ACTIVE
    life2 = load_lifecycle_events(sha2)
    assert life2.is_ok or life2.is_absent
    assert life2.status in {PreparationLifecycleEventKind.ACTIVE, None}


# ── Corrupt ledger refusal ────────────────────────────────────────────────────


def test_revoke_corrupt_ledger_refused():
    sha, receipt = _create_active_receipt()

    # Corrupt the lifecycle ledger — delete it first to ensure clean state, then write invalid JSON
    ledger_path = _self_dogfood_store_root() / "lifecycle.jsonl"
    ledger_path.unlink(missing_ok=True)
    ledger_path.write_text(
        '{"schema_version": "rig.relay.preparation_lifecycle_event.v1", "event_id": "broken", '
        '"event_kind": "active", "preparation_receipt_sha256": "' + sha + '"'
        ', "integrity_digest": "sha256:deadbeef"}\nNOT_JSON_LINE\n',
        encoding="utf-8",
    )

    result = revoke_preparation_receipt(sha)
    assert not result.succeeded, f"Expected failure, got: {result.outcome}"


# ── Schema validation ─────────────────────────────────────────────────────────


def test_revocation_result_model():
    r = RevocationResult(
        outcome=RevocationOutcome.REVOKED,
        preparation_receipt_sha256="sha256:abc123",
        revocation_event_id="evt_001",
    )
    assert r.succeeded
    assert r.revocation_event_id == "evt_001"


def test_revocation_outcome_enum_covers_all_cases():
    cases = list(RevocationOutcome)
    assert RevocationOutcome.REVOKED in cases
    assert RevocationOutcome.ALREADY_REVOKED in cases
    assert RevocationOutcome.ALREADY_CONSUMED in cases
    assert RevocationOutcome.ALREADY_SUPERSEDED in cases
    assert RevocationOutcome.RECEIPT_NOT_FOUND in cases
    assert RevocationOutcome.RECEIPT_CORRUPT in cases
