"""Tests for generic disclosure authorization authority.

Tests: issue, validate, consume, expire, replay refusal, evidence mismatch,
unsupported class refusal, corrupt receipt refusal, bounded-use consumption.
"""

from __future__ import annotations

from rig_relay.governance.disclosure_authorization import (
    RESTRICTED_DISCLOSURE_CLASSES,
    DisclosureAuthorizationReceipt,
    DisclosureClass,
    DisclosureOutcome,
    _receipt_path,
    _store_root,
    consume_disclosure_authorization,
    issue_disclosure_authorization,
    validate_disclosure_authorization,
)

EVIDENCE_DIGEST = (
    "sha256:aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
)
OTHER_DIGEST = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"


def _clean_store():
    root = _store_root()
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _issue_and_return_id(disclosure_class=None, **kwargs):
    _clean_store()
    if disclosure_class is None:
        disclosure_class = DisclosureClass.PATH_IDENTITY.value
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=disclosure_class,
        actor_identity="test-actor",
        purpose="testing",
        **kwargs,
    )
    assert result.outcome == DisclosureOutcome.ISSUED
    assert result.receipt is not None
    return result.receipt.authorization_id, result.receipt


# ── Issue authorization ──────────────────────────────────────────────────────


def test_issue_valid_disclosure():
    _clean_store()
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
        actor_identity="test-actor",
        purpose="testing",
    )
    assert result.outcome == DisclosureOutcome.ISSUED
    assert result.receipt is not None
    assert result.receipt.verify_integrity()
    assert result.receipt.disclosure_class == "path_identity"
    assert result.receipt.evidence_digest == EVIDENCE_DIGEST


def test_issue_unsupported_class_refused():
    _clean_store()
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST, disclosure_class="nonexistent_class"
    )
    assert result.outcome == DisclosureOutcome.UNSUPPORTED_CLASS


def test_issue_persists_receipt():
    _clean_store()
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
    )
    assert result.receipt is not None
    path = _receipt_path(result.receipt.authorization_id)
    assert path.exists()


# ── Validate authorization ────────────────────────────────────────────────────


def test_validate_fresh_receipt():
    auth_id, receipt = _issue_and_return_id(
        disclosure_class=DisclosureClass.BRANCH_IDENTITY.value, ttl_minutes=60
    )
    valid = validate_disclosure_authorization(
        auth_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert valid.outcome == DisclosureOutcome.VALID
    assert valid.is_authorized


def test_validate_evidence_mismatch_refused():
    auth_id, receipt = _issue_and_return_id(
        disclosure_class=DisclosureClass.COMMIT_SUBJECT.value
    )
    valid = validate_disclosure_authorization(
        auth_id, current_evidence_digest=OTHER_DIGEST
    )
    assert valid.outcome == DisclosureOutcome.EVIDENCE_MISMATCH
    assert not valid.is_authorized


def test_validate_without_evidence_digest_passes():
    auth_id, receipt = _issue_and_return_id(
        disclosure_class=DisclosureClass.METADATA_DISCLOSURE.value
    )
    valid = validate_disclosure_authorization(auth_id)
    assert valid.outcome == DisclosureOutcome.VALID


def test_validate_not_found():
    _clean_store()
    valid = validate_disclosure_authorization("nonexistent-id")
    assert valid.outcome == DisclosureOutcome.NOT_FOUND


# ── Consume authorization ────────────────────────────────────────────────────


def test_consume_one_time_receipt():
    auth_id, receipt = _issue_and_return_id(one_time=True)
    consumed = consume_disclosure_authorization(
        auth_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert consumed.outcome == DisclosureOutcome.CONSUMED
    assert consumed.receipt is not None
    assert consumed.receipt.consumed is True

    # Replay should refuse
    replay = validate_disclosure_authorization(auth_id)
    assert replay.outcome == DisclosureOutcome.ALREADY_CONSUMED


def test_consume_replay_refused():
    auth_id, receipt = _issue_and_return_id(one_time=True)
    c1 = consume_disclosure_authorization(
        auth_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert c1.outcome == DisclosureOutcome.CONSUMED

    c2 = consume_disclosure_authorization(
        auth_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert c2.outcome == DisclosureOutcome.ALREADY_CONSUMED


# ── Corrupt receipt refusal ──────────────────────────────────────────────────


def test_corrupt_receipt_refused():
    _clean_store()
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
    )
    assert result.receipt is not None
    auth_id = result.receipt.authorization_id

    # Tamper with the receipt file
    import json

    path = _receipt_path(auth_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["evidence_digest"] = OTHER_DIGEST
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    valid = validate_disclosure_authorization(auth_id)
    assert valid.outcome == DisclosureOutcome.CORRUPT


# ── Disclosure classes and policy ────────────────────────────────────────────


def test_disclosure_class_enum_covers_all():
    assert DisclosureClass.PATH_IDENTITY.value == "path_identity"
    assert DisclosureClass.PATH_INVENTORY.value == "path_inventory"
    assert DisclosureClass.BRANCH_IDENTITY.value == "branch_identity"
    assert DisclosureClass.BRANCH_ENUMERATION.value == "branch_enumeration"
    assert DisclosureClass.COMMIT_SUBJECT.value == "commit_subject"
    assert DisclosureClass.COMMIT_BODY.value == "commit_body"
    assert DisclosureClass.COMMIT_PATCH.value == "commit_patch"
    assert DisclosureClass.METADATA_DISCLOSURE.value == "metadata_disclosure"
    assert DisclosureClass.RAW_CONTENT.value == "raw_content"


def test_restricted_classes_are_identifiable():
    assert "raw_content" in RESTRICTED_DISCLOSURE_CLASSES
    assert "commit_patch" in RESTRICTED_DISCLOSURE_CLASSES
    assert "path_identity" not in RESTRICTED_DISCLOSURE_CLASSES


# ── Receipt model integrity ──────────────────────────────────────────────────


def test_receipt_model_integrity():
    receipt = DisclosureAuthorizationReceipt(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class="path_identity",
        actor_identity="test",
    )
    receipt.seal()
    assert receipt.verify_integrity()


def test_receipt_model_tampered():
    receipt = DisclosureAuthorizationReceipt(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class="path_identity",
        actor_identity="test",
    )
    receipt.seal()
    receipt.evidence_digest = OTHER_DIGEST
    assert not receipt.verify_integrity()


# ── Expiry ───────────────────────────────────────────────────────────────────


def test_validate_expired_receipt():
    _clean_store()
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.METADATA_DISCLOSURE.value,
        ttl_minutes=0,  # Expires immediately
    )
    assert result.receipt is not None
    auth_id = result.receipt.authorization_id

    valid = validate_disclosure_authorization(auth_id)
    assert valid.outcome == DisclosureOutcome.EXPIRED
