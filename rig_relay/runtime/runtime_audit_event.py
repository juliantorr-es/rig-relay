"""RuntimeAuditEvent — content-light audit event for runtime tool executions.

Records the outcome of a RuntimeToolExecutionResult as a persistable,
content-light audit event. Written to an append-only JSONL store.

All event data is content-light: no raw payloads, stdout, stderr, file
contents, diffs, snippets, or secrets. Only status indicators, hashes,
timing, changed paths, and context propagation fields.

Context propagation (Otel-inspired):
- mission_id, agent_id, lease_id, parent_event_id are carried when
  available so logs/traces/audits across process boundaries correlate.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.runtime_audit_event.v1"

# ── Model ─────────────────────────────────────────────────────────────


class RuntimeAuditEvent(BaseModel):
    """Content-light audit event for a runtime tool execution.

    Captures the full outcome of a RuntimeToolExecutionResult as an
    append-only audit record. The runtime_result_sha256 field links
    to the execution result's canonical JSON so that tampering or
    data drift can be detected.

    Context propagation fields (optional):
      mission_id, agent_id, lease_id, parent_event_id — carried when
      available so invocations can be correlated across boundaries.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    audit_event_id: str
    invocation_id: str
    tool_name: str
    status: str  # completed | blocked | refused | failed
    tool_status: str | None = None
    receipt_sha256: str | None = None
    runtime_result_sha256: str | None = None
    runtime_envelope_sha256: str | None = None
    supervisor_result_envelope_id: str | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None
    source_kind: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    tool_receipt_kind: str | None = None
    tool_receipt_schema_version: str | None = None
    # ── Context propagation (Otel-inspired) ───────────────────────
    mission_id: str | None = None
    agent_id: str | None = None
    lease_id: str | None = None
    parent_event_id: str | None = None
    # ── Timing ────────────────────────────────────────────────────
    created_at: str = ""


# ── Builder ───────────────────────────────────────────────────────────


def build_runtime_audit_event(
    result: Any,
    *,
    audit_event_id: str | None = None,
    created_at: str | None = None,
    mission_id: str | None = None,
    agent_id: str | None = None,
    lease_id: str | None = None,
    parent_event_id: str | None = None,
) -> RuntimeAuditEvent:
    """Build a RuntimeAuditEvent from a RuntimeToolExecutionResult.

    Computes runtime_result_sha256 as the SHA-256 of the result's
    canonical JSON model dump. Copies content-light fields only.

    Context propagation fields (mission_id, agent_id, lease_id,
    parent_event_id) are passed through when available so
    invocations can be correlated across process boundaries.
    """
    from datetime import UTC, datetime

    stamp = created_at or datetime.now(UTC).isoformat()
    eid = audit_event_id or _generate_event_id(result.invocation_id or result.intent_id)

    # Compute runtime_result_sha256 from canonical JSON
    result_json = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    result_sha256 = "sha256:" + hashlib.sha256(result_json.encode()).hexdigest()

    return RuntimeAuditEvent(
        schema_version=_SCHEMA_VERSION,
        audit_event_id=eid,
        invocation_id=result.invocation_id or result.intent_id,
        tool_name=result.tool_name,
        status=result.status.value
        if hasattr(result.status, "value")
        else str(result.status),
        tool_status=result.tool_status,
        receipt_sha256=result.receipt_sha256,
        runtime_result_sha256=result_sha256,
        runtime_envelope_sha256=getattr(result, "runtime_envelope_sha256", None),
        supervisor_result_envelope_id=getattr(
            result, "supervisor_result_envelope_id", None
        ),
        supervisor_result_envelope_sha256=getattr(
            result, "supervisor_result_envelope_sha256", None
        ),
        supervisor_result_classification=getattr(
            result, "supervisor_result_classification", None
        ),
        source_kind=getattr(result, "source_kind", None),
        changed_paths=list(result.changed_paths),
        duration_ms=result.duration_ms,
        error_kind=result.error_kind,
        refusal_reason=result.refusal_reason,
        tool_receipt_kind=result.tool_receipt_kind,
        tool_receipt_schema_version=result.tool_receipt_schema_version,
        mission_id=mission_id,
        agent_id=agent_id,
        lease_id=lease_id,
        parent_event_id=parent_event_id,
        created_at=stamp,
    )


def _generate_event_id(invocation_id: str) -> str:
    """Generate a content-addressed audit event ID."""
    import hashlib

    raw = f"runtime_audit:{invocation_id}:{datetime.now(UTC).isoformat()}"
    return "aev-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Store ─────────────────────────────────────────────────────────────


class RuntimeAuditPersistenceStore:
    """Append-only JSONL store for RuntimeAuditEvent records.

    Each append writes a single JSON line. Creates parent directories
    automatically. Uses flush + fsync for best-effort durability.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ── Public API ─────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
        """Append an audit event to the JSONL file.

        Creates parent directories if needed. Flushes and fsyncs
        for best-effort durability.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = (
            json.dumps(
                event.model_dump(mode="json"),
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

    def read_events(self) -> list[RuntimeAuditEvent]:
        """Read all audit events from the JSONL file.

        Returns an empty list if the file does not exist. Parsing
        errors are silently skipped (malformed lines are ignored).
        """
        if not self._path.is_file():
            return []

        events: list[RuntimeAuditEvent] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = RuntimeAuditEvent.model_validate(data)
                    events.append(event)
                except (json.JSONDecodeError, ValueError):
                    pass
        return events

    def count(self) -> int:
        """Count events without loading all into memory."""
        if not self._path.is_file():
            return 0
        count = 0
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


__all__ = [
    "RuntimeAuditEvent",
    "RuntimeAuditPersistenceStore",
    "build_runtime_audit_event",
]
