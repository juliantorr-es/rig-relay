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


__all__ = [
    "find_active_preparation_receipts",
    "load_preparation_receipt",
    "persist_preparation_receipt",
    "resolve_best_preparation_receipt",
]
