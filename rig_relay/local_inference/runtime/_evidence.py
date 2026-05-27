"""Canonical governed evidence ledgers — locked, schema-validated, digest-chained.

fcntl advisory locking on data file (same file for read and write).
Schema validated via jsonschema. Digest-chained. Idempotent operation_id.
Content-light: SHA256 hashes only.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path

from rig_relay.core.logger import logger

try:
    import jsonschema as _js  # noqa: F401

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class EvidenceLedgerError(Exception):
    pass


class EvidenceLedger:
    def __init__(self, path: Path, schema: dict | None = None) -> None:
        self._path = path
        self._schema = schema
        self._seen_ops: set[str] = set()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, operation_id: str, event: str, payload: dict) -> str:
        if operation_id in self._seen_ops:
            entries = self._read_all()
            for e in entries:
                if e.get("_operation_id") == operation_id:
                    return e.get("_digest", "")
        self._seen_ops.add(operation_id)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        envelope = self._build_envelope(operation_id, event, payload)
        self._validate_schema(payload)
        self._validate_envelope(envelope)

        line = json.dumps(envelope, sort_keys=True, default=str)
        self._write_locked(line)
        logger.debug(
            "evidence: %s op=%s digest=%s",
            self._path.name,
            operation_id,
            envelope["_digest"][:16],
        )
        return envelope["_digest"]

    def reconstruct(self) -> list[dict]:
        entries = self._read_all()
        prev_digest = ""
        validated: list[dict] = []
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
            self._validate_schema(entry.get("payload", {}))
            prev_digest = computed
            validated.append(entry)
        return validated

    def _read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        with open(self._path) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                result: list[dict] = []
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise EvidenceLedgerError(f"Corrupt JSON line {i}: {e}") from e
                return result
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _build_envelope(self, operation_id: str, event: str, payload: dict) -> dict:
        prev = self._last_digest()
        envelope = {
            "_operation_id": operation_id,
            "_event": event,
            "_written_at": _now_iso(),
            "_ledger": self._path.name,
            "_prev_digest": prev,
            "payload": payload,
        }
        envelope["_digest"] = _compute_digest(envelope)
        return envelope

    def _validate_schema(self, payload: dict) -> None:
        if not self._schema:
            return
        if not HAS_JSONSCHEMA:
            return
        import jsonschema

        try:
            jsonschema.validate(payload, self._schema)
        except jsonschema.ValidationError as e:
            raise EvidenceLedgerError(f"Schema: {e.message}") from e

    def _validate_envelope(self, envelope: dict) -> None:
        if not envelope.get("_operation_id"):
            raise EvidenceLedgerError("Missing _operation_id")
        if not envelope.get("_digest"):
            raise EvidenceLedgerError("Missing _digest")

    def _write_locked(self, line: str) -> None:
        with open(self._path, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _last_digest(self) -> str:
        entries = self._read_all()
        return entries[-1].get("_digest", "") if entries else ""


_EVIDENCE_ROOT = Path(".build/rig-relay/evidence")

_EXECUTION_SCHEMA = {
    "type": "object",
    "required": ["receipt_id", "status", "content_light"],
    "properties": {
        "receipt_id": {"type": "string"},
        "task_id_hash": {"type": "string"},
        "status": {"type": "string"},
        "content_light": {"const": True},
    },
}
_LIFECYCLE_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "event", "model_id_hash", "content_light"],
    "properties": {
        "schema_version": {"type": "string"},
        "event": {"type": "string"},
        "model_id_hash": {"type": "string"},
        "content_light": {"const": True},
    },
}
_CACHE_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "content_light"],
    "properties": {
        "schema_version": {"type": "string"},
        "content_light": {"const": True},
    },
}

_execution_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_execution_ledger.jsonl", _EXECUTION_SCHEMA
)
_lifecycle_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_lifecycle_ledger.jsonl", _LIFECYCLE_SCHEMA
)
_cache_ledger = EvidenceLedger(
    _EVIDENCE_ROOT / "runtime_cache_ledger.jsonl", _CACHE_SCHEMA
)


def emit_execution_receipt(op_id: str, receipt: dict) -> str:
    return _execution_ledger.append(
        op_id, "rig.relay.runtime.execution_completed", receipt
    )


def emit_refusal_receipt(op_id: str, refusal_payload: dict) -> str:
    return _execution_ledger.append(
        op_id, "rig.relay.runtime.task_refused", refusal_payload
    )


def emit_lifecycle_event(op_id: str, event: str, payload: dict) -> str:
    return _lifecycle_ledger.append(op_id, event, payload)


def emit_cache_evidence(op_id: str, payload: dict) -> str:
    return _cache_ledger.append(
        op_id, "rig.relay.runtime.cache_evidence_recorded", payload
    )


def emit_tool_proposal_evidence(op_id: str, payload: dict) -> str:
    return _execution_ledger.append(
        op_id, "rig.relay.runtime.tool_proposals_detected", payload
    )


def reconstruct_ledgers() -> dict[str, list[dict]]:
    return {
        "execution": _execution_ledger.reconstruct(),
        "lifecycle": _lifecycle_ledger.reconstruct(),
        "cache": _cache_ledger.reconstruct(),
    }


def _compute_digest(envelope: dict) -> str:
    stripped = {k: v for k, v in envelope.items() if k != "_digest"}
    canonical = json.dumps(stripped, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
