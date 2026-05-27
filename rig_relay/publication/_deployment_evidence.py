"""Deployment evidence ledger for Lane X3 publication deployment.

Extends the PublicationEvidenceLedger pattern with deployment-specific
schemas, dedup semantics, and content-light enforcement. Uses the same
fcntl locking, operation-id dedup, conflict detection architecture.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.publication._deployment_models import DeploymentOutcomeReceipt

DEPLOYMENT_LEDGER_DIR = Path(".build/rig-relay/publication")
DEPLOYMENT_LEDGER_FILE = "publication_deployment_evidence.v1.jsonl"
DEPLOYMENT_EVENT_SCHEMA_VERSION = "rig.relay.publication_deployment_event.v1"

_DEPLOYMENT_EVENT_SCHEMA_PATH = (
    "docs/schemas/rig.relay.publication_deployment_evidence.v1.schema.json"
)

_deployment_schema_cache: dict | None = None


def _resolve_schema_path() -> Path:
    p = Path(_DEPLOYMENT_EVENT_SCHEMA_PATH)
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / _DEPLOYMENT_EVENT_SCHEMA_PATH


def _load_deployment_schema() -> dict:
    global _deployment_schema_cache
    if _deployment_schema_cache is not None:
        return _deployment_schema_cache
    loaded: dict = json.loads(_resolve_schema_path().read_text("utf-8"))
    _deployment_schema_cache = loaded
    return loaded


def _validate_deployment_receipt_against_schema(receipt: dict) -> None:
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError(
            "Cannot validate deployment receipts: jsonschema is not installed"
        ) from e
    try:
        schema = _load_deployment_schema()
    except FileNotFoundError as e:
        raise RuntimeError(
            "Cannot validate deployment receipts: schema file not found"
        ) from e
    try:
        jsonschema.validate(receipt, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"Deployment receipt failed schema validation: {e.message}"
        ) from e


def _compute_event_digest_deployment(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


class DeploymentEvidenceLedger:
    """Append-only JSONL ledger for deployment outcome evidence.

    Schema-validated, content-light, operation-id dedup under fcntl lock.
    Extends the same governance pattern as PublicationEvidenceLedger for
    the deployment domain.
    """

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is None:
            ledger_path = DEPLOYMENT_LEDGER_DIR / DEPLOYMENT_LEDGER_FILE
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    def append_event(self, operation_id: str, receipt: DeploymentOutcomeReceipt) -> str:
        """Persist a deployment outcome receipt as a content-light event.

        Returns the event_digest. Dedup and conflict detection happen
        inside the fcntl lock scope.
        """
        receipt_data = receipt.model_dump()
        if not receipt_data.get("evidence_digest"):
            receipt.evidence_digest = receipt.compute_digest()
            receipt_data = receipt.model_dump()

        event = {
            "schema_version": DEPLOYMENT_EVENT_SCHEMA_VERSION,
            "operation_id": operation_id,
            "created_at": datetime.now(UTC).isoformat(),
            "receipt": receipt_data,
        }
        event_digest = _compute_event_digest_deployment(event)
        event["event_digest"] = event_digest

        _validate_deployment_receipt_against_schema(receipt_data)

        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"

        with open(self._lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                existing = self._find_under_lock(operation_id)
                if existing is not None:
                    existing_receipt = existing.get("receipt", {})
                    if existing_receipt.get("evidence_digest") != receipt_data.get(
                        "evidence_digest"
                    ):
                        raise RuntimeError(
                            f"Operation idempotency conflict: operation_id={operation_id} "
                            f"already terminal with different receipt content"
                        )
                    return existing.get("event_digest", "")

                with open(self._path, "a") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

        return event_digest

    def count_events(self) -> int:
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def _find_under_lock(self, operation_id: str) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        target = f'"operation_id":"{operation_id}"'
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if target in line:
                    try:
                        event = json.loads(line)
                        return event
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        return None


__all__ = [
    "DEPLOYMENT_EVENT_SCHEMA_VERSION",
    "DEPLOYMENT_LEDGER_DIR",
    "DEPLOYMENT_LEDGER_FILE",
    "DeploymentEvidenceLedger",
]
