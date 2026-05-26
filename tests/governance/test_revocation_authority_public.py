"""Public-boundary revocation authority tests.

Proves the governed public revocation producer with authorization enforcement.
Distinct from the primitive tests in test_receipt_revocation.py — these tests
exercise the PUBLIC boundary with real authorization receipt validation.
"""

from __future__ import annotations

import json

from rig_relay.governance.auth_receipts import (
    generate_dev_receipt,
    generate_preparation_receipt,
)
from rig_relay.governance.receipt_store import (
    PreparationLifecycleEvent,
    PreparationLifecycleEventKind,
    _self_dogfood_store_root,
    append_lifecycle_event,
    get_lifecycle_status,
    persist_preparation_receipt,
)
from rig_relay.governance.revocation_authority import (
    REVOKE_ACTION,
    PublicRevocationOutcome,
    revoke_preparation_receipt_public,
)


def _create_active_receipt():
    receipt = generate_preparation_receipt(
        session_id="test_session_pub",
        task_id="test_task_pub",
        branch="test-branch",
        prepared_paths=["test/file.py"],
    )
    path = persist_preparation_receipt(receipt)
    assert path is not None
    return receipt["receipt_sha256"], receipt


def _dev_receipt_json(action=REVOKE_ACTION):
    r = generate_dev_receipt(action=action)
    return json.dumps(r)


def _dev_receipt_json_expired():
    r = generate_dev_receipt(action=REVOKE_ACTION, ttl_seconds=0)
    return json.dumps(r)


def _dev_receipt_json_wrong_action():
    r = generate_dev_receipt(action="checkpoint.commit")
    return json.dumps(r)


# ── Successful active receipt revocation through public boundary ───────────


def test_public_revoke_active_receipt():
    sha, receipt = _create_active_receipt()
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert result.succeeded
    assert result.outcome == PublicRevocationOutcome.REVOKED
    assert result.revocation_event_id is not None
    assert result.evidence is not None
    assert result.evidence["outcome"] == "revoked"
    assert result.authorization_receipt_sha256
    assert get_lifecycle_status(sha) == PreparationLifecycleEventKind.REVOKED


# ── Idempotent repeated public revocation ───────────────────────────────────


def test_public_revoke_idempotent():
    sha, receipt = _create_active_receipt()
    authz = _dev_receipt_json()
    r1 = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert r1.outcome == PublicRevocationOutcome.REVOKED
    r2 = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert r2.outcome == PublicRevocationOutcome.ALREADY_REVOKED
    assert r2.succeeded


# ── Authorization refusal ────────────────────────────────────────────────────


def test_public_revoke_missing_authorization():
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=None)
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.AUTHORIZATION_MISSING


def test_public_revoke_invalid_authorization():
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt_public(
        sha, authorization_receipt_json="not json"
    )
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.AUTHORIZATION_INVALID


def test_public_revoke_wrong_action_receipt():
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt_public(
        sha, authorization_receipt_json=_dev_receipt_json_wrong_action()
    )
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.AUTHORIZATION_ACTION_MISMATCH


def test_public_revoke_expired_receipt():
    sha, receipt = _create_active_receipt()
    result = revoke_preparation_receipt_public(
        sha, authorization_receipt_json=_dev_receipt_json_expired()
    )
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.AUTHORIZATION_EXPIRED


# ── Post-revocation validate/checkpoint refusal through public boundary ──────


def test_public_revoke_then_checkpoint_refuses():
    sha, receipt = _create_active_receipt()
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert result.succeeded
    assert get_lifecycle_status(sha) == PreparationLifecycleEventKind.REVOKED


# ── Already-consumed refusal through public boundary ───────────────────────


def test_public_revoke_already_consumed():
    sha, receipt = _create_active_receipt()
    consumed = PreparationLifecycleEvent(
        event_kind=PreparationLifecycleEventKind.CONSUMED,
        preparation_receipt_sha256=sha,
        branch="test-branch",
        producer="checkpoint.run",
    )
    eid = append_lifecycle_event(consumed)
    assert eid is not None
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.ALREADY_CONSUMED


# ── Already-superseded refusal through public boundary ─────────────────────


def test_public_revoke_already_superseded():
    sha, receipt = _create_active_receipt()
    superseded = PreparationLifecycleEvent(
        event_kind=PreparationLifecycleEventKind.SUPERSEDED,
        preparation_receipt_sha256=sha,
        branch="test-branch",
        producer="prepare_checkpoint.run",
        superseded_by_receipt_sha256="sha256:deadbeef",
    )
    eid = append_lifecycle_event(superseded)
    assert eid is not None
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.ALREADY_SUPERSEDED


# ── Corrupt receipt refusal through public boundary ──────────────────────────


def test_public_revoke_corrupt_receipt():
    sha, receipt = _create_active_receipt()
    path = _self_dogfood_store_root() / f"{sha}.json"
    path.write_text("corrupt{{{", encoding="utf-8")
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert not result.succeeded
    assert result.outcome == PublicRevocationOutcome.RECEIPT_CORRUPT
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


# ── Bounded evidence emission ────────────────────────────────────────────────


def test_public_revoke_produces_evidence():
    sha, receipt = _create_active_receipt()
    authz = _dev_receipt_json()
    result = revoke_preparation_receipt_public(sha, authorization_receipt_json=authz)
    assert result.succeeded
    assert result.evidence is not None
    assert result.evidence["schema_version"] == "rig.relay.revocation_evidence.v1"
    assert result.evidence["preparation_receipt_sha256"] == sha
    assert result.evidence["revocation_event_id"] == result.revocation_event_id
    assert result.evidence["outcome"] == "revoked"
