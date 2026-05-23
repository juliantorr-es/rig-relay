#!/usr/bin/env python3
"""Rig Relay Storage Audit.

Inspects the .build/rig-relay/ artifact tree and reports:
- Total size, size by top-level category, file counts, largest files
- Stale lease counts
- Rollup candidates and prune candidates
- Budget status: ok|warn|over_budget|fleet_blocked
- Recommendations (run lease cleanup, run compaction, run GC, block fleet)

**Never deletes anything.** This is a read-only inspection tool.

Usage:
    uv run python scripts/rig_relay_storage_audit.py
    uv run python scripts/rig_relay_storage_audit.py --root .build/rig-relay --budget warn_local_mb=1024 --output /tmp/audit.json
    uv run python scripts/rig_relay_storage_audit.py --json

Content-light: never reads source code, secrets, or user data.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any

from rig_relay.core.paths import is_confidential_artifact_path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
DEFAULT_BUDGET_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.storage_budget.v1.schema.json"
)

# ── Budget defaults (used when no budget file is found) ─────────────────

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

# ── Category labels for known subdirectories ────────────────────────────

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
    """Return directory/file size in MB."""
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
    """Count files recursively."""
    repo_root = _repo_root(path)
    return sum(
        1
        for f in path.rglob("*")
        if f.is_file() and not is_confidential_artifact_path(f, repo_root)
    )


def _largest_files(path: Path, n: int = 10) -> list[dict[str, Any]]:
    """Return the n largest files as [{path, size_mb, modified_days_ago}]."""
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
    """Count lease files older than stale_hours."""
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
    """Find JSONL files in derived/ that have no corresponding .parquet."""
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
    """Find files older than their category retention."""
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
                # Protected classes exclusion
                name_lower = f.name.lower()
                if "manifest" in name_lower:
                    continue
                if "receipt" in name_lower:
                    continue
                if "convergence" in name_lower:
                    continue
                # Only delete telemetry zips, keep manifest
                if subdir == "telemetry-bundles" and f.suffix != ".zip":
                    continue
                candidates.append(candidate)

    candidates.sort(key=lambda x: -x["size_mb"])
    return candidates


def audit_storage(
    root: Path = DEFAULT_BUILD_ROOT, budget: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run storage audit and return result dict.

    Args:
        root: Path to .build/rig-relay/ directory.
        budget: Storage budget dict. Uses DEFAULT_BUDGET if None.

    Returns:
        Dict with categories, totals, budget status, and recommendations.
    """
    if budget is None:
        budget = dict(DEFAULT_BUDGET)
    repo_root = _repo_root(root)

    # Category sizes
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

    # Stale leases
    leases_dir = root / "coordination" / "leases" / "paths"
    stale_lease_count = _count_stale_leases(
        leases_dir, budget.get("stale_leases_hours", 24)
    )

    # Largest files
    top_files = _largest_files(root, 10)

    # Rollup candidates
    rollup_candidates = _find_rollup_candidates(root / "derived")

    # Prune candidates
    prune_candidates = _find_prune_candidates(root, budget)

    # Budget status
    if total_size_mb >= budget.get("refuse_fleet_over_mb", 4096):
        budget_status = "fleet_blocked"
    elif total_size_mb >= budget.get("max_local_mb", 2048):
        budget_status = "over_budget"
    elif total_size_mb >= budget.get("warn_local_mb", 1024):
        budget_status = "warn"
    else:
        budget_status = "ok"

    # Recommendations
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

    result: dict[str, Any] = {
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
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Rig Relay build artifacts and compute storage budget status. Never deletes anything."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BUILD_ROOT,
        help=f"Build root directory (default: {DEFAULT_BUILD_ROOT})",
    )
    parser.add_argument(
        "--budget",
        type=Path,
        default=None,
        help="Path to storage budget JSON file (default: uses embedded defaults)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable report",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write JSON output to file"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915
    args = _parse_args(argv)

    root = args.root
    if not root.is_dir():
        print(f"ERROR: Build root not found: {root}", file=sys.stderr)
        return 1

    budget: dict[str, Any] | None = None
    if args.budget and args.budget.is_file():
        try:
            budget = json.loads(args.budget.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: Could not load budget file: {e}", file=sys.stderr)
            budget = None

    result = audit_storage(root=root, budget=budget)

    if args.json or args.output:
        json_output = json.dumps(result, indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json_output, encoding="utf-8")
            print(f"Audit written to {args.output}")
        if args.json:
            print(json_output)
        return 0

    # Human-readable report
    print("=== Rig Relay Storage Audit ===")
    print(f"Build root: {result['build_root']}")
    print(f"Total size: {result['total_size_mb']:.1f} MB")
    print(f"Total files: {result['total_file_count']}")
    print()
    print("--- Categories ---")
    for _name, cat in sorted(result["categories"].items()):
        print(
            f"  {cat['label']:35s} {cat['size_mb']:>8.1f} MB  {cat['file_count']:>5d} files"
        )
    print()
    print(f"--- Budget Status: {result['budget']['status'].upper()} ---")
    print(f"  Warn:     {result['budget']['warn_local_mb']:>5d} MB")
    print(f"  Max:      {result['budget']['max_local_mb']:>5d} MB")
    print(f"  Fleet:    {result['budget']['refuse_fleet_over_mb']:>5d} MB")
    print(f"  Current:  {result['total_size_mb']:>5.1f} MB")
    print()
    print(f"Stale leases: {result['stale_lease_count']}")
    print()
    if result["largest_files"]:
        print("--- Largest Files ---")
        for f in result["largest_files"][:5]:
            print(
                f"  {f['size_mb']:>8.3f} MB  {f['modified_days_ago']:>3d}d  {f['path']}"
            )
        print()
    if result["rollup_candidates"]:
        print("--- Rollup Candidates ---")
        for c in result["rollup_candidates"]:
            status = "✓" if c["parquet_exists"] else " "
            print(
                f"  [{status}] {c['source']:45s} "
                f"{c['size_mb']:>6.2f} MB  {c['rows']:>6d} rows"
            )
        print()
    if result["prune_candidates_count"] > 0:
        print(
            f"Prune candidates: {result['prune_candidates_count']} files "
            f"({result['prune_candidates_total_mb']:.1f} MB)"
        )
        print()
    if result["recommendations"]:
        print("--- Recommendations ---")
        for r in result["recommendations"]:
            print(f"  → {r}")
        print()
    print("(Read-only — nothing was deleted)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
