from __future__ import annotations

from datetime import UTC
import json
from pathlib import Path
from typing import Any


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


def load_preparation_receipt(receipt_sha256: str) -> dict[str, Any] | None:
    """Load a preparation receipt by its SHA256."""
    root = _store_root()
    receipt_path = root / f"{receipt_sha256}.json"
    if not receipt_path.exists():
        return None
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception:
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

        # Filter by branch
        if branch is not None and receipt.get("branch") != branch:
            continue

        # Filter by worktree
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

        # Filter by session/task (optional narrowing)
        if session_id is not None and receipt.get("session_id") != session_id:
            continue
        if task_id is not None and receipt.get("task_id") != task_id:
            continue

        # Check expiration
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

    # Sort newest first
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

    # If multiple active receipts, prefer the one whose post_index_tree_digest matches current index
    if current_index_tree_digest is not None:
        for receipt in candidates:
            expected = receipt.get("post_index_tree_digest")
            if expected == current_index_tree_digest:
                return ("valid_index_match", receipt)
        # No match found — report stale against newest
        return ("stale_index_mismatch", candidates[0])

    # No current digest available
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


def _generate_id() -> str:
    import secrets

    return secrets.token_hex(16)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


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

        # Only validation receipts
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


__all__ = [
    "find_active_preparation_receipts",
    "find_active_validation_receipts",
    "generate_validation_receipt",
    "load_preparation_receipt",
    "load_validation_receipt",
    "persist_preparation_receipt",
    "persist_validation_receipt",
    "resolve_best_preparation_receipt",
]
