"""Rig Relay Storage Audit — package-owned reusable implementation.

Content-light storage audit. Inspects the .build/rig-relay/ artifact tree
and reports totals, category sizes, stale leases, rollup/prune candidates,
budget status, and recommendations.

**Never deletes anything.** Read-only inspection.

Originally extracted from scripts/rig_relay_storage_audit.py to close the
reverse-layering gap where production packages (storage_lifecycle.py,
_intents/_storage.py) imported from scripts/.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rig_relay.core.paths import is_confidential_artifact_path

DEFAULT_BUILD_ROOT_NAME: str = "rig-relay"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _default_build_root() -> Path:
    """Return the default build root at .build/rig-relay relative to repo root."""
    return REPO_ROOT / ".build" / DEFAULT_BUILD_ROOT_NAME


CATEGORY_LABELS: dict[str, str] = {
    "coordination": "Coordination (hot)",
    "derived": "Derived datasets (warm)",
    "reports": "Reports (warm)",
    "desktop": "Desktop snapshots (hot)",
    "telemetry-bundles": "Telemetry bundles (hot)",
    "drive-uploads": "Drive uploads (hot)",
    "cockpit": "Cockpit snapshots (warm)",
    "chatgpt-bundles": "ChatGPT bundles (warm)",
}

DEFAULT_BUDGET: dict[str, Any] = {
    "schema_version": "rig.relay.storage_budget.v1",
    "warn_local_mb": 1024,
    "max_local_mb": 2048,
    "refuse_fleet_over_mb": 4096,
    "max_bundle_mb": 250,
    "max_chatgpt_bundle_mb": 512,
    "raw_observability_days": 3,
    "raw_tool_artifacts_days": 3,
    "coordination_events_days": 14,
    "stale_leases_hours": 24,
    "desktop_projection_snapshots_days": 1,
    "telemetry_bundle_zip_days": 7,
    "derived_jsonl_days": 30,
    "parquet_rollups_days": 365,
    "keep_all_failures": True,
    "keep_all_refusals": True,
    "keep_all_conflicts": True,
    "keep_all_checkpoint_refusals": True,
    "sample_success_rate": 0.05,
    "max_semantic_snippets_per_session": 200,
    "max_command_events_per_session": 5000,
    "warnings": [],
}


def _repo_root(build_root: Path) -> Path:
    resolved = build_root.resolve(strict=False)
    parts = resolved.parts
    for idx in range(len(parts) - 1):
        if parts[idx] == ".build" and parts[idx + 1] == "rig-relay":
            if idx == 0:
                return Path(resolved.anchor or ".")
            return Path(*parts[:idx])
    if len(resolved.parents) >= 2:
        return resolved.parents[1]
    return resolved.parent


def _size_mb(path: Path) -> float:
    repo_root = _repo_root(path)
    if is_confidential_artifact_path(path, repo_root):
        return 0.0
    if path.is_file():
        return path.stat().st_size / 1_048_576.0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            if is_confidential_artifact_path(f, repo_root):
                continue
            total += f.stat().st_size
    return total / 1_048_576.0


def _file_count(path: Path) -> int:
    repo_root = _repo_root(path)
    return sum(
        1
        for f in path.rglob("*")
        if f.is_file() and not is_confidential_artifact_path(f, repo_root)
    )


def _largest_files(path: Path, n: int = 10) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    repo_root = _repo_root(path)
    files: list[dict[str, Any]] = []
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        if is_confidential_artifact_path(f, repo_root):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            age_days = (now - mtime).days
        except OSError:
            age_days = 0
        files.append({
            "path": str(
                f.relative_to(path.parent) if f.is_relative_to(path.parent) else f
            ),
            "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
            "modified_days_ago": age_days,
        })
    files.sort(key=lambda x: -x["size_mb"])
    return files[:n]


def _count_stale_leases(leases_dir: Path, stale_hours: int = 24) -> int:
    if not leases_dir.is_dir():
        return 0
    repo_root = _repo_root(leases_dir)
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=stale_hours)
    count = 0
    for f in leases_dir.rglob("*"):
        if not f.is_file():
            continue
        if is_confidential_artifact_path(f, repo_root):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                count += 1
        except OSError:
            pass
    return count


def _find_rollup_candidates(derived_dir: Path) -> list[dict[str, Any]]:
    if not derived_dir.is_dir():
        return []
    repo_root = _repo_root(derived_dir)
    candidates: list[dict[str, Any]] = []
    for f in sorted(derived_dir.iterdir()):
        if f.suffix != ".jsonl":
            continue
        if is_confidential_artifact_path(f, repo_root):
            continue
        parquet_path = f.with_suffix(".parquet")
        candidates.append({
            "source": f.name,
            "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
            "parquet_exists": parquet_path.is_file(),
            "rows": _count_jsonl_rows(f),
        })
    return candidates


def _count_jsonl_rows(path: Path) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except OSError:
        pass
    return count


def _find_prune_candidates(root: Path, budget: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    candidates: list[dict[str, Any]] = []
    repo_root = _repo_root(root)

    retention_map: dict[str, int] = {
        "coordination": budget.get("coordination_events_days", 14),
        "coordination/artifacts": budget.get("raw_tool_artifacts_days", 3),
        "coordination/leases": int(budget.get("stale_leases_hours", 24) / 24) or 1,
        "desktop": budget.get("desktop_projection_snapshots_days", 1),
        "telemetry-bundles": budget.get("telemetry_bundle_zip_days", 7),
        "derived": budget.get("derived_jsonl_days", 30),
        "reports": 30,
        "chatgpt-bundles": 30,
        "cockpit": 7,
        "drive-uploads": 7,
    }

    for subdir, days in retention_map.items():
        target = root / subdir
        if not target.is_dir():
            continue
        cutoff = now - timedelta(days=days)
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if is_confidential_artifact_path(f, repo_root):
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime < cutoff:
                candidate = {
                    "path": str(
                        f.relative_to(root.parent)
                        if f.is_relative_to(root.parent)
                        else f
                    ),
                    "category": subdir,
                    "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
                    "modified": mtime.isoformat(),
                    "retention_days": days,
                }
                name_lower = f.name.lower()
                if "manifest" in name_lower:
                    continue
                if "receipt" in name_lower:
                    continue
                if "convergence" in name_lower:
                    continue
                if subdir == "telemetry-bundles" and f.suffix != ".zip":
                    continue
                candidates.append(candidate)

    candidates.sort(key=lambda x: -x["size_mb"])
    return candidates


def audit_storage(
    root: Path | None = None, budget: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run storage audit and return result dict.

    Args:
        root: Path to .build/rig-relay/ directory. Uses default if None.
        budget: Storage budget dict. Uses DEFAULT_BUDGET if None.

    Returns:
        Dict with categories, totals, budget status, and recommendations.
        Returns a warning dict if root does not exist or is not a directory.
    """
    if root is None:
        root = _default_build_root()
    if not root.is_dir():
        return {
            "schema_version": "rig.relay.storage_audit.v1",
            "build_root": str(root),
            "total_size_mb": 0.0,
            "total_file_count": 0,
            "categories": {},
            "budget": {
                "warn_local_mb": 1024,
                "max_local_mb": 2048,
                "refuse_fleet_over_mb": 4096,
                "status": "unknown",
            },
            "stale_lease_count": 0,
            "largest_files": [],
            "rollup_candidates": [],
            "prune_candidates_count": 0,
            "prune_candidates_total_mb": 0.0,
            "recommendations": [],
        }
    if budget is None:
        budget = dict(DEFAULT_BUDGET)
    repo_root = _repo_root(root)

    categories: dict[str, dict[str, Any]] = {}
    for subdir in sorted(root.iterdir()):
        if not subdir.is_dir():
            continue
        if is_confidential_artifact_path(subdir, repo_root):
            continue
        label = CATEGORY_LABELS.get(subdir.name, subdir.name)
        categories[subdir.name] = {
            "label": label,
            "size_mb": round(_size_mb(subdir), 3),
            "file_count": _file_count(subdir),
        }

    total_size_mb = round(sum(c["size_mb"] for c in categories.values()), 3)

    leases_dir = root / "coordination" / "leases" / "paths"
    stale_lease_count = _count_stale_leases(
        leases_dir, budget.get("stale_leases_hours", 24)
    )

    top_files = _largest_files(root, 10)
    rollup_candidates = _find_rollup_candidates(root / "derived")
    prune_candidates = _find_prune_candidates(root, budget)

    if total_size_mb >= budget.get("refuse_fleet_over_mb", 4096):
        budget_status = "fleet_blocked"
    elif total_size_mb >= budget.get("max_local_mb", 2048):
        budget_status = "over_budget"
    elif total_size_mb >= budget.get("warn_local_mb", 1024):
        budget_status = "warn"
    else:
        budget_status = "ok"

    recommendations: list[str] = []
    if stale_lease_count > 0:
        recommendations.append(
            f"Run lease cleanup: {stale_lease_count} stale lease(s) detected"
        )
    candidates_needing_rollup = [
        c for c in rollup_candidates if not c["parquet_exists"]
    ]
    if candidates_needing_rollup:
        recommendations.append(
            f"Run compaction: {len(candidates_needing_rollup)} JSONL dataset(s) without Parquet"
        )
    if budget_status in {"over_budget", "fleet_blocked"}:
        recommendations.append("Run GC to free storage space")
    if budget_status == "fleet_blocked":
        recommendations.append(
            "BLOCKED: Fleet/delegate execution refused until GC runs"
        )

    return {
        "schema_version": "rig.relay.storage_audit.v1",
        "build_root": str(root),
        "total_size_mb": total_size_mb,
        "total_file_count": sum(c["file_count"] for c in categories.values()),
        "categories": categories,
        "budget": {
            "warn_local_mb": budget.get("warn_local_mb", 1024),
            "max_local_mb": budget.get("max_local_mb", 2048),
            "refuse_fleet_over_mb": budget.get("refuse_fleet_over_mb", 4096),
            "status": budget_status,
        },
        "stale_lease_count": stale_lease_count,
        "largest_files": top_files,
        "rollup_candidates": rollup_candidates,
        "prune_candidates_count": len(prune_candidates),
        "prune_candidates_total_mb": round(
            sum(c["size_mb"] for c in prune_candidates), 3
        ),
        "recommendations": recommendations,
    }


__all__ = ["CATEGORY_LABELS", "DEFAULT_BUDGET", "_default_build_root", "audit_storage"]
