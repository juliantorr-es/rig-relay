"""Canonical governed evidence ledgers — locked, schema-validated, digest-chained.

fcntl advisory locking on data file (same file for read and write).
Schema validated via jsonschema against canonical JSON Schema files under
docs/schemas/. Digest-chained. Idempotent operation_id.
Content-light: SHA256 hashes only.

X2 repair: inline schema dicts replaced with loaded canonical JSON Schema
files. Tool proposal evidence now writes to its own schema-validated ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.core.logger import logger

try:
    import jsonschema as _js  # noqa: F401

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

_SCHEMA_DIR_REL = "docs/schemas"


def _resolve_schema_path(filename: str) -> Path:
    p = Path(_SCHEMA_DIR_REL) / filename
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / _SCHEMA_DIR_REL / filename


def _load_canonical_schema(filename: str) -> dict[str, Any]:
    return json.loads(_resolve_schema_path(filename).read_text("utf-8"))


class EvidenceLedgerError(Exception):
    pass


def _get_fd(path: Path) -> int:
    """Open (or create) the data file and return its file descriptor.

    Uses O_RDWR so the same fd supports both read and write.
    """
    os.makedirs(str(path.parent), exist_ok=True)
    return os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)


def _read_lines_from_fd(fd: int) -> list[dict[str, Any]]:
    """Read and parse every JSONL line through the given file descriptor.

    Seeks to byte 0 first so we always read the full file.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, os.fstat(fd).st_size)
    result: list[dict[str, Any]] = []
    for i, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise EvidenceLedgerError(f"Corrupt JSON line {i}: {e}") from e
    return result


class EvidenceLedger:
    """A digest-chained, schema-validated, lock-guarded append-only evidence ledger.

    The entire append operation (dedup, predecessor selection, serialization,
    validation, write, flush, fsync) happens under a single fcntl LOCK_EX on
    the data file.  Readers also lock the same file with LOCK_SH.
    """

    def __init__(
        self,
        path: Path,
        schema: dict[str, Any] | None = None,
        *,
        require_jsonschema: bool = True,
    ) -> None:
        self._path = path
        self._schema = schema
        if schema is not None and require_jsonschema and not HAS_JSONSCHEMA:
            raise EvidenceLedgerError(
                "EvidenceLedger constructed with a schema but jsonschema is not available. "
                "Install jsonschema or set require_jsonschema=False."
            )
        self._seen_ops: set[str] = set()

    @property
    def path(self) -> Path:
        return self._path

    # ── public append / reconstruct ──────────────────────────────────────

    def append(self, operation_id: str, event: str, payload: dict[str, Any]) -> str:
        """Append one envelope.  Thread- and process-safe via fcntl LOCK_EX."""
        if not operation_id:
            raise EvidenceLedgerError("Missing _operation_id")

        fd = _get_fd(self._path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                return self._append_locked(fd, operation_id, event, payload)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def reconstruct(self) -> list[dict[str, Any]]:
        """Read and validate the entire chain.  Returns envelope list."""
        fd = _get_fd(self._path)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            try:
                return self._reconstruct_locked(fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # ── core locked operations ───────────────────────────────────────────

    def _append_locked(
        self, fd: int, operation_id: str, event: str, payload: dict[str, Any]
    ) -> str:
        # 1. Re-read from disk under lock so we catch writes from other
        #    processes that arrived after our last read.
        existing = _read_lines_from_fd(fd)

        # 2. Idempotent dedup against BOTH disk and in-memory set.
        for e in existing:
            if e.get("_operation_id") == operation_id:
                self._seen_ops.add(operation_id)
                return e.get("_digest", "")
        if operation_id in self._seen_ops:
            # Should not reach here under the lock, but belt-and-suspenders.
            for e in existing:
                if e.get("_operation_id") == operation_id:
                    return e.get("_digest", "")

        # 3. Select predecessor from the re-read chain.
        last = existing[-1] if existing else {}
        prev_digest = last.get("_digest", "") if existing else ""

        # 4. Build and validate the envelope.
        envelope = self._build_envelope(prev_digest, operation_id, event, payload)
        self._validate_payload(payload)
        self._validate_envelope(envelope)

        # 5. Write, flush, fsync — all under the lock.
        line = json.dumps(envelope, sort_keys=True, default=str) + "\n"
        os.lseek(fd, 0, os.SEEK_END)
        written = os.write(fd, line.encode("utf-8"))
        if written != len(line.encode("utf-8")):
            raise EvidenceLedgerError(
                f"Short write: {written} != {len(line.encode('utf-8'))}"
            )
        os.fsync(fd)

        # 6. Record in memory set (under lock).
        self._seen_ops.add(operation_id)

        logger.debug(
            "evidence: %s op=%s digest=%s",
            self._path.name,
            operation_id,
            envelope["_digest"][:16],
        )
        return envelope["_digest"]

    def _reconstruct_locked(self, fd: int) -> list[dict[str, Any]]:
        entries = _read_lines_from_fd(fd)
        prev_digest = ""
        validated: list[dict[str, Any]] = []
        seen_ops: set[str] = set()

        for i, entry in enumerate(entries, 1):
            computed = _compute_digest(entry)
            expected = entry.get("_digest", "")
            if computed != expected:
                raise EvidenceLedgerError(
                    f"Digest mismatch line {i}: {computed[:16]} != {expected[:16]}"
                )
            if prev_digest and entry.get("_prev_digest") != prev_digest:
                raise EvidenceLedgerError(f"Chain break line {i}")
            op_id = entry.get("_operation_id", "")
            if op_id and op_id in seen_ops:
                raise EvidenceLedgerError(f"Duplicate op line {i}: {op_id}")
            if op_id:
                seen_ops.add(op_id)
            self._validate_payload(entry.get("payload", {}))
            prev_digest = computed
            validated.append(entry)
        return validated

    # ── envelope construction ────────────────────────────────────────────

    def _build_envelope(
        self, prev_digest: str, operation_id: str, event: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "_operation_id": operation_id,
            "_event": event,
            "_written_at": _now_iso(),
            "_ledger": self._path.name,
            "_prev_digest": prev_digest,
            "payload": payload,
        }
        envelope["_digest"] = _compute_digest(envelope)
        return envelope

    # ── validation ───────────────────────────────────────────────────────

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        if not self._schema:
            return
        if not HAS_JSONSCHEMA:
            raise EvidenceLedgerError(
                "Schema validation requested but jsonschema is not available."
            )
        import jsonschema

        try:
            jsonschema.validate(payload, self._schema)
        except jsonschema.ValidationError as e:
            raise EvidenceLedgerError(f"Schema: {e.message}") from e

    def _validate_envelope(self, envelope: dict[str, Any]) -> None:
        if not envelope.get("_operation_id"):
            raise EvidenceLedgerError("Missing _operation_id")
        if not envelope.get("_digest"):
            raise EvidenceLedgerError("Missing _digest")

    # ── internal helpers (no filesystem I/O) ─────────────────────────────

    def _last_digest(self) -> str:
        """Read the last digest.  Caller MUST hold the lock."""
        # This is kept for informational callers but is NOT used inside
        # the append path (which does its own read under the lock).
        fd = _get_fd(self._path)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            try:
                entries = _read_lines_from_fd(fd)
                return entries[-1].get("_digest", "") if entries else ""
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ── module-level ledger instances ────────────────────────────────────────

_EVIDENCE_ROOT = Path(".build/rig-relay/evidence")

# Canonical schemas loaded from docs/schemas/ (published authority).
_EXECUTION_SCHEMA = _load_canonical_schema(
    "rig.relay.runtime_execution_event.v1.schema.json"
)
_LIFECYCLE_SCHEMA = _load_canonical_schema(
    "rig.relay.runtime_lifecycle_event.v1.schema.json"
)
_CACHE_SCHEMA = _load_canonical_schema("rig.relay.runtime_cache_event.v1.schema.json")
_SCHEDULER_SCHEMA = _load_canonical_schema(
    "rig.relay.runtime_scheduler_event.v1.schema.json"
)
_TOOL_PROPOSAL_SCHEMA = _load_canonical_schema(
    "rig.relay.runtime_tool_proposal_event.v1.schema.json"
)

_execution_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_execution_ledger.jsonl", _EXECUTION_SCHEMA
)
_lifecycle_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_lifecycle_ledger.jsonl", _LIFECYCLE_SCHEMA
)
_cache_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_cache_ledger.jsonl", _CACHE_SCHEMA
)
_scheduler_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_scheduler_ledger.jsonl", _SCHEDULER_SCHEMA
)
_tool_proposal_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_tool_proposal_ledger.jsonl", _TOOL_PROPOSAL_SCHEMA
)


def emit_execution_receipt(op_id: str, receipt: dict[str, Any]) -> str:
    return _execution_ledger.append(
        op_id, "rig.relay.runtime.execution_completed", receipt
    )


def emit_refusal_receipt(op_id: str, refusal_payload: dict[str, Any]) -> str:
    return _execution_ledger.append(
        op_id, "rig.relay.runtime.task_refused", refusal_payload
    )


def emit_lifecycle_event(op_id: str, event: str, payload: dict[str, Any]) -> str:
    return _lifecycle_ledger.append(op_id, event, payload)


def emit_cache_evidence(op_id: str, payload: dict[str, Any]) -> str:
    return _cache_ledger.append(
        op_id, "rig.relay.runtime.cache_evidence_recorded", payload
    )


def emit_tool_proposal_evidence(op_id: str, payload: dict[str, Any]) -> str:
    return _tool_proposal_ledger.append(
        op_id, "rig.relay.runtime.tool_proposals_detected", payload
    )


def emit_scheduler_event(op_id: str, event_type: str, payload: dict[str, Any]) -> str:
    return _scheduler_ledger.append(
        op_id, f"rig.relay.runtime.scheduler.{event_type}", payload
    )


_STREAM_TERMINAL_ROOT = Path(".build/rig-relay/evidence")
_STREAM_TERMINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "operation_id", "terminal_state", "content_light"],
    "properties": {
        "schema_version": {"type": "string"},
        "operation_id": {"type": "string"},
        "terminal_state": {
            "type": "string",
            "enum": ["provisional", "terminalized", "evidence_failed"],
        },
        "evidence_receipt_id": {"type": "string"},
        "content_light": {"const": True},
    },
    "additionalProperties": False,
}

_stream_terminal_ledger = EvidenceLedger(
    _STREAM_TERMINAL_ROOT / "runtime_stream_terminal_ledger.jsonl",
    _STREAM_TERMINAL_SCHEMA,
)


def emit_stream_terminal_event(op_id: str, payload: dict[str, Any]) -> str:
    return _stream_terminal_ledger.append(
        op_id, "rig.relay.runtime.stream_terminalized", payload
    )


def reconstruct_ledgers() -> dict[str, list[dict[str, Any]]]:
    return {
        "execution": _execution_ledger.reconstruct(),
        "lifecycle": _lifecycle_ledger.reconstruct(),
        "cache": _cache_ledger.reconstruct(),
        "scheduler": _scheduler_ledger.reconstruct(),
        "tool_proposal": _tool_proposal_ledger.reconstruct(),
        "stream_terminal": _stream_terminal_ledger.reconstruct(),
    }


# ── hashing ──────────────────────────────────────────────────────────────


def _compute_digest(envelope: dict[str, Any]) -> str:
    stripped = {k: v for k, v in envelope.items() if k != "_digest"}
    canonical = json.dumps(stripped, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
