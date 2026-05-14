"""Rig Relay Audit Trail — append-only content-light audit store.

Provides the AuditEvent model and an append-only AuditTrailStore that
persists content-light audit events as JSONL. Each event can reference
a ReceiptEnvelope by ID or embed a full ReceiptEnvelope if content-light.

All event data is content-light: no raw payloads, stdout, stderr, file
contents, diffs, snippets, or secrets.

Provenance (Rig-to-Relay porting doctrine):
  Pattern source: Rig's workspace_audit.py (AuditAction, AuditSubjectKind,
  AuditDecision, AuditActor, AuditSubject, AuditEvent, AuditTrailStore)
  adapted as a relay-native Pydantic module.
  Porting status: reimplement (relay_owned).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
  Not a copy of Rig's product domain — uses relay-native field names,
  Pydantic BaseModel, StrEnum, extra="forbid", content-light conventions,
  and append-only JSONL storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptEnvelope,
    ReceiptSubject,
)

# ── Enums ─────────────────────────────────────────────────────────────


class AuditActionKind(StrEnum):
    """Canonical audit action types for the relay audit trail."""

    RECEIPT_CREATED = "receipt_created"
    DECISION_RECORDED = "decision_recorded"
    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    WORKTREE_CREATED = "worktree_created"
    WORKTREE_REMOVED = "worktree_removed"
    VALIDATION_COMPLETED = "validation_completed"
    PROJECTION_BUILT = "projection_built"
    ENVELOPE_CREATED = "envelope_created"


class AuditDecisionKind(StrEnum):
    """Canonical audit decision outcomes."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    REFUSED = "refused"
    COMPLETED = "completed"
    FAILED = "failed"
    INFORMATIONAL = "informational"


# ── Model ─────────────────────────────────────────────────────────────


class AuditEvent(BaseModel):
    """A single content-light audit trail event.

    References a ReceiptEnvelope by ID or embeds a full ReceiptEnvelope.
    All event data is content-light: no raw payloads, stdout, stderr,
    file contents, diffs, snippets, or secrets.

    Deterministic ordering: events are ordered by ``sequence``, then
    ``timestamp`` on read.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.audit_event.v1"
    event_id: str
    sequence: int
    timestamp: str
    workspace_id: str | None = None
    session_id: str | None = None
    actor: ReceiptActor | None = None
    action: AuditActionKind
    subject: ReceiptSubject | None = None
    decision: AuditDecisionKind
    envelope_id: str | None = None
    envelope: ReceiptEnvelope | None = None
    evidence_sha256: str | None = None
    notes: list[str] = Field(default_factory=list)


# ── Store ─────────────────────────────────────────────────────────────


class AuditStoreReadError(Exception):
    """Raised when an audit event line cannot be parsed during read."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(message)


class AuditTrailStore:
    """Append-only local audit trail store backed by JSONL.

    Writes are appended to a single JSONL file. Reads parse all lines
    and return parsed events plus any parse errors. Malformed lines
    are reported as read errors — the store does not crash on them.

    Not cryptographically signed or tamper-proof. Append-only guarantees
    are best-effort local (flush + fsync per append).

    Deterministic ordering: events are sorted by ``(sequence, timestamp)``
    on read.

    Example::

        store = AuditTrailStore(Path("/tmp/audit.jsonl"))
        event = store.append(AuditEvent(...))
        events, errors = store.read_events()
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock: Any = None  # future: threading.Lock for concurrent writes

    # ── Public API ─────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        """Return the path to the audit trail JSONL file."""
        return self._path

    def append(self, event: AuditEvent) -> AuditEvent:
        """Append an audit event to the trail.

        Creates parent directories if needed. Flushes and fsyncs
        the file after writing for durability.

        Args:
            event: The AuditEvent to persist.

        Returns:
            The event (same instance) for chaining.

        Raises:
            OSError: If the file cannot be written.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            json.dumps(
                event.model_dump(mode="json", exclude_none=True),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return event

    def append_audit_event(  # noqa: PLR0913
        self,
        *,
        event_id: str,
        action: AuditActionKind,
        decision: AuditDecisionKind,
        actor: ReceiptActor | None = None,
        subject: ReceiptSubject | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        envelope_id: str | None = None,
        envelope: ReceiptEnvelope | None = None,
        evidence_sha256: str | None = None,
        notes: list[str] | None = None,
        timestamp: str | None = None,
    ) -> AuditEvent:
        """Build and append an audit event from components.

        Convenience method that constructs an AuditEvent with an
        auto-computed sequence number and appends it.

        Args:
            event_id: Unique event identifier.
            action: The audit action kind.
            decision: The audit decision kind.
            actor: Optional ReceiptActor.
            subject: Optional ReceiptSubject.
            workspace_id: Optional workspace context.
            session_id: Optional session context.
            envelope_id: Optional ReceiptEnvelope reference.
            envelope: Optional embedded ReceiptEnvelope.
            evidence_sha256: Optional content hash.
            notes: Optional list of human-readable notes.
            timestamp: ISO 8601 timestamp. Auto-generated if omitted.

        Returns:
            The created and persisted AuditEvent.
        """
        seq = self.next_sequence()
        stamp = timestamp or datetime.now(UTC).isoformat()
        event = AuditEvent(
            schema_version="rig.relay.audit_event.v1",
            event_id=event_id,
            sequence=seq,
            timestamp=stamp,
            workspace_id=workspace_id,
            session_id=session_id,
            actor=actor,
            action=action,
            subject=subject,
            decision=decision,
            envelope_id=envelope_id,
            envelope=envelope,
            evidence_sha256=evidence_sha256,
            notes=notes or [],
        )
        return self.append(event)

    def read_events(self) -> tuple[list[AuditEvent], list[AuditStoreReadError]]:
        """Read all audit events from the trail.

        Returns:
            (events, errors) where:
            - events is a list of successfully parsed AuditEvent,
              sorted by ``(sequence, timestamp)``.
            - errors is a list of AuditStoreReadError for lines that
              could not be parsed.

        Malformed lines are reported as errors, not raised. The store
        returns all valid events even when some lines are corrupted.
        """
        if not self._path.is_file():
            return [], []

        events: list[AuditEvent] = []
        errors: list[AuditStoreReadError] = []

        with self._path.open("r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = AuditEvent.model_validate(data)
                    events.append(event)
                except (json.JSONDecodeError, ValueError) as e:
                    errors.append(
                        AuditStoreReadError(
                            message=f"line {line_idx}: {e}", line=line_idx
                        )
                    )

        # Deterministic ordering: sequence first, then timestamp
        events.sort(key=lambda e: (e.sequence, e.timestamp))
        return events, errors

    def next_sequence(self) -> int:
        """Compute the next sequence number.

        Counts existing lines in the JSONL file. This is approximate
        under concurrent writers (no lock). For single-writer use,
        this is deterministic.
        """
        if not self._path.is_file():
            return 1
        with self._path.open("r", encoding="utf-8") as f:
            count = sum(1 for _ in f)
        return count + 1

    def latest_event(self) -> AuditEvent | None:
        """Return the latest audit event, or None if empty."""
        events, _errors = self.read_events()
        if not events:
            return None
        return events[-1]


__all__ = [
    "AuditActionKind",
    "AuditDecisionKind",
    "AuditEvent",
    "AuditStoreReadError",
    "AuditTrailStore",
]
