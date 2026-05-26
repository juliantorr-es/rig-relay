from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
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
# ── Immutable Preparation Receipt Lifecycle Events (S4/S5) ────────────
# ═══════════════════════════════════════════════════════════════════════

_LIFECYCLE_SCHEMA_VERSION = "rig.relay.preparation_lifecycle_event.v1"

# ── Lock infrastructure ───────────────────────────────────────────────

_lifecycle_thread_lock = threading.Lock()
_lifecycle_lock_fd: int | None = None


def _acquire_lifecycle_lock() -> None:
    global _lifecycle_lock_fd
    _lifecycle_thread_lock.acquire()
    lock_path = _store_root() / "lifecycle.jsonl.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    if _lifecycle_lock_fd is None:
        _lifecycle_lock_fd = os.open(str(lock_path), os.O_RDWR)
    fcntl.flock(_lifecycle_lock_fd, fcntl.LOCK_EX)


def _release_lifecycle_lock() -> None:
    global _lifecycle_lock_fd
    if _lifecycle_lock_fd is not None:
        fcntl.flock(_lifecycle_lock_fd, fcntl.LOCK_UN)
    _lifecycle_thread_lock.release()


# ── Typed lifecycle load outcomes (S5) ────────────────────────────────


class LifecycleLoadOutcome(StrEnum):
    ABSENT = auto()
    OK = auto()
    CORRUPT_LEDGER = auto()
    INVALID_EVENT = auto()
    INTEGRITY_MISMATCH = auto()
    BROKEN_CHAIN = auto()


@dataclass(slots=True)
class LifecycleLoadResult:
    outcome: LifecycleLoadOutcome
    events: list[Any] = field(default_factory=list)
    status: PreparationLifecycleEventKind | None = None
    error_detail: str = ""

    @property
    def is_ok(self) -> bool:
        return self.outcome == LifecycleLoadOutcome.OK

    @property
    def is_absent(self) -> bool:
        return self.outcome == LifecycleLoadOutcome.ABSENT


# ── Event model ───────────────────────────────────────────────────────


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
    prior_event_digest: str | None = None
    integrity_digest: str = ""

    def recompute_integrity(self) -> str:
        payload = self.model_dump(exclude={"integrity_digest"})
        payload["integrity_digest"] = ""
        payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return _sha256_bytes(payload_data)

    def seal(self) -> None:
        self.integrity_digest = self.recompute_integrity()

    def verify_integrity(self) -> bool:
        return self.integrity_digest == self.recompute_integrity()

    def verify_chain(self, prior: PreparationLifecycleEvent | None) -> bool:
        if prior is None:
            return self.prior_event_digest is None
        return self.prior_event_digest == prior.integrity_digest


# ── Ledger path ───────────────────────────────────────────────────────


def _lifecycle_ledger_path() -> Path:
    return _store_root() / "lifecycle.jsonl"


# ── Append with lock, chain, flush, fsync (S5) ────────────────────────


def append_lifecycle_event(event: PreparationLifecycleEvent) -> str | None:
    """Append an immutable lifecycle event under stable lock, flush, and fsync.

    * Acquires in-process thread lock + fcntl exclusive lock
    * Assigns prior_event_digest from the last event for this receipt
    * Seals integrity_digest
    * Appends to lifecycle.jsonl
    * Flushes and fsyncs the write
    * Verifies the written byte count

    Returns event.event_id on durable success, None on failure.
    """
    try:
        _acquire_lifecycle_lock()
    except Exception:
        return None

    try:
        if not event.event_id:
            event.event_id = secrets.token_hex(16)

        # ── Chain: bind prior digest for this receipt ──
        prior = _last_event_for_receipt(event.preparation_receipt_sha256)
        if prior is not None:
            event.prior_event_digest = prior.integrity_digest

        event.seal()

        ledger = _lifecycle_ledger_path()
        ledger.parent.mkdir(parents=True, exist_ok=True)

        line_bytes = (event.model_dump_json() + "\n").encode("utf-8")
        with open(ledger, "ab") as f:
            pos_before = f.tell()
            f.write(line_bytes)
            f.flush()
            os.fsync(f.fileno())
            pos_after = f.tell()
            expected = len(line_bytes)
            actual = pos_after - pos_before
            if actual != expected:
                from rig_relay.core.logger import logger

                logger.error(
                    "Lifecycle write size mismatch: expected=%d actual=%d",
                    expected,
                    actual,
                )
                return None

        return event.event_id
    except OSError:
        return None
    finally:
        _release_lifecycle_lock()


# ── Read helpers (pre-lock) ───────────────────────────────────────────


def _last_event_for_receipt(receipt_sha256: str) -> PreparationLifecycleEvent | None:
    """Return the last lifecycle event for a receipt (called under lock)."""
    ledger = _lifecycle_ledger_path()
    if not ledger.is_file():
        return None
    last: PreparationLifecycleEvent | None = None
    try:
        with open(ledger, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj: dict[str, Any] = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if obj.get("preparation_receipt_sha256") != receipt_sha256:
                    continue
                try:
                    event = PreparationLifecycleEvent.model_validate(obj)
                except Exception:
                    continue
                if not event.verify_integrity():
                    continue
                last = event
    except OSError:
        pass
    return last


# ── Typed lifecycle load (S5) ─────────────────────────────────────────


def load_lifecycle_events(preparation_receipt_sha256: str) -> LifecycleLoadResult:
    """Load all lifecycle events for a preparation receipt with typed outcomes.

    Fail-closed: corrupt JSON, invalid model, integrity failure, or broken
    chain produces a typed failure outcome. A corrupt ledger is NOT an empty
    ledger — it must not cause a terminal receipt to appear ACTIVE.
    """
    ledger = _lifecycle_ledger_path()
    if not ledger.exists():
        return LifecycleLoadResult(
            outcome=LifecycleLoadOutcome.ABSENT,
            status=PreparationLifecycleEventKind.ACTIVE,
        )

    from rig_relay.core.logger import logger

    events: list[PreparationLifecycleEvent] = []
    try:
        with open(ledger, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj: dict[str, Any] = json.loads(line)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Corrupt lifecycle ledger JSON: %s", exc)
                    return LifecycleLoadResult(
                        outcome=LifecycleLoadOutcome.CORRUPT_LEDGER,
                        error_detail=f"Malformed JSON in lifecycle ledger: {exc}",
                    )

                try:
                    event = PreparationLifecycleEvent.model_validate(obj)
                except Exception as exc:
                    logger.warning("Invalid lifecycle event in ledger: %s", exc)
                    return LifecycleLoadResult(
                        outcome=LifecycleLoadOutcome.INVALID_EVENT,
                        error_detail=f"Invalid lifecycle event model: {exc}",
                    )

                if not event.verify_integrity():
                    logger.warning(
                        "Lifecycle event integrity mismatch: %s", event.event_id
                    )
                    return LifecycleLoadResult(
                        outcome=LifecycleLoadOutcome.INTEGRITY_MISMATCH,
                        error_detail=(
                            f"Lifecycle event {event.event_id} integrity "
                            f"digest mismatch"
                        ),
                    )

                if event.preparation_receipt_sha256 != preparation_receipt_sha256:
                    continue

                # Chain verification: prior_event_digest must match
                # the previous event's integrity_digest
                if events:
                    expected_prior = events[-1].integrity_digest
                    if event.prior_event_digest != expected_prior:
                        logger.warning(
                            "Broken lifecycle chain: event %s expects prior "
                            "%s but got %s",
                            event.event_id,
                            expected_prior,
                            event.prior_event_digest,
                        )
                        return LifecycleLoadResult(
                            outcome=LifecycleLoadOutcome.BROKEN_CHAIN,
                            error_detail=(
                                f"Lifecycle chain broken at event {event.event_id}"
                            ),
                        )

                events.append(event)
    except OSError as exc:
        logger.warning("Cannot read lifecycle ledger: %s", exc)
        return LifecycleLoadResult(
            outcome=LifecycleLoadOutcome.CORRUPT_LEDGER,
            error_detail=f"OS error reading lifecycle ledger: {exc}",
        )

    status = events[-1].event_kind if events else PreparationLifecycleEventKind.ACTIVE
    return LifecycleLoadResult(
        outcome=LifecycleLoadOutcome.OK, events=events, status=status
    )


def read_lifecycle_events(
    preparation_receipt_sha256: str,
) -> list[PreparationLifecycleEvent]:
    """Backward-compatible read — returns events for OK loads, empty list otherwise."""
    result = load_lifecycle_events(preparation_receipt_sha256)
    if result.is_ok:
        return result.events
    return []


def get_lifecycle_status(
    preparation_receipt_sha256: str,
) -> PreparationLifecycleEventKind:
    """Determine the current lifecycle status of a preparation receipt.

    Returns ACTIVE when the ledger is absent or contains no events.
    Returns the most-recent event kind when the ledger is OK.
    Returns ACTIVE for corrupt ledgers (callers should check
    load_lifecycle_events directly for typed outcomes in governed paths).
    """
    result = load_lifecycle_events(preparation_receipt_sha256)
    if result.is_ok and result.status is not None:
        return result.status
    if result.is_absent:
        return PreparationLifecycleEventKind.ACTIVE
    return PreparationLifecycleEventKind.ACTIVE


# ── Scope-based receipt search ────────────────────────────────────────


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

        if receipt.get("branch") != branch:
            continue

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

        receipt_paths = set(receipt.get("prepared_paths", []) or [])
        if not isinstance(receipt_paths, set):
            try:
                receipt_paths = set(receipt_paths)
            except TypeError:
                continue
        if not path_set.intersection(receipt_paths):
            continue

        stored = receipt.get("receipt_sha256", "")
        recomputed = _recompute_receipt_digest(receipt)
        if not stored or stored != recomputed:
            continue

        overlapping.append(receipt)

    overlapping.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return overlapping


def cr_lifecycle_ledger_path() -> Path:
    return _lifecycle_ledger_path()


# ═══════════════════════════════════════════════════════════════════════
# ── Single-Use Transition Lock (A4) ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

# Per-receipt transition locks: one fcntl lock file per preparation
# receipt SHA256.  Held across the full verify → commit → consume
# critical corridor so two concurrent checkpoints cannot race through
# the ACTIVE gate.

_transition_lock_fds: dict[str, int] = {}
_transition_lock_mutex = threading.Lock()


def acquire_transition_lock(preparation_receipt_sha256: str) -> bool:
    """Acquire an exclusive per-receipt transition lock.

    The lock covers the full single-use checkpoint transition:
    re-verify ACTIVE → commit → append CONSUMED → release.

    Returns True on success, False if lock cannot be acquired.
    """
    lock_file = _store_root() / f"transition_{preparation_receipt_sha256}.lock"
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.touch(exist_ok=True)
        fd = os.open(str(lock_file), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        with _transition_lock_mutex:
            _transition_lock_fds[preparation_receipt_sha256] = fd
        return True
    except OSError:
        return False


def release_transition_lock(preparation_receipt_sha256: str) -> None:
    """Release the per-receipt transition lock."""
    with _transition_lock_mutex:
        fd = _transition_lock_fds.pop(preparation_receipt_sha256, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# ── Cross-Evidence Reconciliation (A4) ─────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class ReconciliationOutcome(StrEnum):
    ACTIVE = auto()
    CONSUMED_CONSISTENT = auto()
    TERMINAL_COMMITTED_REPAIRABLE = auto()
    LIFECYCLE_ONLY_NO_TERMINAL = auto()
    DUPLICATE_TERMINAL = auto()
    PREPARATION_INTEGRITY_FAILURE = auto()
    LIFECYCLE_AUTHORITY_CORRUPT = auto()
    GIT_EVIDENCE_AMBIGUOUS = auto()
    UNRECOVERABLE_CONTRADICTION = auto()


@dataclass(slots=True)
class ReconciliationResult:
    outcome: ReconciliationOutcome
    preparation_receipt_sha256: str = ""
    lifecycle_status: PreparationLifecycleEventKind | None = None
    terminal_commit_sha: str | None = None
    committed_head_sha: str | None = None
    error_detail: str = ""
    repairable: bool = False

    @property
    def is_active(self) -> bool:
        return self.outcome == ReconciliationOutcome.ACTIVE

    @property
    def is_consumed(self) -> bool:
        return self.outcome == ReconciliationOutcome.CONSUMED_CONSISTENT

    @property
    def is_repairable(self) -> bool:
        return self.outcome == ReconciliationOutcome.TERMINAL_COMMITTED_REPAIRABLE


def _find_terminal_commit(
    preparation_receipt_sha256: str, repo_root: Path
) -> dict[str, str | bool | None]:
    """Search bounded git history for a commit with structured trailer.

    Uses ``git log --format=%(trailers:only,unfold)`` with
    ``--grep`` for the exact trailer key.  Parses trailer lines for
    ``Rig-Preparation-Receipt-SHA256: value`` and only matches an
    exact value equality.

    Returns ``{"committed_head": sha, "trailer_match": True}`` or
    ``{"committed_head": None, "trailer_match": False}``.
    """
    import subprocess

    trailer_key = "Rig-Preparation-Receipt-SHA256"
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                "-10",
                "--format=%H%n%(trailers:only,unfold)",
                f"--grep={trailer_key}: {preparation_receipt_sha256}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {"committed_head": None, "trailer_match": False}

    if proc.returncode != 0:
        return {"committed_head": None, "trailer_match": False}

    output = proc.stdout.strip()
    if not output:
        return {"committed_head": None, "trailer_match": False}

    lines = output.splitlines()
    if not lines:
        return {"committed_head": None, "trailer_match": False}

    candidate_head = lines[0].strip()
    trailer_lines = lines[1:]

    for line in trailer_lines:
        line = line.strip()
        if ": " not in line:
            continue
        key, _, value = line.partition(": ")
        if key == trailer_key and value == preparation_receipt_sha256:
            return {"committed_head": candidate_head, "trailer_match": True}

    return {"committed_head": None, "trailer_match": False}


def _count_terminal_commits(preparation_receipt_sha256: str, repo_root: Path) -> int:
    """Count git commits with the exact trailer key=value pair."""
    import subprocess

    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                "-10",
                "--format=%H",
                f"--grep=Rig-Preparation-Receipt-SHA256: {preparation_receipt_sha256}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0

    if proc.returncode != 0:
        return 0
    commits = [h for h in proc.stdout.strip().splitlines() if h]
    return len(commits)


def reconcile_receipt_evidence(
    *,
    preparation_receipt_sha256: str,
    branch: str,
    repo_root: Path,
    worktree_root: str = "",
    expected_post_index_digest: str | None = None,
) -> ReconciliationResult:
    """Cross-evidence reconciliation across all durable authorities.

    Reads preparation receipt, lifecycle ledger, and git trailer
    evidence. Produces typed reconciliation outcomes sufficient for
    governed checkpoint and validate decisions.

    Called under the per-receipt transition lock for checkpoint
    operations; callable without lock for read-only validate paths.
    """
    from rig_relay.core.logger import logger

    # 1. Load and integrity-check preparation receipt (S3)
    load_result = load_preparation_receipt_typed(preparation_receipt_sha256)
    if not load_result.is_valid:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.PREPARATION_INTEGRITY_FAILURE,
            preparation_receipt_sha256=preparation_receipt_sha256,
            error_detail=load_result.error_detail,
        )

    receipt = load_result.receipt
    assert receipt is not None

    # Verify branch binding
    receipt_branch = receipt.get("branch", "")
    if receipt_branch and branch and receipt_branch != branch:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.UNRECOVERABLE_CONTRADICTION,
            preparation_receipt_sha256=preparation_receipt_sha256,
            error_detail=f"Branch mismatch: receipt={receipt_branch}, current={branch}",
        )

    # 2. Load lifecycle authority (S5)
    life_result = load_lifecycle_events(preparation_receipt_sha256)
    if not life_result.is_ok and not life_result.is_absent:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.LIFECYCLE_AUTHORITY_CORRUPT,
            preparation_receipt_sha256=preparation_receipt_sha256,
            error_detail=life_result.error_detail,
        )

    life_status = life_result.status
    lifecycle_consumed = (
        life_status == PreparationLifecycleEventKind.CONSUMED if life_status else False
    )
    lifecycle_superseded = (
        life_status == PreparationLifecycleEventKind.SUPERSEDED
        if life_status
        else False
    )
    lifecycle_revoked = (
        life_status == PreparationLifecycleEventKind.REVOKED if life_status else False
    )

    # 3. Terminal Git trailer evidence (A3/A4)
    terminal_count = _count_terminal_commits(preparation_receipt_sha256, repo_root)
    terminal_result = _find_terminal_commit(preparation_receipt_sha256, repo_root)

    # 4. Reconcile
    # ── Terminal lifecycle states (superseded, revoked) are authoritative ──
    if lifecycle_superseded:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.CONSUMED_CONSISTENT,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=life_status,
        )
    if lifecycle_revoked:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.CONSUMED_CONSISTENT,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=life_status,
        )

    # ── Normal reconciliation ──
    # A5: verify terminal commit is reachable from current branch tip
    from rig_relay.governance.checkpoint_transaction import is_commit_reachable

    if not lifecycle_consumed and terminal_count == 0:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.ACTIVE,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=PreparationLifecycleEventKind.ACTIVE,
        )

    if lifecycle_consumed and terminal_count >= 1:
        committed_head: str | None = (
            terminal_result["committed_head"]
            if isinstance(terminal_result["committed_head"], str)
            else None
        )
        if committed_head is None:
            return ReconciliationResult(
                outcome=ReconciliationOutcome.LIFECYCLE_ONLY_NO_TERMINAL,
                preparation_receipt_sha256=preparation_receipt_sha256,
                lifecycle_status=PreparationLifecycleEventKind.CONSUMED,
                error_detail="Lifecycle CONSUMED but no terminal commit identified",
            )
        if not is_commit_reachable(committed_head, branch, repo_root):
            return ReconciliationResult(
                outcome=ReconciliationOutcome.LIFECYCLE_ONLY_NO_TERMINAL,
                preparation_receipt_sha256=preparation_receipt_sha256,
                lifecycle_status=PreparationLifecycleEventKind.CONSUMED,
                terminal_commit_sha=committed_head,
                error_detail=(
                    f"Lifecycle CONSUMED but terminal commit "
                    f"{committed_head[:12]} is not reachable from {branch}"
                ),
            )
        if terminal_count > 1:
            return ReconciliationResult(
                outcome=ReconciliationOutcome.DUPLICATE_TERMINAL,
                preparation_receipt_sha256=preparation_receipt_sha256,
                lifecycle_status=PreparationLifecycleEventKind.CONSUMED,
                terminal_commit_sha=committed_head,
                error_detail=f"Found {terminal_count} terminal commits",
            )
        return ReconciliationResult(
            outcome=ReconciliationOutcome.CONSUMED_CONSISTENT,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=PreparationLifecycleEventKind.CONSUMED,
            terminal_commit_sha=committed_head,
            committed_head_sha=committed_head,
        )

    if terminal_count >= 1 and not lifecycle_consumed:
        committed_head: str | None = (
            terminal_result["committed_head"]
            if isinstance(terminal_result["committed_head"], str)
            else None
        )
        if terminal_count > 1:
            logger.warning(
                "Duplicate terminal evidence for receipt %s: %d commits",
                preparation_receipt_sha256,
                terminal_count,
            )
            return ReconciliationResult(
                outcome=ReconciliationOutcome.DUPLICATE_TERMINAL,
                preparation_receipt_sha256=preparation_receipt_sha256,
                lifecycle_status=life_status,
                terminal_commit_sha=committed_head,
                error_detail=f"Found {terminal_count} terminal commits",
            )
        return ReconciliationResult(
            outcome=ReconciliationOutcome.TERMINAL_COMMITTED_REPAIRABLE,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=PreparationLifecycleEventKind.ACTIVE,
            terminal_commit_sha=committed_head,
            committed_head_sha=committed_head,
            repairable=True,
        )

    if lifecycle_consumed and terminal_count == 0:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.LIFECYCLE_ONLY_NO_TERMINAL,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=PreparationLifecycleEventKind.CONSUMED,
            error_detail="Lifecycle claims CONSUMED but no git commit carries the trailer",
        )

    if terminal_count > 1:
        ch: str | None = (
            terminal_result["committed_head"]
            if isinstance(terminal_result["committed_head"], str)
            else None
        )
        return ReconciliationResult(
            outcome=ReconciliationOutcome.DUPLICATE_TERMINAL,
            preparation_receipt_sha256=preparation_receipt_sha256,
            lifecycle_status=life_status,
            terminal_commit_sha=ch,
            error_detail=f"Found {terminal_count} terminal commits",
        )

    return ReconciliationResult(
        outcome=ReconciliationOutcome.UNRECOVERABLE_CONTRADICTION,
        preparation_receipt_sha256=preparation_receipt_sha256,
        lifecycle_status=life_status,
        error_detail="Unexpected reconciliation state",
    )


__all__ = [
    "LifecycleLoadOutcome",
    "LifecycleLoadResult",
    "PreparationLifecycleEvent",
    "PreparationLifecycleEventKind",
    "PreparationLoadOutcome",
    "PreparationLoadResult",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "acquire_transition_lock",
    "append_lifecycle_event",
    "cr_lifecycle_ledger_path",
    "find_active_preparation_receipts",
    "find_active_receipts_by_scope",
    "find_active_validation_receipts",
    "generate_validation_receipt",
    "get_lifecycle_status",
    "load_lifecycle_events",
    "load_preparation_receipt",
    "load_preparation_receipt_typed",
    "load_validation_receipt",
    "persist_preparation_receipt",
    "persist_validation_receipt",
    "read_lifecycle_events",
    "reconcile_receipt_evidence",
    "release_transition_lock",
    "resolve_best_preparation_receipt",
]
