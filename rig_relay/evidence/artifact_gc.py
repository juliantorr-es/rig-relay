"""Artifact garbage collection — retention-based cleanup for .build/rig-relay/.

Core GC logic extracted from scripts/rig_relay_gc_artifacts.py so the
package does not import from scripts. The script is now a thin CLI adapter.

Content-light: never reads source code, secrets, or user data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
from typing import Any

from rig_relay.core.paths import is_confidential_artifact_path

# ── Budget defaults ─────────────────────────────────────────────────────

DEFAULT_BUDGET: dict[str, Any] = {
    "schema_version": "rig.relay.storage_budget.v1",
    "warn_local_mb": 1024,
    "max_local_mb": 2048,
    "refuse_fleet_over_mb": 4096,
    "raw_observability_days": 3,
    "raw_tool_artifacts_days": 3,
    "coordination_events_days": 14,
    "stale_leases_hours": 24,
    "desktop_projection_snapshots_days": 1,
    "telemetry_bundle_zip_days": 7,
    "derived_jsonl_days": 30,
    "parquet_rollups_days": 365,
    "drive_upload_receipt_days": 7,
    "keep_all_failures": True,
    "keep_all_refusals": True,
    "keep_all_conflicts": True,
    "keep_all_checkpoint_refusals": True,
    "sample_success_rate": 0.05,
    "max_semantic_snippets_per_session": 200,
    "max_command_events_per_session": 5000,
    "warnings": [],
}

PROTECTED_NAMES = (
    "rollup_manifest",
    "export_manifest",
    "receipt",
    "convergence_report",
    "checkpoint_receipt",
)


def _repo_root(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    parts = resolved.parts
    for idx in range(len(parts) - 1):
        if parts[idx] == ".build" and parts[idx + 1] == "rig-relay":
            if idx == 0:
                return Path(resolved.anchor or ".")
            return Path(*parts[:idx])
    if len(resolved.parents) >= 2:
        return resolved.parents[1]
    return resolved.parent

RETENTION_RULES: list[tuple[str, str, list[str] | None, str]] = [
    (
        "coordination/leases",
        "stale_leases_hours",
        None,
        "Stale coordination leases (>24h)",
    ),
    ("coordination/artifacts", "raw_tool_artifacts_days", None, "Raw tool artifacts"),
    (
        "coordination",
        "coordination_events_days",
        [".jsonl"],
        "Coordination events (events.jsonl)",
    ),
    (
        "desktop",
        "desktop_projection_snapshots_days",
        None,
        "Desktop projection snapshots",
    ),
    (
        "telemetry-bundles",
        "telemetry_bundle_zip_days",
        [".zip"],
        "Telemetry bundle zips (keep manifests)",
    ),
    (
        "derived",
        "derived_jsonl_days",
        [".jsonl"],
        "Derived JSONL datasets (only if Parquet exists)",
    ),
    ("reports", "reports_days", None, "Reports"),
    ("chatgpt-bundles", "chatgpt_bundles_days", None, "ChatGPT dev bundles"),
    ("cockpit", "cockpit_days", None, "Cockpit snapshots"),
    ("drive-uploads", "drive_upload_days", None, "Drive upload receipts"),
]

DEFAULT_RETENTION_DAYS: dict[str, int] = {
    "reports_days": 30,
    "chatgpt_bundles_days": 30,
    "cockpit_days": 7,
    "drive_upload_days": 7,
}


def _size_mb(path: Path) -> float:
    repo_root = _repo_root(path)
    if is_confidential_artifact_path(path, repo_root):
        return 0.0
    if path.is_file():
        return path.stat().st_size / 1_048_576.0
    total = 0
    if path.is_dir():
        for f in path.rglob("*"):
            if f.is_file():
                if is_confidential_artifact_path(f, repo_root):
                    continue
                total += f.stat().st_size
    return total / 1_048_576.0


def _is_protected(file_path: Path) -> bool:
    name_lower = file_path.name.lower()
    for protected in PROTECTED_NAMES:
        if protected in name_lower:
            return True
    return False


def _is_active_lease(file_path: Path, stale_hours: int = 24) -> bool:
    if "lease" not in file_path.name.lower():
        return False
    try:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
        return (datetime.now(UTC) - mtime).total_seconds() < (stale_hours * 3600)
    except OSError:
        return False


def _get_budget_key_value(budget: dict[str, Any], key: str) -> int:
    if key in budget:
        val = budget[key]
        if key == "stale_leases_hours":
            return max(1, int(val / 24))
        return int(val)
    return DEFAULT_RETENTION_DAYS.get(key, 30)


def _find_gc_candidates(root: Path, budget: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    candidates: list[dict[str, Any]] = []
    stale_hours = int(budget.get("stale_leases_hours", 24))
    repo_root = _repo_root(root)

    for subdir, budget_key, allowed_exts, description in RETENTION_RULES:
        target = root / subdir
        if not target.is_dir():
            continue

        retention_days = _get_budget_key_value(budget, budget_key)
        cutoff = now - timedelta(days=retention_days)

        if subdir == "coordination/leases":
            hours_cutoff = now - timedelta(hours=stale_hours)
            for f in target.rglob("*"):
                if not f.is_file():
                    continue
                if is_confidential_artifact_path(f, repo_root):
                    continue
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
                except OSError:
                    continue
                if mtime >= hours_cutoff:
                    continue
                if f.name in {"index.json"}:
                    continue
                candidates.append({
                    "path": str(f),
                    "relative_path": str(f.relative_to(root.parent))
                    if f.is_relative_to(root.parent)
                    else str(f),
                    "category": subdir,
                    "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
                    "modified": mtime.isoformat(),
                    "retention_days": retention_days,
                    "description": description,
                    "protected": False,
                })
            continue

        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if is_confidential_artifact_path(f, repo_root):
                continue
            if _is_protected(f):
                continue
            if allowed_exts is not None and f.suffix not in allowed_exts:
                continue
            if _is_active_lease(f, stale_hours):
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            if subdir == "derived" and f.suffix == ".jsonl":
                parquet_path = f.with_suffix(".parquet")
                if not parquet_path.is_file():
                    continue
            candidates.append({
                "path": str(f),
                "relative_path": str(f.relative_to(root.parent))
                if f.is_relative_to(root.parent)
                else str(f),
                "category": subdir,
                "size_mb": round(f.stat().st_size / 1_048_576.0, 3),
                "modified": mtime.isoformat(),
                "retention_days": retention_days,
                "description": description,
                "protected": False,
            })

    candidates.sort(key=lambda x: -x["size_mb"])
    return candidates


def _remove_empty_dirs(root: Path) -> None:
    repo_root = _repo_root(root)
    for dirpath in sorted(root.rglob("*"), key=lambda p: len(str(p)), reverse=True):
        if dirpath.is_dir():
            if is_confidential_artifact_path(dirpath, repo_root):
                continue
            try:
                if not any(dirpath.iterdir()):
                    dirpath.rmdir()
            except OSError:
                pass


def run_artifact_gc(
    root: Path,
    budget: dict[str, Any] | None = None,
    confirm: bool = False,
    force: bool = False,
    archive_dir: Path | None = None,
) -> dict[str, Any]:
    """Run garbage collection on the .build/rig-relay/ artifact tree.

    Args:
        root: Build root directory.
        budget: Storage budget dict. Uses DEFAULT_BUDGET if None.
        confirm: If True, actually delete/archive. If False, dry-run.
        force: If True, skip budget check.
        archive_dir: Optional directory for archiving instead of deleting.

    Returns:
        Dict with GC results: candidates, summary, warnings.
    """
    if budget is None:
        budget = dict(DEFAULT_BUDGET)

    candidates = _find_gc_candidates(root, budget)

    if not candidates:
        return {
            "schema_version": "rig.relay.gc_manifest.v1",
            "build_root": str(root),
            "created_at": datetime.now(UTC).isoformat(),
            "candidates": [],
            "summary": {
                "total_candidates": 0,
                "deleted": 0,
                "archived": 0,
                "skipped": 0,
                "freed_mb": 0.0,
                "dry_run": not confirm,
            },
            "warnings": [],
        }

    results: list[dict[str, Any]] = []
    deleted_count = 0
    archived_count = 0
    skipped_count = 0
    freed_mb = 0.0
    warnings: list[str] = []

    for c in candidates:
        file_path = Path(c["path"])
        if not file_path.is_file():
            skipped_count += 1
            results.append({**c, "action": "skipped (not found)"})
            continue

        if not confirm:
            results.append({**c, "action": "would remove"})
            skipped_count += 1
            continue

        if archive_dir:
            try:
                relative = file_path.relative_to(root)
                archive_target = archive_dir / relative
                archive_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file_path), str(archive_target))
                archived_count += 1
                freed_mb += c["size_mb"]
                results.append({**c, "action": "archived"})
            except (OSError, ValueError) as e:
                warnings.append(f"Failed to archive {file_path}: {e}")
                results.append({**c, "action": f"archive failed: {e}"})
                skipped_count += 1
        else:
            try:
                file_path.unlink()
                deleted_count += 1
                freed_mb += c["size_mb"]
                results.append({**c, "action": "deleted"})
            except OSError as e:
                warnings.append(f"Failed to delete {file_path}: {e}")
                results.append({**c, "action": f"delete failed: {e}"})
                skipped_count += 1

    if confirm and not archive_dir:
        _remove_empty_dirs(root)

    return {
        "schema_version": "rig.relay.gc_manifest.v1",
        "build_root": str(root),
        "created_at": datetime.now(UTC).isoformat(),
        "candidates": results,
        "summary": {
            "total_candidates": len(candidates),
            "deleted": deleted_count,
            "archived": archived_count,
            "skipped": skipped_count,
            "freed_mb": round(freed_mb, 3),
            "dry_run": not confirm,
        },
        "warnings": warnings,
    }


__all__ = ["DEFAULT_BUDGET", "run_artifact_gc"]
