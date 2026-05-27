"""Deployment evidence ledger for Lane X3.1 publication deployment.

X3.1 repairs: full event-envelope schema validation, nested receipt
digest verification, authoritative/degraded reconstruction, corrupt-row
reporting, conflict based on governed content not untrusted strings.
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

_EVENT_SCHEMA_PATH = (
    "docs/schemas/rig.relay.publication_deployment_event.v1.schema.json"
)
_RECEIPT_SCHEMA_PATH = (
    "docs/schemas/rig.relay.publication_deployment_evidence.v1.schema.json"
)

_event_schema_cache: dict | None = None
_receipt_schema_cache: dict | None = None


def _resolve_schema_path(rel_path: str) -> Path:
    p = Path(rel_path)
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / rel_path


def _load_event_schema() -> dict:
    global _event_schema_cache
    if _event_schema_cache is not None:
        return _event_schema_cache
    loaded: dict = json.loads(
        _resolve_schema_path(_EVENT_SCHEMA_PATH).read_text("utf-8")
    )
    _event_schema_cache = loaded
    return loaded


def _load_receipt_schema() -> dict:
    global _receipt_schema_cache
    if _receipt_schema_cache is not None:
        return _receipt_schema_cache
    loaded: dict = json.loads(
        _resolve_schema_path(_RECEIPT_SCHEMA_PATH).read_text("utf-8")
    )
    _receipt_schema_cache = loaded
    return loaded


def _validate_receipt_against_schema(receipt: dict) -> None:
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError(
            "Cannot validate deployment receipts: jsonschema is not installed"
        ) from e
    schema = _load_receipt_schema()
    try:
        jsonschema.validate(receipt, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"Deployment receipt failed schema validation: {e.message}"
        ) from e


def _validate_event_against_schema(event: dict) -> None:
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError(
            "Cannot validate deployment events: jsonschema is not installed"
        ) from e
    try:
        schema = _load_event_schema()
    except FileNotFoundError as e:
        raise RuntimeError(
            "Cannot validate deployment events: schema file not found"
        ) from e
    try:
        jsonschema.validate(event, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"Deployment event failed schema validation: {e.message}"
        ) from e


def _compute_governance_digest(receipt: dict[str, Any]) -> str:
    """Governance-scoped digest for conflict detection — only outcome fields."""
    canonical = {
        "deployment_phase": receipt.get("deployment_phase", ""),
        "pages_configured": receipt.get("pages_configured", False),
        "content_published": receipt.get("content_published", False),
        "build_initiated": receipt.get("build_initiated", False),
        "remote_verified": receipt.get("remote_verified", False),
        "refusal_code": receipt.get("refusal_code"),
        "refusal_reasons": sorted(receipt.get("refusal_reasons", [])),
        "preview_evidence_digest": receipt.get("preview_evidence_digest", ""),
        "compilation_result_digest": receipt.get("compilation_result_digest", ""),
        "authorization_receipt_digest": receipt.get("authorization_receipt_digest", ""),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _verify_receipt_digest(receipt: dict[str, Any]) -> None:
    stored = receipt.get("evidence_digest", "")
    canonical = {
        "schema_version": receipt.get("schema_version", ""),
        "receipt_id": receipt.get("receipt_id", ""),
        "operation_id": receipt.get("operation_id", ""),
        "preparation_digest": receipt.get("preparation_digest", ""),
        "profile_candidate_digest": receipt.get("profile_candidate_digest", ""),
        "preview_evidence_digest": receipt.get("preview_evidence_digest", ""),
        "preview_receipt_digest": receipt.get("preview_receipt_digest", ""),
        "compilation_result_digest": receipt.get("compilation_result_digest", ""),
        "authorization_receipt_digest": receipt.get("authorization_receipt_digest", ""),
        "deployment_phase": receipt.get("deployment_phase", ""),
        "pages_site_url": receipt.get("pages_site_url", ""),
        "pages_build_status": receipt.get("pages_build_status", ""),
        "pages_configured": receipt.get("pages_configured", False),
        "content_published": receipt.get("content_published", False),
        "build_initiated": receipt.get("build_initiated", False),
        "refusal_code": receipt.get("refusal_code"),
        "refusal_reasons": sorted(receipt.get("refusal_reasons", [])),
        "remote_request_sent": receipt.get("remote_request_sent", False),
        "remote_verified": receipt.get("remote_verified", False),
        "remote_verification_digest": receipt.get("remote_verification_digest", ""),
        "recovery_required": receipt.get("recovery_required", False),
        "deployed_at": receipt.get("deployed_at", ""),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    computed = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    if stored and stored != computed:
        raise ValueError(
            f"Receipt evidence digest mismatch: stored={stored[:20]}..., "
            f"computed={computed[:20]}..."
        )


def _compute_event_digest(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _verify_event_digest(event: dict[str, Any]) -> None:
    stored = event.get("event_digest")
    if stored is None:
        raise ValueError("Event missing event_digest")
    computed = _compute_event_digest(event)
    if stored != computed:
        raise ValueError(
            f"Event integrity failure: stored={stored[:20]}..., "
            f"computed={computed[:20]}..."
        )


class DeploymentEvidenceLedger:
    """Append-only JSONL ledger for deployment outcome evidence.

    X3.1 repair #6: full event-envelope validation, nested receipt
    digest verification, authoritative/degraded reconstruction,
    corrupt-row reporting, governance-scoped conflict detection.
    """

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is None:
            ledger_path = DEPLOYMENT_LEDGER_DIR / DEPLOYMENT_LEDGER_FILE
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    def append_event(self, operation_id: str, receipt: DeploymentOutcomeReceipt) -> str:
        """Persist a deployment outcome receipt as a content-light event.

        Returns the event_digest. Under fcntl lock:
        - Validates receipt schema and digest
        - Deduplicates same operation_id + same governance state
        - Conflicts on same operation_id + different governance state
        """
        receipt_data = receipt.model_dump()
        receipt.evidence_digest = receipt.compute_digest()
        receipt_data = receipt.model_dump()

        _validate_receipt_against_schema(receipt_data)
        _verify_receipt_digest(receipt_data)

        event = {
            "schema_version": DEPLOYMENT_EVENT_SCHEMA_VERSION,
            "operation_id": operation_id,
            "created_at": datetime.now(UTC).isoformat(),
            "receipt": receipt_data,
        }
        event_digest = _compute_event_digest(event)
        event["event_digest"] = event_digest

        _validate_event_against_schema(event)

        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"

        with open(self._lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                existing = self._find_under_lock(operation_id)
                if existing is not None:
                    existing_receipt = existing.get("receipt", {})
                    if _compute_governance_digest(
                        receipt_data
                    ) != _compute_governance_digest(existing_receipt):
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

    def load_receipts(self, authoritative: bool = False) -> dict[str, Any]:
        """Load persisted events with full integrity verification.

        Validates: event schema, event digest, receipt schema, receipt digest.
        Returns typed reconstruction result.
        """
        if not self._path.exists():
            return {
                "receipts": [],
                "total_rows": 0,
                "valid_rows": 0,
                "corrupt_rows": 0,
                "corrupt_lines": [],
                "corruption_detected": False,
                "reconstruction_warnings": [],
            }

        receipts: list[dict[str, Any]] = []
        corrupt_lines: list[int] = []
        total = 0
        valid = 0

        with open(self._path) as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                total += 1

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    corrupt_lines.append(line_num)
                    continue

                try:
                    _validate_event_against_schema(event)
                    _verify_event_digest(event)
                    receipt = event.get("receipt", {})
                    _validate_receipt_against_schema(receipt)
                    _verify_receipt_digest(receipt)
                    receipts.append(receipt)
                    valid += 1
                except (ValueError, RuntimeError, KeyError):
                    corrupt_lines.append(line_num)
                    continue

        corrupt_count = len(corrupt_lines)
        corruption_detected = corrupt_count > 0
        warnings: list[str] = []

        if corruption_detected:
            warnings.append(
                f"Ledger {self._path}: {corrupt_count} corrupt/tampered/invalid "
                f"row(s) at lines {corrupt_lines[:10]}"
            )

        if authoritative and corruption_detected:
            return {
                "receipts": [],
                "total_rows": total,
                "valid_rows": 0,
                "corrupt_rows": corrupt_count,
                "corrupt_lines": corrupt_lines,
                "corruption_detected": True,
                "reconstruction_warnings": [
                    "Authoritative reconstruction refused: "
                    f"{corrupt_count} corrupt/tampered/invalid row(s)"
                ],
            }

        return {
            "receipts": receipts,
            "total_rows": total,
            "valid_rows": valid,
            "corrupt_rows": corrupt_count,
            "corrupt_lines": corrupt_lines,
            "corruption_detected": corruption_detected,
            "reconstruction_warnings": warnings,
        }

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
                        _verify_event_digest(event)
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
