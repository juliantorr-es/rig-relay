"""Deployment evidence ledger for Lane X3.1 publication deployment.

X3.1 repairs: full event-envelope schema validation, nested receipt
digest verification, authoritative/degraded reconstruction, corrupt-row
reporting, conflict based on governed content not untrusted strings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.publication._deployment_models import (
    PublicationTransitionReceipt,
    _digest_sha256,
)

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
        "transition_phase": receipt.get("transition_phase", ""),
        "transition_preparation_digest": receipt.get(
            "transition_preparation_digest", ""
        ),
        "pages_created": receipt.get("pages_created", False),
        "pages_updated": receipt.get("pages_updated", False),
        "content_published": receipt.get("content_published", False),
        "published_commit_sha": receipt.get("published_commit_sha", ""),
        "git_publication_mode": receipt.get("git_publication_mode", "none"),
        "build_initiated": receipt.get("build_initiated", False),
        "remote_verified": receipt.get("remote_verified", False),
        "build_commit_sha": receipt.get("build_commit_sha", ""),
        "build_commit_matches_published": receipt.get(
            "build_commit_matches_published", False
        ),
        "refusal_code": receipt.get("refusal_code"),
        "refusal_reasons": sorted(receipt.get("refusal_reasons", [])),
        "preview_evidence_digest": receipt.get("preview_evidence_digest", ""),
        "static_bundle_digest": receipt.get("static_bundle_digest", ""),
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
        "transition_preparation_digest": receipt.get(
            "transition_preparation_digest", ""
        ),
        "preview_evidence_digest": receipt.get("preview_evidence_digest", ""),
        "preview_receipt_digest": receipt.get("preview_receipt_digest", ""),
        "static_bundle_digest": receipt.get("static_bundle_digest", ""),
        "authorization_receipt_digest": receipt.get("authorization_receipt_digest", ""),
        "transition_phase": receipt.get("transition_phase", ""),
        "pages_site_url": receipt.get("pages_site_url", ""),
        "pages_build_status": receipt.get("pages_build_status", ""),
        "pages_created": receipt.get("pages_created", False),
        "pages_updated": receipt.get("pages_updated", False),
        "content_publication_manifest_digest": receipt.get(
            "content_publication_manifest_digest", ""
        ),
        "content_published": receipt.get("content_published", False),
        "published_commit_sha": receipt.get("published_commit_sha", ""),
        "git_publication_mode": receipt.get("git_publication_mode", "none"),
        "build_initiated": receipt.get("build_initiated", False),
        "remote_verified": receipt.get("remote_verified", False),
        "remote_verification_digest": receipt.get("remote_verification_digest", ""),
        "build_commit_sha": receipt.get("build_commit_sha", ""),
        "build_commit_matches_published": receipt.get(
            "build_commit_matches_published", False
        ),
        "refusal_code": receipt.get("refusal_code"),
        "refusal_reasons": sorted(receipt.get("refusal_reasons", [])),
        "recovery_required": receipt.get("recovery_required", False),
        "recovery_hint": receipt.get("recovery_hint", ""),
        "target_identity_digest": receipt.get("target_identity_digest", ""),
        "deployed_at": receipt.get("deployed_at", ""),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    computed = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    if not stored:
        raise ValueError("Receipt missing evidence_digest")
    if stored != computed:
        raise ValueError(
            f"Receipt evidence digest mismatch: stored={stored!r} != computed={computed!r}"
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

    @asynccontextmanager
    async def branch_publication_lock(
        self, owner: str, repo: str, branch: str
    ) -> AsyncIterator[Any]:
        """Async context manager for branch-level publication serialization.

        Lock files live in <ledger_dir>/locks/ keyed by sha256(owner/repo:branch).
        Acquires fcntl lock (non-blocking). Yields a context object with
        ``acquired`` bool — False when another process holds the lock.
        """
        lock_dir = self._path.parent / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_id = _digest_sha256(f"{owner}/{repo}:{branch}")
        lock_path = lock_dir / f"{lock_id}.lock"

        acquired = False
        lock_fd = None
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, OSError):
            if lock_fd is not None:
                try:
                    lock_fd.close()
                except OSError:
                    pass
            lock_fd = None

        try:
            yield type("_BranchLockCtx", (), {"acquired": acquired})()
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (ValueError, OSError):
                    pass
                try:
                    lock_fd.close()
                except (ValueError, OSError):
                    pass

    def check_branch_publication_state(
        self, owner: str, repo: str, branch: str, content_digest: str
    ) -> dict:
        """Check if content is already published or pending for this branch.

        Scans evidence ledger for events matching the content digest.
        Returns dict with: already_published, pending_commit_sha,
        conflicting_operation_id, status.
        """
        result: dict = {
            "already_published": False,
            "pending_commit_sha": None,
            "conflicting_operation_id": None,
            "status": "clean",
        }

        reconstruction = self.load_receipts()
        matching_receipts: list[dict] = []
        for receipt_data in reconstruction.get("receipts", []):
            receipt_sbd = receipt_data.get("static_bundle_digest", "")
            if receipt_sbd != content_digest:
                continue

            receipt_target = receipt_data.get("target_identity_digest", "")
            if receipt_target and owner and repo:
                target_digest = _digest_sha256(f"{owner}/{repo}/{branch}")
                if receipt_target != target_digest:
                    continue

            matching_receipts.append(receipt_data)

        if not matching_receipts:
            return result

        for receipt_data in matching_receipts:
            if receipt_data.get("content_published"):
                result["already_published"] = True
                result["pending_commit_sha"] = receipt_data.get(
                    "published_commit_sha", ""
                )
                result["status"] = "already_published"
                return result

        for receipt_data in matching_receipts:
            if receipt_data.get("transition_phase") == "content_publication_prepared":
                result["pending_commit_sha"] = receipt_data.get(
                    "published_commit_sha", ""
                )
                result["conflicting_operation_id"] = receipt_data.get(
                    "operation_id", ""
                )
                result["status"] = "pending"
                return result

        return result

    def append_event(
        self, operation_id: str, receipt: PublicationTransitionReceipt
    ) -> str:
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
                        if event.get("operation_id") != operation_id:
                            continue
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
