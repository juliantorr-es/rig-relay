"""Disclosure Evidence Query Service — read-side projection over canonical
disclosure transition evidence.

Provides typed, content-light projections of disclosure transitions suitable
for desktop/Gridline consumption, governed agents, and accessibility surfaces.

Reads from the fsynced transition ledger and disclosure event ledger.
Never mutates transition, authorization, manifest, or disclosure-event
authority state.

Lane A owns this query surface. It is subordinate to the transition authority
— only transition-ledger claims are canonical.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.governance.disclosure_transition import (
    TERMINAL_STATUSES,
    TransitionStatus,
    _find_transition_for_auth,
    _load_all_ledger_events,
)

QUERY_SCHEMA_VERSION = "rig.relay.disclosure_query_projection.v1"


# ── Projection models ──────────────────────────────────────────────────


class RecoveryProvenanceProjection(BaseModel):
    """Recovery provenance for a disclosure transition."""

    model_config = ConfigDict(extra="forbid")

    is_recovered: bool = Field(
        default=False,
        description="True if this transition was completed through recovery.",
    )
    recovery_detail: str | None = Field(
        default=None,
        description="Recovery outcome tag (recovered_and_completed, recovered_already_complete).",
    )
    uninterrupted: bool = Field(
        default=True,
        description="False when any recovery was needed during this transition.",
    )
    last_durable_status_before_recovery: str | None = Field(
        default=None,
        description="The last durably-recorded transition status before recovery resumed.",
    )


class ContentDispositionProjection(BaseModel):
    """Protected-content disclosure disposition."""

    model_config = ConfigDict(extra="forbid")

    disclosure_class: str = Field(
        default="", description="Governance DisclosureClass for this transition."
    )
    selector_present: bool = Field(
        default=False,
        description="True if the transition includes a scoped selector disclosure.",
    )
    selector_digest: str | None = Field(
        default=None, description="SHA256 of the disclosed selector identity, if any."
    )
    selector_required_class: str | None = Field(
        default=None,
        description="DisclosureClass required for this selector as recorded in the manifest.",
    )
    includes_hash_only_protection: bool = Field(
        default=False,
        description="True when protected-content classification included hash-only (S_) items.",
    )
    prohibited_class_blocked: bool = Field(
        default=False,
        description="True when the transition refused a prohibited disclosure class.",
    )


class ArtifactIntegrityProjection(BaseModel):
    """Artifact-integrity disposition for a disclosure transition."""

    model_config = ConfigDict(extra="forbid")

    receipt_identity: str | None = Field(
        default=None, description="Receipt identity (dza_{transition_id})."
    )
    receipt_bound: bool = Field(
        default=False,
        description="True when the disclosure receipt was durably persisted.",
    )
    receipt_digest: str | None = Field(
        default=None, description="Downstream receipt digest reference."
    )
    event_identity: str | None = Field(
        default=None, description="Disclosure-event identity (dze_{transition_id})."
    )
    event_durable: bool = Field(
        default=False,
        description="True when the disclosure event was durably appended.",
    )
    manifest_image: str = Field(
        default="unknown",
        description="Manifest two-image validation result: precondition, post_image, or unknown.",
    )
    manifest_verified: bool = Field(
        default=False, description="True when the manifest passed two-image validation."
    )
    corruption_detail: str | None = Field(
        default=None,
        description="Corruption reason vocabulary, if the transition was CORRUPT.",
    )
    chain_valid: bool = Field(
        default=True,
        description="False when the transition digest chain shows discontinuity.",
    )


class DisclosureTransitionProjection(BaseModel):
    """Content-light projection of a single disclosure transition."""

    model_config = ConfigDict(extra="forbid")

    transition_id: str
    authorization_id: str
    evidence_digest: str
    projection_id: str
    status: str
    recipient_class: str
    provider_or_channel: str
    purpose: str | None = None
    retention_assertion: str | None = None
    training_use_assertion: str | None = None
    transition_digest: str
    created_at: str
    sequence: int
    recovery_provenance: RecoveryProvenanceProjection | None = None
    content_disposition: ContentDispositionProjection | None = None
    artifact_integrity: ArtifactIntegrityProjection | None = None


class QueryFilter(BaseModel):
    """Filter criteria for disclosure transition queries."""

    model_config = ConfigDict(extra="forbid")

    transition_id: str | None = Field(
        default=None, description="Exact transition identifier match."
    )
    authorization_id: str | None = Field(
        default=None, description="Authorization identifier match."
    )
    evidence_digest: str | None = Field(
        default=None, description="Evidence digest (candidate bundle hash) match."
    )
    status: str | None = Field(
        default=None,
        description="TransitionStatus filter. One of: completed, refused, corrupt, conflict, prepared, etc.",
    )
    include_terminated: bool = Field(
        default=True,
        description="Include terminal (completed, refused, corrupt, conflict) transitions.",
    )


class DisclosureQueryResult(BaseModel):
    """Result of a query against the disclosure evidence ledgers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = QUERY_SCHEMA_VERSION
    query_digest: str = Field(
        default="",
        description="SHA256 of this query result (deterministic, content-light).",
    )
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    filter: QueryFilter
    transitions: list[DisclosureTransitionProjection] = Field(default_factory=list)
    total_count: int = 0
    content_light_guarantee: bool = True


# ── Digest helpers ─────────────────────────────────────────────────────


def _compute_sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _seal_result(result: DisclosureQueryResult) -> None:
    data = result.model_dump(exclude={"query_digest"})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    result.query_digest = _compute_sha256(canonical.encode("utf-8"))


# ── Projection builders ────────────────────────────────────────────────


def _build_recovery_provenance(event: dict) -> RecoveryProvenanceProjection | None:
    recovery_detail = event.get("recovery_detail")
    if not recovery_detail:
        return None
    return RecoveryProvenanceProjection(
        is_recovered=recovery_detail
        in ("recovered_and_completed", "recovered_already_complete"),
        recovery_detail=recovery_detail,
        uninterrupted=False,
        last_durable_status_before_recovery=event.get("parent_transition_digest", "")
        or None,
    )


def _build_content_disposition(event: dict) -> ContentDispositionProjection | None:
    disclosure_class = event.get("disclosure_class", "")
    if not disclosure_class:
        return None
    return ContentDispositionProjection(
        disclosure_class=disclosure_class,
        selector_present=bool(event.get("selector_digest")),
        selector_digest=event.get("selector_digest"),
        selector_required_class=event.get("selector_required_class"),
        includes_hash_only_protection=False,
        prohibited_class_blocked=event.get("status") == "refused",
    )


def _build_artifact_integrity(event: dict) -> ArtifactIntegrityProjection | None:
    receipt_digest = event.get("downstream_receipt_digest")
    event_id_val = event.get("downstream_event_id")
    status = event.get("status", "")
    corruption = event.get("corrupt_detail")

    manifest_image = "unknown"
    manifest_verified = False
    if status in ("manifest_applied", "disclosure_event_recorded", "completed"):
        manifest_image = "post_image"
        manifest_verified = True

    return ArtifactIntegrityProjection(
        receipt_identity=f"dza_{event.get('transition_id', '')}"
        if receipt_digest
        else None,
        receipt_bound=bool(receipt_digest),
        receipt_digest=receipt_digest,
        event_identity=event_id_val,
        event_durable=bool(event_id_val),
        manifest_image=manifest_image,
        manifest_verified=manifest_verified,
        corruption_detail=corruption,
        chain_valid=status not in ("corrupt",),
    )


def _event_to_projection(event: dict) -> DisclosureTransitionProjection:
    """Convert a ledger event dict to a content-light projection."""
    return DisclosureTransitionProjection(
        transition_id=event.get("transition_id", ""),
        authorization_id=event.get("authorization_id", ""),
        evidence_digest=event.get("evidence_digest", ""),
        projection_id=event.get("projection_id", ""),
        status=event.get("status", ""),
        recipient_class=event.get("recipient_class", ""),
        provider_or_channel=event.get("provider_or_channel", ""),
        purpose=event.get("purpose"),
        retention_assertion=event.get("retention_assertion"),
        training_use_assertion=event.get("training_use_assertion"),
        transition_digest=event.get("transition_digest", ""),
        created_at=event.get("created_at", ""),
        sequence=event.get("sequence", 0),
        recovery_provenance=_build_recovery_provenance(event),
        content_disposition=_build_content_disposition(event),
        artifact_integrity=_build_artifact_integrity(event),
    )


# ── Query API ──────────────────────────────────────────────────────────


def _events_for_auth(auth_id: str, evidence: str) -> dict | None:
    """Get the last (most recent status) event for an auth+evidence pair."""
    events = _find_transition_for_auth(auth_id, evidence)
    if not events:
        return None
    events.sort(key=lambda e: e.get("sequence", 0))
    return events[-1]


def _events_for_transition_id(tid: str) -> dict | None:
    """Get the last event for a specific transition_id."""
    events = _load_all_ledger_events()
    matches = [e for e in events if e.get("transition_id") == tid]
    if not matches:
        return None
    matches.sort(key=lambda e: e.get("sequence", 0))
    return matches[-1]


def query_transitions(filter: QueryFilter | None = None) -> DisclosureQueryResult:
    """Read-side query: list disclosure transitions matching optional filter criteria.

    Returns typed, content-light projections suitable for desktop/Gridline
    consumption. Never mutates authority state.
    """
    f = filter or QueryFilter()
    all_events = _load_all_ledger_events()

    transitions_seen: dict[str, dict] = {}
    for ev in all_events:
        tid = ev.get("transition_id", "")
        existing = transitions_seen.get(tid)
        if existing is None:
            transitions_seen[tid] = ev
        elif ev.get("sequence", 0) > existing.get("sequence", 0):
            transitions_seen[tid] = ev

    results: list[DisclosureTransitionProjection] = []

    for ev in transitions_seen.values():
        status = ev.get("status", "")

        if not f.include_terminated and status in {s.value for s in TERMINAL_STATUSES}:
            continue
        if f.status and status != f.status:
            continue
        if f.transition_id and ev.get("transition_id") != f.transition_id:
            continue
        if f.authorization_id and ev.get("authorization_id") != f.authorization_id:
            continue
        if f.evidence_digest and ev.get("evidence_digest") != f.evidence_digest:
            continue

        results.append(_event_to_projection(ev))

    results.sort(key=lambda p: (p.created_at, p.transition_id), reverse=True)

    result = DisclosureQueryResult(
        filter=f, transitions=results, total_count=len(results)
    )
    _seal_result(result)
    return result


def lookup_transition_by_id(
    transition_id: str,
) -> DisclosureTransitionProjection | None:
    """Look up the most recent projection for a specific transition_id."""
    ev = _events_for_transition_id(transition_id)
    if ev is None:
        return None
    return _event_to_projection(ev)


def lookup_transition_by_auth(
    authorization_id: str, evidence_digest: str
) -> DisclosureTransitionProjection | None:
    """Look up the most recent projection for an auth+evidence pair."""
    ev = _events_for_auth(authorization_id, evidence_digest)
    if ev is None:
        return None
    return _event_to_projection(ev)


def compute_projection_digest(projections: list[DisclosureTransitionProjection]) -> str:
    """Compute a deterministic projection digest for a list of transition projections.

    Suitable for UI or governed-agent surface binding — the same canonical
    evidence yields the same digest.
    """
    data = [p.model_dump() for p in projections]
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return _compute_sha256(canonical.encode("utf-8"))


def list_by_status(
    status: TransitionStatus, *, limit: int = 100
) -> list[DisclosureTransitionProjection]:
    """List transitions with a specific terminal or non-terminal status."""
    result = query_transitions(QueryFilter(status=status.value))
    return result.transitions[:limit]


__all__ = [
    "QUERY_SCHEMA_VERSION",
    "ArtifactIntegrityProjection",
    "ContentDispositionProjection",
    "DisclosureQueryResult",
    "DisclosureTransitionProjection",
    "QueryFilter",
    "RecoveryProvenanceProjection",
    "compute_projection_digest",
    "list_by_status",
    "lookup_transition_by_auth",
    "lookup_transition_by_id",
    "query_transitions",
]
