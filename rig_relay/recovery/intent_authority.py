"""Durable Recovery Intent Authority v1.

Canonical, digest-validated, policy-bounded executable-input authority
for the recovery execution corridor. The handoff's (recovery_receipt_sha256,
payload_digest) composite key identifies the canonical intent.

Separates content-light intent receipts (in the evidence ledger) from
governed executable payloads (in a separate payload store). No raw tool
arguments, file content, or secrets appear in evidence.

Lazy-first-write semantics: the first digest-verified intent that arrives
at _execute_handoff() is materialized to the canonical authority. Subsequent
retrievals for the same composite key MUST match the canonical payload.
No caller can substitute args after first materialization.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


class GovernedPayloadStore:
    """Separate, digest-verified payload storage.

    Payloads live outside the evidence ledger. Keyed by intent_id.
    Content-light evidence never sees the raw payload — only its digest.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def put(self, intent_id: str, payload: dict[str, Any]) -> str:
        """Store payload. Returns the computed payload_digest."""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = _sha256_data(raw)

        payload_path = self._dir / f"{intent_id}.json"
        lock_path = self._dir / f"{intent_id}.lock"

        with open(lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                payload_path.write_text(raw)
                payload_path.chmod(0o600)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

        return payload_digest

    def get(self, intent_id: str) -> dict[str, Any] | None:
        """Retrieve stored payload. Returns None if not found."""
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

    @property
    def payload_store(self) -> GovernedPayloadStore:
        return self._payload_store

    def materialize_intent(
        self,
        *,
        recovery_receipt_sha256: str,
        payload_digest: str,
        manifest_digest: str,
        canonical_tool_name: str,
        normalized_args: dict[str, Any],
        execution_class: str,
        correlation_id: str = "",
        validation_profile: str | None = None,
        bounded_paths: list[str] | None = None,
        mutation_class: str | None = None,
        materialization_kind: str = "lazy_first_write",
    ) -> str:
        """Materialize a recovery intent.

        Verifies the digest of normalized_args matches payload_digest.
        Persists the content-light receipt and stores the payload.
        Returns the intent_id.

        Raises:
            ValueError: if digest verification fails.
        """
        raw = json.dumps(normalized_args, sort_keys=True, separators=(",", ":"))
        computed = _sha256_data(raw)
        if computed != payload_digest:
            raise ValueError(
                f"Payload digest mismatch: expected {payload_digest[:20]}..., "
                f"computed {computed[:20]}..."
            )

        intent_id = _compute_intent_id(recovery_receipt_sha256, payload_digest)

        # ── Check for existing intent ──────────────────────────
        existing = self._load_receipt_by_intent_id(intent_id)
        if existing is not None:
            # Already materialized — verify stored payload matches
            stored = self._payload_store.get(intent_id)
            if stored is None:
                raise ValueError(
                    f"Intent {intent_id[:20]}... has receipt but no payload"
                )
            stored_raw = json.dumps(stored, sort_keys=True, separators=(",", ":"))
            stored_digest = _sha256_data(stored_raw)
            if stored_digest != payload_digest:
                raise ValueError(
                    f"Intent {intent_id[:20]}... already materialized with "
                    f"different payload"
                )
            return intent_id

        # ── Store payload first (idempotent by digest) ─────────
        self._payload_store.put(intent_id, normalized_args)

        # ── Build and persist content-light receipt ────────────
        receipt_event = {
            "schema_version": "rig.relay.recovery_intent_authority.v1",
            "intent_id": intent_id,
            "recovery_receipt_sha256": recovery_receipt_sha256,
            "payload_digest": payload_digest,
            "manifest_digest": manifest_digest,
            "canonical_tool_name": canonical_tool_name,
            "execution_class": execution_class,
            "correlation_id": correlation_id,
            "validation_profile": validation_profile,
            "bounded_paths": list(bounded_paths) if bounded_paths else [],
            "mutation_class": mutation_class,
            "materialization_kind": materialization_kind,
            "content_light": True,
            "created_at": _utcnow_iso(),
        }
        self._append_receipt(receipt_event)

        return intent_id

    def load_intent(
        self, recovery_receipt_sha256: str, payload_digest: str
    ) -> dict[str, Any] | None:
        """Load a canonical intent receipt by composite key.

        Returns the receipt dict with verified integrity, or None.
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

    def _append_receipt(self, event: dict[str, Any]) -> str:
        _assert_no_raw_content(event)
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


__all__ = ["DurableRecoveryIntentAuthority", "GovernedPayloadStore"]
