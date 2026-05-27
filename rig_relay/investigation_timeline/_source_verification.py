from __future__ import annotations

import hashlib
import json

from rig_relay.investigation_timeline._models import SourceDomain, VerificationClass


def _compact_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def verify_observability_event(
    record: dict, computed_digest: str
) -> tuple[VerificationClass, str | None, bool]:
    event_hash = record.get("event_hash", "")
    if not event_hash or not event_hash.startswith("sha256:"):
        return VerificationClass.PARSED_UNVERIFIED, event_hash or None, False
    envelope_for_hash = {k: v for k, v in record.items() if k != "event_hash"}
    try:
        recalculated = (
            "sha256:"
            + hashlib.sha256(
                _compact_json(envelope_for_hash).encode("utf-8")
            ).hexdigest()
        )
    except Exception:
        return VerificationClass.PARSED_UNVERIFIED, event_hash, False
    if recalculated == event_hash:
        return VerificationClass.VERIFIED_CANONICAL, event_hash, True
    return VerificationClass.CORRUPT, event_hash, False


def verify_coordination_event(
    record: dict, computed_digest: str
) -> tuple[VerificationClass, str | None, bool]:
    event_hash = record.get("event_hash", "")
    if not event_hash or not event_hash.startswith("sha256:"):
        return VerificationClass.PARSED_UNVERIFIED, event_hash or None, False
    payload = record.get("payload", {})
    if not payload:
        return VerificationClass.PARSED_UNVERIFIED, event_hash, False
    try:
        recalculated = (
            "sha256:"
            + hashlib.sha256(
                _compact_json(_compact_json(payload)).encode("utf-8")
            ).hexdigest()
        )
    except Exception:
        return VerificationClass.PARSED_UNVERIFIED, event_hash, False
    if recalculated == event_hash:
        return VerificationClass.VERIFIED_CANONICAL, event_hash, True
    return VerificationClass.PARSED_UNVERIFIED, event_hash, False


def verify_disclosure_event(record: dict) -> tuple[VerificationClass, str | None, bool]:
    transition_digest = record.get("transition_digest", "")
    if not transition_digest or not transition_digest.startswith("sha256:"):
        return VerificationClass.PARSED_UNVERIFIED, transition_digest or None, False
    if record.get("status") in {"corrupt", "recovery_required"}:
        return VerificationClass.CANONICAL_DEGRADED, transition_digest, False
    try:
        recalculated = _compute_disclosure_digest(record)
    except Exception:
        return VerificationClass.PARSED_UNVERIFIED, transition_digest, False
    if recalculated == transition_digest:
        return VerificationClass.VERIFIED_CANONICAL, transition_digest, True
    return VerificationClass.PARSED_UNVERIFIED, transition_digest, False


def _compute_disclosure_digest(record: dict) -> str:
    digest_fields = {
        "schema_version",
        "transition_id",
        "authorization_id",
        "evidence_digest",
        "projection_id",
        "disclosure_class",
        "selector_digest",
        "selector_required_class",
        "manifest_digest_before",
        "manifest_digest_after",
        "retention_assertion",
        "training_use_assertion",
        "compilation_receipt_sha256",
        "receipt_approved_at",
        "disclosure_event_created_at",
        "consumed_auth_receipt_digest",
        "status",
        "parent_transition_digest",
        "downstream_event_id",
        "downstream_receipt_digest",
        "sequence",
    }
    payload = {k: record.get(k) for k in digest_fields if k in record}
    payload["transition_digest"] = ""
    canonical = _compact_json(payload)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_publication_event(
    record: dict,
) -> tuple[VerificationClass, str | None, bool]:
    event_digest = record.get("event_digest", "")
    if not event_digest or not event_digest.startswith("sha256:"):
        return VerificationClass.PARSED_UNVERIFIED, event_digest or None, False
    try:
        recalculated = _compute_publication_envelope_digest(record)
    except Exception:
        return VerificationClass.PARSED_UNVERIFIED, event_digest, False
    if recalculated == event_digest:
        return VerificationClass.VERIFIED_CANONICAL, event_digest, True
    return VerificationClass.PARSED_UNVERIFIED, event_digest, False


def _compute_publication_envelope_digest(event: dict) -> str:
    envelope_for_hash = {k: v for k, v in event.items() if k != "event_digest"}
    canonical = _compact_json(envelope_for_hash)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_checkpoint_event(record: dict) -> tuple[VerificationClass, str | None, bool]:
    event_hash = record.get("event_hash", "")
    if not event_hash or not event_hash.startswith("sha256:"):
        return VerificationClass.PARSED_UNVERIFIED, event_hash or None, False
    envelope_for_hash = {k: v for k, v in record.items() if k != "event_hash"}
    try:
        recalculated = (
            "sha256:"
            + hashlib.sha256(
                _compact_json(envelope_for_hash).encode("utf-8")
            ).hexdigest()
        )
    except Exception:
        return VerificationClass.PARSED_UNVERIFIED, event_hash, False
    if recalculated == event_hash:
        return VerificationClass.VERIFIED_CANONICAL, event_hash, True
    return VerificationClass.PARSED_UNVERIFIED, event_hash, False


DOMAIN_VERIFIERS: dict[SourceDomain, object] = {}
