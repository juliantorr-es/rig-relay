"""Canonical path-scoped write lock for proposals.

Ensures two concurrent proposals targeting the same file
are serialized. A stale contender sees the updated hash
and refuses rather than overwriting from an invalid baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

_LOCK_TIMEOUT_SECONDS = 300


def acquire_path_lock(
    campaign_id: str, canonical_path: str, proposal_id: str, root: Path
) -> bool:
    """Acquire a path-scoped write lock. Returns True if lock was acquired."""
    lock_dir = root / ".rig" / "relay" / "campaigns" / campaign_id / "path_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe_name = canonical_path.replace("/", "_").replace(".", "_")
    lock_path = lock_dir / f"{safe_name}.lock"

    if lock_path.exists():
        try:
            data = json.loads(lock_path.read_text())
            existing = data.get("proposal_id")
            ts = data.get("timestamp", 0)
            if existing and (time.time() - ts) < _LOCK_TIMEOUT_SECONDS:
                return False  # lock held by another proposal
        except (json.JSONDecodeError, KeyError):
            pass

    lock_path.write_text(
        json.dumps({
            "proposal_id": proposal_id,
            "canonical_path": canonical_path,
            "timestamp": int(time.time()),
        })
    )
    return True


def release_path_lock(campaign_id: str, canonical_path: str, root: Path) -> None:
    """Release a path-scoped write lock."""
    lock_dir = root / ".rig" / "relay" / "campaigns" / campaign_id / "path_locks"
    safe_name = canonical_path.replace("/", "_").replace(".", "_")
    lock_path = lock_dir / f"{safe_name}.lock"
    if lock_path.exists():
        lock_path.unlink()
