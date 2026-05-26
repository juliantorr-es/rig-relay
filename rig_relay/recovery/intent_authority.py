"""Durable Recovery Intent Authority v1.

Canonical, digest-validated, policy-bounded executable-input authority
for the recovery execution corridor. The handoff's (recovery_receipt_sha256,
payload_digest) composite key identifies the canonical intent.

Separates content-light intent receipts (in a schema-validated, fail-closed
evidence ledger) from crash-durable governed executable payloads (in a
separate, atomically written payload store). No raw tool arguments, file
content, or secrets appear in evidence.

Materialization must complete before execution. The originating recovery
corridor (D1/D2) carries a payload digest; this authority materializes the
actual executable payload before any live runtime admission. No caller can
substitute args after first materialization.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import (
    ValidationError as _JsonSchemaValidationError,
    validate as _jsonschema_validate,
)


@dataclass
class MaterializationRequest:
    """Typed materialization parameters. No raw payload in evidence."""

    recovery_receipt_sha256: str
    payload_digest: str
    manifest_digest: str
    canonical_tool_name: str
    normalized_args: dict[str, Any]
    execution_class: str
    correlation_id: str = ""
    validation_profile: str | None = None
    bounded_paths: list[str] | None = None
    mutation_class: str | None = None
    materialization_kind: str = "pre_handoff"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _compute_intent_id(recovery_receipt_sha256: str, payload_digest: str) -> str:
    """Deterministic intent identifier from the composite key."""
    raw = f"{recovery_receipt_sha256}|{payload_digest}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _compute_event_digest(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _sha256_data(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


_FORBIDDEN_RECEIPT_KEYS = frozenset({
    "raw_emission",
    "raw_prompt",
    "raw_model_output",
    "normalized_payload",
    "normalized_args",
    "file_content",
    "mutation_content",
    "secret",
    "api_key",
    "token",
    "command_content",
    "raw_stdout",
    "raw_stderr",
})


def _fsync_dir(dir_path: Path) -> None:
    """fsync the directory to ensure metadata (renames, creates) is durable."""
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


class GovernedPayloadStore:
    """Separate, digest-verified, crash-durable payload storage.

    Payloads live outside the evidence ledger. Keyed by intent_id.
    Content-light evidence never sees the raw payload — only its digest.

    Writes are atomic (tempfile + rename) and durably fsynced.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        atexit.register(self._cleanup_temp_files)

    def put(self, intent_id: str, payload: dict[str, Any]) -> str:
        """Store payload atomically and durably under per-intent lock."""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = _sha256_data(raw)
        lock_path = self._dir / f"{intent_id}.lock"
        with open(lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                self._write_locked(intent_id, payload)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        return payload_digest

    def _write_locked(self, intent_id: str, payload: dict[str, Any]) -> str:
        """Write payload when caller already holds the per-intent lock."""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = _sha256_data(raw)
        payload_path = self._dir / f"{intent_id}.json"
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=self._dir, prefix=f".{intent_id}.", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as tmp_f:
                tmp_f.write(raw)
                tmp_f.flush()
                os.fsync(tmp_f.fileno())
            os.rename(tmp_path, str(payload_path))
            _fsync_dir(self._dir)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
        payload_path.chmod(0o600)
        return payload_digest

    def get(self, intent_id: str) -> dict[str, Any] | None:
        """Retrieve stored payload. Returns None if not found or corrupt."""
        payload_path = self._dir / f"{intent_id}.json"
        if not payload_path.exists():
            return None
        try:
            raw = payload_path.read_text()
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, intent_id: str) -> bool:
        return (self._dir / f"{intent_id}.json").exists()

    def _cleanup_temp_files(self) -> None:
        """Remove orphaned temp files from incomplete writes."""
        try:
            for p in self._dir.glob(".*.tmp"):
                try:
                    p.unlink()
                except OSError:
                    pass
        except OSError:
            pass


class DurableRecoveryIntentAuthority:
    """Canonical recovery intent authority.

    Persists content-light intent receipts in an append-only JSONL ledger
    and executable payloads in a separate governed store. The composite key
    (recovery_receipt_sha256, payload_digest) identifies the canonical intent.

    Lazy-first-write: the first caller to materialize a verified intent for
    a given composite key wins. Subsequent callers with different args for
    the same key are refused.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._payload_store = GovernedPayloadStore(data_dir / "payloads")
        self._receipt_path = data_dir / "intent_receipts.jsonl"
        self._receipt_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = data_dir / "intent_receipts.jsonl.lock"
        self._schema: dict[str, Any] | None = None

    def _load_schema(self) -> dict[str, Any] | None:
        """Load the intent authority schema, caching it.

        Returns None if the schema file is absent (will be caught by
        _validate_receipt_against_schema).
        """
        if self._schema is not None:
            return self._schema

        import rig_relay

        root = Path(rig_relay.__file__).parent.parent
        resolved = (
            root
            / "docs"
            / "schemas"
            / "rig.relay.recovery_intent_authority.v1.schema.json"
        )

        if not resolved.exists():
            return None

        try:
            self._schema = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Intent authority schema is invalid JSON: {e}") from e

        return self._schema

    def _validate_receipt_against_schema(self, event: dict[str, Any]) -> None:
        """Validate receipt event against the canonical schema.

        Fail-closed: any validation failure raises ValueError.
        Schema file must be present and valid. jsonschema must be importable.
        """
        schema = self._load_schema()
        if schema is None:
            raise ValueError(
                "Intent authority schema file not found — cannot validate receipt"
            )
        try:
            _jsonschema_validate(instance=event, schema=schema)
        except _JsonSchemaValidationError as e:
            raise ValueError(
                f"Intent receipt failed schema validation: {e.message}"
            ) from e

    @property
    def payload_store(self) -> GovernedPayloadStore:
        return self._payload_store

    def materialize_intent(self, req: MaterializationRequest) -> str:
        """Materialize a recovery intent under a lock-scoped admission protocol.

        The full check → write → receipt sequence is guarded by a per-intent
        fcntl lock. Two concurrent materializers for the same composite key
        converge to one canonical receipt and one payload identity.

        Raises ValueError on digest mismatch or invalid receipt.
        """
        raw = json.dumps(req.normalized_args, sort_keys=True, separators=(",", ":"))
        computed = _sha256_data(raw)
        if computed != req.payload_digest:
            raise ValueError(
                f"Payload digest mismatch: expected {req.payload_digest[:20]}..., "
                f"computed {computed[:20]}..."
            )

        intent_id = _compute_intent_id(req.recovery_receipt_sha256, req.payload_digest)

        # ── Lock-scoped admission: full check → write → receipt ──
        lock_path = self._data_dir / f".materialize.{intent_id}.lock"
        with open(lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                # Re-check existence under lock (closes TOCTOU gap)
                existing = self._load_receipt_by_intent_id(intent_id)
                if existing is not None:
                    stored = self._payload_store.get(intent_id)
                    if stored is None:
                        raise ValueError(
                            f"Intent {intent_id[:20]}... has receipt but no payload"
                        )
                    stored_raw = json.dumps(
                        stored, sort_keys=True, separators=(",", ":")
                    )
                    stored_digest = _sha256_data(stored_raw)
                    if stored_digest != req.payload_digest:
                        raise ValueError(
                            f"Intent {intent_id[:20]}... already materialized with "
                            f"different payload"
                        )
                    return intent_id

                # No existing intent — write payload (no separate lock needed;
                # we hold the per-intent lock already)
                self._payload_store._write_locked(intent_id, req.normalized_args)

                # Build and persist content-light receipt
                receipt_event = {
                    "schema_version": "rig.relay.recovery_intent_authority.v1",
                    "intent_id": intent_id,
                    "recovery_receipt_sha256": req.recovery_receipt_sha256,
                    "payload_digest": req.payload_digest,
                    "manifest_digest": req.manifest_digest,
                    "canonical_tool_name": req.canonical_tool_name,
                    "execution_class": req.execution_class,
                    "correlation_id": req.correlation_id,
                    "validation_profile": req.validation_profile,
                    "bounded_paths": list(req.bounded_paths)
                    if req.bounded_paths
                    else [],
                    "mutation_class": req.mutation_class,
                    "materialization_kind": req.materialization_kind,
                    "content_light": True,
                    "created_at": _utcnow_iso(),
                }
                self._append_receipt_locked(receipt_event)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

        return intent_id

    def load_intent(
        self, recovery_receipt_sha256: str, payload_digest: str
    ) -> dict[str, Any] | None:
        """Load a canonical intent receipt by composite key.

        Returns the receipt dict with verified integrity, or None.
        Also verifies the payload exists and digest-matches.
        A receipt pointing to a missing or corrupt payload returns None.
        """
        intent_id = _compute_intent_id(recovery_receipt_sha256, payload_digest)
        receipt = self._load_receipt_by_intent_id(intent_id)
        if receipt is None:
            return None
        # Verify self-integrity
        expected = _compute_event_digest(receipt)
        stored = receipt.get("event_digest", "")
        if stored and stored != expected:
            return None
        # Verify payload exists and matches
        receipt_pd = receipt.get("payload_digest", "")
        payload = self._payload_store.get(intent_id)
        if payload is None:
            return None
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        computed = _sha256_data(raw)
        if computed != receipt_pd:
            return None
        receipt["event_digest"] = expected
        return receipt

    def retrieve_payload(
        self, intent_id: str, expected_payload_digest: str
    ) -> dict[str, Any] | None:
        """Retrieve and digest-verify a stored payload.

        Returns the payload dict, or None if not found or digest mismatch.
        """
        payload = self._payload_store.get(intent_id)
        if payload is None:
            return None
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        computed = _sha256_data(raw)
        if computed != expected_payload_digest:
            return None
        return payload

    def intent_exists(self, recovery_receipt_sha256: str, payload_digest: str) -> bool:
        intent_id = _compute_intent_id(recovery_receipt_sha256, payload_digest)
        return self._payload_store.exists(intent_id)

    # ── Internal ───────────────────────────────────────────────

    def _load_receipt_by_intent_id(self, intent_id: str) -> dict[str, Any] | None:
        if not self._receipt_path.exists():
            return None
        with open(self._receipt_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("intent_id") == intent_id:
                    return event
        return None

    def _append_receipt_locked(self, event: dict[str, Any]) -> str:
        """Append receipt when caller holds per-intent lock (no separate lock)."""
        _assert_no_raw_content(event)
        self._validate_receipt_against_schema(event)
        event_digest = _compute_event_digest(event)
        event["event_digest"] = event_digest
        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        with open(self._receipt_path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return event_digest

    def _append_receipt(self, event: dict[str, Any]) -> str:
        """Public receipt append under receipt-lock (for external callers)."""
        _assert_no_raw_content(event)
        self._validate_receipt_against_schema(event)
        event_digest = _compute_event_digest(event)
        event["event_digest"] = event_digest
        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
        with open(self._lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                with open(self._receipt_path, "a") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        return event_digest


def _assert_no_raw_content(event: dict[str, Any]) -> None:
    for key in _FORBIDDEN_RECEIPT_KEYS:
        if key in event:
            raise ValueError(
                f"Intent authority receipt contains forbidden content key: {key}"
            )


__all__ = [
    "DurableRecoveryIntentAuthority",
    "GovernedPayloadStore",
    "MaterializationRequest",
]
