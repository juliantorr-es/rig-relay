from __future__ import annotations

import hashlib
import json

from rig_relay.investigation_timeline._models import VerificationClass
from rig_relay.investigation_timeline._source_verification import (
    verify_checkpoint_event,
    verify_coordination_event,
    verify_disclosure_event,
    verify_observability_event,
    verify_publication_event,
)


def _compact(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(obj: object) -> str:
    return "sha256:" + hashlib.sha256(_compact(obj).encode("utf-8")).hexdigest()


def _wrong_digest() -> str:
    return "sha256:" + ("00" * 32)


def test_verify_observability_corrupt_on_mismatch():
    record = {
        "event_name": "rig.relay.session.started",
        "event_id": "evt_001",
        "session_id": "s-abc",
        "created_at": "2025-01-15T10:00:00Z",
        "payload": {"status": "success"},
        "event_hash": _wrong_digest(),
    }
    computed_digest = _digest(record)
    vc, _, verified = verify_observability_event(record, computed_digest)
    assert vc == VerificationClass.CORRUPT
    assert verified is False


def test_verify_coordination_corrupt_on_mismatch():
    record = {
        "event_name": "coord.session.registered",
        "event_id": "evt_001",
        "session_id": "s-abc",
        "created_at": "2025-01-15T10:00:00Z",
        "payload": {"status": "registered", "outcome": "registered"},
        "event_hash": _wrong_digest(),
    }
    computed_digest = _digest(record)
    vc, _, verified = verify_coordination_event(record, computed_digest)
    assert vc == VerificationClass.CORRUPT
    assert verified is False


def test_verify_disclosure_corrupt_on_mismatch():
    record = {
        "transition_id": "dt_001",
        "status": "prepared",
        "created_at": "2025-01-15T10:00:00Z",
        "authorization_id": "auth_001",
        "schema_version": "rig.relay.disclosure_transition.v1",
        "evidence_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "projection_id": "proj_001",
        "disclosure_class": "standard",
        "sequence": 1,
        "transition_digest": _wrong_digest(),
    }
    vc, _, verified = verify_disclosure_event(record)
    assert vc == VerificationClass.CORRUPT
    assert verified is False


def test_verify_publication_corrupt_on_mismatch():
    record = {
        "schema_version": "rig.relay.publication_preview_event.v1",
        "receipt": {
            "schema_version": "rig.relay.publication_preview_receipt.v1",
            "receipt_id": "sha256:aaa111",
            "compiled_at": "2026-05-01T10:00:00Z",
            "compilation_successful": True,
            "safety_passed": True,
            "deployment_ready": False,
            "preview_only": True,
        },
        "event_digest": _wrong_digest(),
    }
    vc, _, verified = verify_publication_event(record)
    assert vc == VerificationClass.CORRUPT
    assert verified is False


def test_verify_checkpoint_corrupt_on_mismatch():
    record = {
        "event_name": "rig.relay.checkpoint.committed",
        "event_id": "evt_001",
        "session_id": "s-abc",
        "created_at": "2025-01-15T10:00:00Z",
        "payload": {
            "session_id": "s-abc",
            "commit_sha": "abc1234",
            "status": "committed",
        },
        "event_hash": _wrong_digest(),
    }
    vc, _, verified = verify_checkpoint_event(record)
    assert vc == VerificationClass.CORRUPT
    assert verified is False


def test_verify_observability_unverified_when_no_hash():
    record = {
        "event_name": "rig.relay.session.started",
        "event_id": "evt_001",
        "session_id": "s-abc",
        "created_at": "2025-01-15T10:00:00Z",
        "payload": {"status": "success"},
    }
    computed_digest = _digest(record)
    vc, _, verified = verify_observability_event(record, computed_digest)
    assert vc == VerificationClass.PARSED_UNVERIFIED
    assert verified is False


def test_verify_coordination_single_encoding_matches():
    payload = {"status": "registered", "outcome": "registered"}
    event_hash = _digest(payload)
    record = {
        "event_name": "coord.session.registered",
        "event_id": "evt_001",
        "session_id": "s-abc",
        "created_at": "2025-01-15T10:00:00Z",
        "payload": payload,
        "event_hash": event_hash,
    }
    computed_digest = _digest(record)
    vc, producer_digest, verified = verify_coordination_event(record, computed_digest)
    assert vc == VerificationClass.VERIFIED_CANONICAL
    assert verified is True
    assert producer_digest == event_hash
