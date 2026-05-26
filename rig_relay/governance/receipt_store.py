from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PreparationLoadOutcome(StrEnum):
    ABSENT = auto()
    UNREADABLE = auto()
    MALFORMED_JSON = auto()
    SCHEMA_INVALID = auto()
    INTEGRITY_MISMATCH = auto()
    LOADED_VALID = auto()


@dataclass(slots=True)
class PreparationLoadResult:
    outcome: PreparationLoadOutcome
    receipt: dict[str, Any] | None = None
    error_detail: str = ""
    receipt_sha256: str = ""

    @property
    def is_valid(self) -> bool:
        return self.outcome == PreparationLoadOutcome.LOADED_VALID

    @property
    def is_absent(self) -> bool:
        return self.outcome == PreparationLoadOutcome.ABSENT


def _self_dogfood_store_root() -> Path:
    """Current self-dogfood: .build/rig-relay/desktop/preparation-receipts"""
    return Path(".build/rig-relay/desktop/preparation-receipts")


def _desktop_store_root() -> Path | None:
    """Future desktop: RigApplicationPaths under Application Support. Not yet implemented."""
    return None


def _store_root() -> Path:
    desktop = _desktop_store_root()
    if desktop is not None:
        return desktop
    return _self_dogfood_store_root()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _generate_id() -> str:
    return secrets.token_hex(16)


def _recompute_receipt_digest(receipt: dict[str, Any]) -> str:
    """Recompute the canonical receipt digest from receipt fields.

    Matches the generation contract: receipt_sha256 is set to ""
    before serialization, exactly as generate_preparation_receipt does.
    """
    payload = {**receipt, "receipt_sha256": ""}
    payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
    return _sha256_bytes(payload_data)


def persist_preparation_receipt(receipt: dict[str, Any]) -> str | None:
    """Persist a preparation receipt. Returns file path or None."""
    root = _store_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        receipt_path = root / f"{receipt['receipt_sha256']}.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return str(receipt_path)
    except Exception:
        return None


def load_preparation_receipt_typed(receipt_sha256: str) -> PreparationLoadResult:
    """Load a preparation receipt with typed outcome discrimination.

    Distinguishes: absent, unreadable, malformed_json, schema_invalid,
    integrity_mismatch, and loaded_valid.

    A receipt whose stored receipt_sha256 does not match a recomputed
    canonical digest yields integrity_mismatch.
    """
    from rig_relay.core.logger import logger

    root = _store_root()
    receipt_path = root / f"{receipt_sha256}.json"

    if not receipt_path.exists():
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.ABSENT,
            receipt_sha256=receipt_sha256,
            error_detail="Receipt file does not exist",
        )

    try:
        raw_bytes = receipt_path.read_bytes()
    except OSError as exc:
        logger.warning("Cannot read preparation receipt %s: %s", receipt_sha256, exc)
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.UNREADABLE,
            receipt_sha256=receipt_sha256,
            error_detail=f"OS error reading receipt file: {exc}",
        )

    try:
        receipt: dict[str, Any] = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "Malformed JSON in preparation receipt %s: %s", receipt_sha256, exc
        )
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.MALFORMED_JSON,
            receipt_sha256=receipt_sha256,
            error_detail=f"JSON decode failed: {exc}",
        )

    if not isinstance(receipt, dict):
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.SCHEMA_INVALID,
            receipt_sha256=receipt_sha256,
            error_detail="Receipt payload is not a JSON object",
        )

    required_keys = {"schema_version", "receipt_sha256", "created_at"}
    missing = required_keys - receipt.keys()
    if missing:
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.SCHEMA_INVALID,
            receipt_sha256=receipt_sha256,
            error_detail=f"Missing required receipt keys: {sorted(missing)}",
        )

    schema_version = receipt.get("schema_version")
    if schema_version != "rig.relay.checkpoint_preparation_receipt.v1":
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.SCHEMA_INVALID,
            receipt_sha256=receipt_sha256,
            error_detail=f"Unknown schema_version: {schema_version}",
        )

    # ── Integrity: recompute canonical digest, compare with stored receipt_sha256 ──
    stored_digest = receipt.get("receipt_sha256", "")
    recomputed = _recompute_receipt_digest(receipt)
    if not stored_digest or stored_digest != recomputed:
        logger.warning(
            "Integrity mismatch for preparation receipt %s: stored=%s recomputed=%s",
            receipt_sha256,
            stored_digest,
            recomputed,
        )
        return PreparationLoadResult(
            outcome=PreparationLoadOutcome.INTEGRITY_MISMATCH,
            receipt_sha256=receipt_sha256,
            error_detail=(
                f"Stored receipt_sha256 ({stored_digest}) does not match "
                f"recomputed digest ({recomputed})"
            ),
        )

    return PreparationLoadResult(
        outcome=PreparationLoadOutcome.LOADED_VALID,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
    )


def load_preparation_receipt(receipt_sha256: str) -> dict[str, Any] | None:
    """Load a preparation receipt by its SHA256.

    Thin backward-compatible wrapper around load_preparation_receipt_typed.
    Returns None for any non-valid outcome.
    """
    result = load_preparation_receipt_typed(receipt_sha256)
    if result.is_valid:
        return result.receipt
    return None


def find_active_preparation_receipts(
    *,
    branch: str | None = None,
    worktree_root: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """Find active preparation receipts matching the given bindings.

    Returns receipts sorted by created_at descending (newest first).
    Does NOT check index tree digest — callers must verify that.
    """
    root = _store_root()
    if not root.exists():
        return []

    receipts: list[dict[str, Any]] = []
    for f in sorted(root.glob("*.json")):
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        if branch is not None and receipt.get("branch") != branch:
            continue

        if worktree_root is not None:
            receipt_wt = receipt.get("worktree_root")
            if receipt_wt is not None:
                try:
                    if str(Path(receipt_wt).resolve()) != str(
                        Path(worktree_root).resolve()
                    ):
                        continue
                except Exception:
                    if str(receipt_wt) != str(worktree_root):
                        continue

        if session_id is not None and receipt.get("session_id") != session_id:
            continue
        if task_id is not None and receipt.get("task_id") != task_id:
            continue

        expires_at = receipt.get("expires_at")
        if expires_at is not None:
            try:
                from datetime import datetime

                expiry = datetime.fromisoformat(expires_at)
                if datetime.now(UTC) > expiry:
                    continue
            except (ValueError, TypeError):
                continue

        receipts.append(receipt)

    receipts.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return receipts


def resolve_best_preparation_receipt(
    *,
    branch: str | None = None,
    worktree_root: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    current_index_tree_digest: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Find the best matching preparation receipt and determine status.

    Returns (status, receipt_or_none).
    Status values: valid_index_match, stale_index_mismatch, expired, absent, ambiguous, not_evaluated, invalid.
    """
    candidates = find_active_preparation_receipts(
        branch=branch,
        worktree_root=worktree_root,
        session_id=session_id,
        task_id=task_id,
    )

    if not candidates:
        return ("absent", None)

    if current_index_tree_digest is not None:
        for receipt in candidates:
            expected = receipt.get("post_index_tree_digest")
            if expected == current_index_tree_digest:
                return ("valid_index_match", receipt)
        return ("stale_index_mismatch", candidates[0])

    if len(candidates) > 1:
        return ("ambiguous", candidates[0])
    return ("valid_index_match", candidates[0])


def generate_validation_receipt(
    *,
    preparation_receipt_sha256: str,
    prepared_index_tree_digest: str | None = None,
    validation_profile: str = "",
    validation_outcome: str = "passed",
    worktree_matched_prepared_index: bool = False,
    untracked_observation_status: str = "not_evaluated",
    observed_worktree_policy: str = "strict_bound_validation_v1",
    exclusion_categories: list[str] | None = None,
    branch: str = "",
    worktree_root: str | None = None,
    session_id: str = "",
    task_id: str = "",
    mission_id: str | None = None,
    claim_id: str | None = None,
    authority_provenance_sha256: str | None = None,
    ignored_disposable_exclusion_categories: list[str] | None = None,
    ignored_observable_candidate_count: int = 0,
    ignored_disposable_count: int = 0,
    unknown_ignored_count: int = 0,
    observable_input_policy_version: str = "1.0",
) -> dict[str, Any]:
    """Generate a durable validation receipt bound to a preparation receipt."""
    from datetime import datetime

    now = datetime.now(UTC)

    receipt: dict[str, Any] = {
        "schema_version": "rig.relay.prepared_index_validation_receipt.v1",
        "validation_id": _generate_id(),
        "created_at": now.isoformat(),
        "preparation_receipt_sha256": preparation_receipt_sha256,
        "prepared_index_tree_digest": prepared_index_tree_digest,
        "validation_profile": validation_profile,
        "validation_outcome": validation_outcome,
        "worktree_matched_prepared_index": worktree_matched_prepared_index,
        "untracked_observation_status": untracked_observation_status,
        "observed_worktree_policy": observed_worktree_policy,
        "exclusion_categories": exclusion_categories or [],
        "ignored_disposable_exclusion_categories": ignored_disposable_exclusion_categories
        or [],
        "ignored_observable_candidate_count": ignored_observable_candidate_count,
        "ignored_disposable_count": ignored_disposable_count,
        "unknown_ignored_count": unknown_ignored_count,
        "observable_input_policy_version": observable_input_policy_version,
        "branch": branch,
        "worktree_root": worktree_root,
        "session_id": session_id,
        "task_id": task_id,
        "mission_identity": mission_id,
        "claim_id": claim_id,
        "authority_provenance_sha256": authority_provenance_sha256,
        "authorization_source": "mission_execution_authority",
        "expires_at": None,
        "receipt_sha256": "",
    }

    receipt_data = json.dumps(receipt, sort_keys=True).encode("utf-8")
    receipt["receipt_sha256"] = _sha256_bytes(receipt_data)
    return receipt


def persist_validation_receipt(receipt: dict[str, Any]) -> str | None:
    """Persist a validation receipt. Returns file path or None."""
    root = _store_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        receipt_path = root / f"{receipt['receipt_sha256']}.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return str(receipt_path)
    except Exception:
        return None


def load_validation_receipt(receipt_sha256: str) -> dict[str, Any] | None:
    """Load a validation receipt by its SHA256."""
    root = _store_root()
    receipt_path = root / f"{receipt_sha256}.json"
    if not receipt_path.exists():
        return None
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_active_validation_receipts(
    *,
    preparation_receipt_sha256: str | None = None,
    branch: str | None = None,
    worktree_root: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """Find active validation receipts matching bindings."""
    root = _store_root()
    if not root.exists():
        return []

    receipts: list[dict[str, Any]] = []
    for f in sorted(root.glob("*.json")):
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        if (
            receipt.get("schema_version")
            != "rig.relay.prepared_index_validation_receipt.v1"
        ):
            continue

        if (
            preparation_receipt_sha256
            and receipt.get("preparation_receipt_sha256") != preparation_receipt_sha256
        ):
            continue
        if branch and receipt.get("branch") != branch:
            continue
        if worktree_root:
            receipt_wt = receipt.get("worktree_root")
            if receipt_wt:
                try:
                    if str(Path(receipt_wt).resolve()) != str(
                        Path(worktree_root).resolve()
                    ):
                        continue
                except Exception:
                    if str(receipt_wt) != str(worktree_root):
                        continue
        if session_id and receipt.get("session_id") != session_id:
            continue
        if task_id and receipt.get("task_id") != task_id:
            continue

        expires_at = receipt.get("expires_at")
        if expires_at:
            try:
                from datetime import datetime

                expiry = datetime.fromisoformat(expires_at)
                if datetime.now(UTC) > expiry:
                    continue
            except (ValueError, TypeError):
                continue

        receipts.append(receipt)

    receipts.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return receipts


# ═══════════════════════════════════════════════════════════════════════
# ── Immutable Preparation Receipt Lifecycle Events (S4) ───────────────
# ═══════════════════════════════════════════════════════════════════════

_LIFECYCLE_SCHEMA_VERSION = "rig.relay.preparation_lifecycle_event.v1"


class PreparationLifecycleEventKind(StrEnum):
    ACTIVE = auto()
    CONSUMED = auto()
    SUPERSEDED = auto()
    REVOKED = auto()


class PreparationLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = _LIFECYCLE_SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: secrets.token_hex(16))
    event_kind: PreparationLifecycleEventKind
    preparation_receipt_sha256: str
    branch: str = ""
    worktree_root: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    producer: str = ""
    committed_head_sha: str | None = None
    superseded_by_receipt_sha256: str | None = None
    integrity_digest: str = ""

    def recompute_integrity(self) -> str:
        payload = self.model_dump(exclude={"integrity_digest"})
        payload["integrity_digest"] = ""
        payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return _sha256_bytes(payload_data)

    def seal(self) -> None:
        self.integrity_digest = self.recompute_integrity()


def _lifecycle_ledger_path() -> Path:
    return _store_root() / "lifecycle.jsonl"


def append_lifecycle_event(event: PreparationLifecycleEvent) -> str | None:
    """Append an immutable lifecycle event to the canonical JSONL ledger.

    Returns the event_id on success, None on failure.
    The event is sealed with an integrity digest before writing.
    """
    event.seal()
    ledger = _lifecycle_ledger_path()
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json() + "\n"
        with open(ledger, "a") as f:
            f.write(line)
        return event.event_id
    except OSError:
        return None


def read_lifecycle_events(
    preparation_receipt_sha256: str,
) -> list[PreparationLifecycleEvent]:
    """Read all lifecycle events for a preparation receipt.

    Returns events in append order (oldest first).
    Malformed lines are silently skipped.
    """
    ledger = _lifecycle_ledger_path()
    if not ledger.exists():
        return []
    events: list[PreparationLifecycleEvent] = []
    with open(ledger) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj: dict[str, Any] = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if obj.get("preparation_receipt_sha256") != preparation_receipt_sha256:
                continue
            try:
                event = PreparationLifecycleEvent.model_validate(obj)
            except Exception:
                continue
            events.append(event)
    return events


def get_lifecycle_status(
    preparation_receipt_sha256: str,
) -> PreparationLifecycleEventKind:
    """Determine the current lifecycle status of a preparation receipt.

    Returns the most-recent terminal lifecycle event kind, or ACTIVE
    if no lifecycle event has been recorded.

    Terminal events are CONSUMED, SUPERSEDED, and REVOKED.
    Multiple events may exist (e.g., superseded then later revoked);
    the last event in the ledger determines the outcome.
    """
    events = read_lifecycle_events(preparation_receipt_sha256)
    if not events:
        return PreparationLifecycleEventKind.ACTIVE
    return events[-1].event_kind


def find_active_receipts_by_scope(
    *, branch: str, worktree_root: str, prepared_paths: list[str]
) -> list[dict[str, Any]]:
    """Find preparation receipts whose prepared paths overlap with the given scope.

    Used to identify candidates for supersession when a new preparation
    receipt is created. Only returns receipts stored on disk that pass
    S3 integrity checks. Lifecycle checks are left to callers.
    """
    root = _store_root()
    if not root.exists():
        return []

    path_set = set(prepared_paths)
    overlapping: list[dict[str, Any]] = []

    for f in sorted(root.glob("*.json")):
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(receipt, dict):
            continue
        if (
            receipt.get("schema_version")
            != "rig.relay.checkpoint_preparation_receipt.v1"
        ):
            continue

        # Same branch binding
        if receipt.get("branch") != branch:
            continue

        # Same worktree
        receipt_wt = receipt.get("worktree_root", "")
        if receipt_wt:
            try:
                if str(Path(receipt_wt).resolve()) != str(
                    Path(worktree_root).resolve()
                ):
                    continue
            except Exception:
                if str(receipt_wt) != str(worktree_root):
                    continue

        # Skip receipts whose scope is completely disjoint
        receipt_paths = set(receipt.get("prepared_paths", []) or [])
        if not isinstance(receipt_paths, set):
            try:
                receipt_paths = set(receipt_paths)
            except TypeError:
                continue
        if not path_set.intersection(receipt_paths):
            continue

        # S3 integrity check via recomputed digest
        stored = receipt.get("receipt_sha256", "")
        recomputed = _recompute_receipt_digest(receipt)
        if not stored or stored != recomputed:
            continue

        overlapping.append(receipt)

    overlapping.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return overlapping


def cr_lifecycle_ledger_path() -> Path:
    return _lifecycle_ledger_path()


__all__ = [
    "PreparationLifecycleEvent",
    "PreparationLifecycleEventKind",
    "PreparationLoadOutcome",
    "PreparationLoadResult",
    "append_lifecycle_event",
    "cr_lifecycle_ledger_path",
    "find_active_preparation_receipts",
    "find_active_receipts_by_scope",
    "find_active_validation_receipts",
    "generate_validation_receipt",
    "get_lifecycle_status",
    "load_preparation_receipt",
    "load_preparation_receipt_typed",
    "load_validation_receipt",
    "persist_preparation_receipt",
    "persist_validation_receipt",
    "read_lifecycle_events",
    "resolve_best_preparation_receipt",
]
