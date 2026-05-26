"""Rig Relay Storage Lifecycle — reusable helper.

Content-light storage audit summary for use by current_state, projection,
and fleet preflight hooks. Wraps the CLI audit logic into an importable helper
that returns compact content-light fields only.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: relay_native (no Rig origin — designed for Relay).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.evidence._storage_audit import audit_storage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"


def _get_largest_category(result: dict[str, Any]) -> str:
    """Return the name of the largest category by size_mb."""
    categories = result.get("categories", {})
    if not categories:
        return ""
    return max(categories, key=lambda k: categories[k]["size_mb"])


def compute_storage_summary(build_root: Path | None = None) -> dict[str, Any]:
    """Compute a content-light storage summary.

    Args:
        build_root: Path to .build/rig-relay directory. Uses default if None.

    Returns:
        Dict with content-light storage fields. If root is missing,
        returns a warning dict rather than failing.
    """
    root = build_root or DEFAULT_BUILD_ROOT

    if not root.is_dir():
        return {
            "budget_status": "unknown",
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "category_count": 0,
            "largest_category": "",
            "rollup_candidate_count": 0,
            "prune_candidate_count": 0,
            "stale_lease_count": 0,
            "recommendations": [],
            "warnings": [f"Build root not found: {root}"],
        }

    result = audit_storage(root=root)

    total_size_bytes = 0
    for cat in result.get("categories", {}).values():
        total_size_bytes += int(cat.get("size_mb", 0) * 1_048_576)

    return {
        "budget_status": result.get("budget", {}).get("status", "unknown"),
        "total_size_bytes": total_size_bytes,
        "total_size_mb": result.get("total_size_mb", 0.0),
        "category_count": len(result.get("categories", {})),
        "largest_category": _get_largest_category(result),
        "rollup_candidate_count": len(result.get("rollup_candidates", [])),
        "prune_candidate_count": result.get("prune_candidates_count", 0),
        "stale_lease_count": result.get("stale_lease_count", 0),
        "recommendations": result.get("recommendations", []),
        "warnings": result.get("_warnings", []),
    }


def run_artifact_gc(
    root: Path,
    budget: dict[str, Any] | None = None,
    confirm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Run artifact garbage collection.

    Delegates to rig_relay.evidence.artifact_gc which owns the GC logic.
    """
    from rig_relay.evidence.artifact_gc import run_artifact_gc as _run

    return _run(root=root, budget=budget, confirm=confirm, force=force)
