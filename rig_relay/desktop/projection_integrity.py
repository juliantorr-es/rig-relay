"""Rig Relay Projection Integrity Assessment — read-only integrity models and builder.

Provides content-light integrity checks that can be attached to desktop
projections. All checks are pure (no side effects, no file reads).

Pattern source: Rig's projection_builder._compute_integrity_status() and
projection_contracts, adapted as a relay-native module.

Doctrine:
- All assessments are read-only.
- All checks are deterministic from supplied data.
- Authority claims must have receipt backing.
- Stale/orphaned receipts are flagged by timestamp.
- No raw receipt payloads, logs, or output in assessments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Placeholder constants ─────────────────────────────────────────────

PLACEHOLDER_NO_RECEIPT = "no_receipt"
PLACEHOLDER_UNAVAILABLE = "unavailable"

# ── Enums ─────────────────────────────────────────────────────────────


class ProjectionIntegrityStatus(StrEnum):
    """Overall integrity status of a projection."""

    VERIFIED = "verified"
    DEGRADED = "degraded"
    STALE = "stale"
    ORPHANED = "orphaned"
    UNKNOWN = "unknown"


class ProjectionContractStatus(StrEnum):
    """Contract satisfaction status for a projection."""

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    VIOLATED = "violated"
    NOT_APPLICABLE = "not_applicable"


class ProjectionViolationCode(StrEnum):
    """Canonical violation codes for projection integrity checks."""

    MISSING_RECEIPT = "missing_receipt"
    STALE_RECEIPT = "stale_receipt"
    ORPHANED_RECEIPT = "orphaned_receipt"
    AUTHORITY_UNBACKED = "authority_unbacked"
    SCHEMA_MISMATCH = "schema_mismatch"
    CONTENT_POLICY_VIOLATION = "content_policy_violation"
    UNKNOWN_WIDGET = "unknown_widget"


# ── Models ────────────────────────────────────────────────────────────


class ProjectionViolation(BaseModel):
    """A single projection integrity violation."""

    model_config = ConfigDict(extra="forbid")

    code: ProjectionViolationCode
    message: str
    severity: str = "warning"
    widget_name: str | None = None
    receipt_id: str | None = None
    path: str | None = None


class ProjectionIntegrityAssessment(BaseModel):
    """Content-light integrity assessment for a single projection.

    Contains no raw receipt payloads, logs, or output — only
    status enums, violation codes, counts, and timestamps.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.projection_integrity.v1"
    integrity_status: ProjectionIntegrityStatus = ProjectionIntegrityStatus.UNKNOWN
    contract_status: ProjectionContractStatus = ProjectionContractStatus.NOT_APPLICABLE
    violation_count: int = 0
    violations: list[ProjectionViolation] = Field(default_factory=list)
    checked_at: str = ""
    receipt_count: int = 0
    stale_receipt_count: int = 0
    orphaned_receipt_count: int = 0
    authority_backed: bool = False


# ── Builder ───────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def build_projection_integrity_assessment(  # noqa: PLR0912, PLR0914, PLR0915
    receipt_records: list[dict[str, Any]] | None = None,
    widget_names: list[str] | None = None,
    claimed_authorities: list[str] | dict[str, str] | None = None,
    now: datetime | None = None,
    stale_after_seconds: int | None = 3600,
) -> ProjectionIntegrityAssessment:
    """Build a content-light integrity assessment from available data.

    Pure function: no side effects, no file reads.

    Args:
        receipt_records: List of ``ToolReceiptIndexRecord`` or minimal dicts
            with at least ``tool_name`` and ``captured_at`` keys.
        widget_names: List of widget names present in the projection.
        claimed_authorities: List of intent/action names claimed by the
            projection, or a dict mapping authority name to receipt id.
        now: Current datetime. Defaults to ``datetime.now(UTC)``.
        stale_after_seconds: Seconds after which a receipt is considered
            stale. ``None`` disables stale detection.

    Returns:
        A ``ProjectionIntegrityAssessment`` with all fields populated.
    """
    checked_at = (now or _utc_now()).isoformat()
    violations: list[ProjectionViolation] = []
    receipts = list(receipt_records or [])
    receipt_count = len(receipts)
    stale_count = 0
    orphaned_count = 0
    authority_backed = False

    # ── Check receipt staleness ──
    if stale_after_seconds is not None and stale_after_seconds > 0:
        cutoff = (now or _utc_now()).timestamp() - stale_after_seconds
        for rec in receipts:
            captured_at = None
            if isinstance(rec, dict):
                captured_at = _parse_timestamp(rec.get("captured_at"))
            elif hasattr(rec, "captured_at"):
                captured_at = _parse_timestamp(rec.captured_at)
            if captured_at and captured_at.timestamp() < cutoff:
                stale_count += 1
                receipt_id = None
                if isinstance(rec, dict):
                    receipt_id = rec.get("event_id")
                elif hasattr(rec, "event_id"):
                    receipt_id = rec.event_id
                violations.append(
                    ProjectionViolation(
                        code=ProjectionViolationCode.STALE_RECEIPT,
                        message=f"Receipt captured at {captured_at.isoformat()} exceeds {stale_after_seconds}s stale threshold",
                        severity="warning",
                        receipt_id=str(receipt_id) if receipt_id else None,
                    )
                )

    # ── Check orphaned receipts ──
    for rec in receipts:
        is_orphaned = False
        receipt_id = None
        if isinstance(rec, dict):
            if not rec.get("session_id") or not rec.get("tool_name"):
                is_orphaned = True
                receipt_id = rec.get("event_id")
        elif hasattr(rec, "session_id") and hasattr(rec, "tool_name"):
            if not rec.session_id or not rec.tool_name:
                is_orphaned = True
                receipt_id = rec.event_id
        if is_orphaned:
            orphaned_count += 1
            violations.append(
                ProjectionViolation(
                    code=ProjectionViolationCode.ORPHANED_RECEIPT,
                    message="Receipt record is missing required linkage fields (session_id, tool_name)",
                    severity="warning",
                    receipt_id=str(receipt_id) if receipt_id else None,
                )
            )

    # ── Check authority backing ──
    if claimed_authorities:
        if isinstance(claimed_authorities, dict):
            receipt_ids = set()
            for r in receipts:
                rid = (
                    r.get("event_id")
                    if isinstance(r, dict)
                    else getattr(r, "event_id", None)
                )
                if rid:
                    receipt_ids.add(rid)
            authority_backed = all(
                bid in receipt_ids for bid in claimed_authorities.values()
            )
        else:
            authority_backed = len(receipts) > 0
        if not authority_backed:
            violations.append(
                ProjectionViolation(
                    code=ProjectionViolationCode.AUTHORITY_UNBACKED,
                    message="Projection claims authority without receipt backing",
                    severity="error",
                )
            )
    else:
        authority_backed = len(receipts) > 0

    # ── Check unknown widgets ──
    if widget_names:
        from rig_relay.desktop.projection_widgets import ALL_WIDGETS

        for wname in widget_names:
            if wname not in ALL_WIDGETS:
                violations.append(
                    ProjectionViolation(
                        code=ProjectionViolationCode.UNKNOWN_WIDGET,
                        message=f"Widget '{wname}' is not in the canonical widget taxonomy",
                        severity="warning",
                        widget_name=wname,
                    )
                )

    # ── Determine statuses ──
    violation_count = len(violations)

    has_stale = any(v.code == ProjectionViolationCode.STALE_RECEIPT for v in violations)
    has_orphaned = any(
        v.code == ProjectionViolationCode.ORPHANED_RECEIPT for v in violations
    )
    has_unbacked = any(
        v.code == ProjectionViolationCode.AUTHORITY_UNBACKED for v in violations
    )

    if violation_count == 0 and receipt_count > 0:
        integrity_status = ProjectionIntegrityStatus.VERIFIED
    elif has_stale:
        integrity_status = ProjectionIntegrityStatus.STALE
    elif has_orphaned:
        integrity_status = ProjectionIntegrityStatus.ORPHANED
    elif has_unbacked:
        integrity_status = ProjectionIntegrityStatus.DEGRADED
    elif receipt_count == 0 and not claimed_authorities:
        integrity_status = ProjectionIntegrityStatus.UNKNOWN
    else:
        integrity_status = ProjectionIntegrityStatus.DEGRADED

    if not claimed_authorities and not widget_names:
        contract_status = ProjectionContractStatus.NOT_APPLICABLE
    elif violation_count == 0:
        contract_status = ProjectionContractStatus.SATISFIED
    elif any(v.severity == "error" for v in violations):
        contract_status = ProjectionContractStatus.VIOLATED
    else:
        contract_status = ProjectionContractStatus.PARTIAL

    return ProjectionIntegrityAssessment(
        schema_version="rig.relay.projection_integrity.v1",
        integrity_status=integrity_status,
        contract_status=contract_status,
        violation_count=violation_count,
        violations=violations,
        checked_at=checked_at,
        receipt_count=receipt_count,
        stale_receipt_count=stale_count,
        orphaned_receipt_count=orphaned_count,
        authority_backed=authority_backed,
    )
