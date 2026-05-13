"""Rig Relay Coordination Lease Cleanup — core module.

Scans coordination leases (path reservations and task claims) for stale,
released, or expired entries and provides cleanup options.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: relay_native (designed for Relay — no Rig origin).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from rig_relay.governance.auth_receipts import validate_receipt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_COORDINATION_ROOT = REPO_ROOT / ".build" / "rig-relay" / "coordination"

CLEANABLE_STATUSES = frozenset({"stale", "released"})


def _parse_iso_datetime(s: str) -> datetime:
    """Parse ISO datetime string, handling 'Z' suffix."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _scan_leases(leases_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Scan lease files and categorize them.

    Returns dict with keys: 'active', 'stale', 'released', 'expired'.
    """
    now = datetime.now(UTC)
    result: dict[str, list[dict[str, Any]]] = {
        "active": [],
        "stale": [],
        "released": [],
        "expired": [],
    }

    for path in sorted(leases_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        data["_path"] = str(path)
        status = data.get("status", "unknown")

        if status in CLEANABLE_STATUSES:
            result[status].append(data)
            continue

        if status == "active":
            expires_at = data.get("expires_at")
            if expires_at:
                try:
                    expires_dt = _parse_iso_datetime(expires_at)
                    if expires_dt < now:
                        result["expired"].append(data)
                        continue
                except (ValueError, TypeError):
                    pass
            result["active"].append(data)

    return result


def _scan_tasks(tasks_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Scan task claim files and categorize them.

    Returns dict with keys: 'active', 'stale', 'released', 'expired'.
    """
    now = datetime.now(UTC)
    result: dict[str, list[dict[str, Any]]] = {
        "active": [],
        "stale": [],
        "released": [],
        "expired": [],
    }

    for path in sorted(tasks_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        data["_path"] = str(path)
        status = data.get("status", "unknown")

        if status in CLEANABLE_STATUSES:
            result[status].append(data)
            continue

        if status == "active":
            expires_at = data.get("expires_at")
            if expires_at:
                try:
                    expires_dt = _parse_iso_datetime(expires_at)
                    if expires_dt < now:
                        result["expired"].append(data)
                        continue
                except (ValueError, TypeError):
                    pass
            result["active"].append(data)

    return result


def _archive_files(files: list[dict[str, Any]], archive_dir: Path) -> list[str]:
    """Move files to archive directory.

    Args:
        files: List of file data dicts with '_path' key.
        archive_dir: Destination archive directory.

    Returns:
        List of error messages.
    """
    errors: list[str] = []
    archive_dir.mkdir(parents=True, exist_ok=True)

    for entry in files:
        src = Path(entry["_path"])
        if not src.is_file():
            continue
        dst = archive_dir / src.name
        try:
            shutil.move(str(src), str(dst))
        except OSError as e:
            errors.append(f"Failed to move {src.name}: {e}")

    return errors


def _delete_files(files: list[dict[str, Any]]) -> list[str]:
    """Delete files permanently.

    Args:
        files: List of file data dicts with '_path' key.

    Returns:
        List of error messages.
    """
    errors: list[str] = []
    for entry in files:
        path = Path(entry["_path"])
        if not path.is_file():
            continue
        try:
            path.unlink()
        except OSError as e:
            errors.append(f"Failed to delete {path.name}: {e}")
    return errors


def _compute_stats(
    leases: dict[str, list[dict[str, Any]]], tasks: dict[str, list[dict[str, Any]]]
) -> dict[str, int]:
    """Compute aggregate statistics."""
    stats: dict[str, int] = {
        "leases_total": sum(len(v) for v in leases.values()),
        "leases_active": len(leases.get("active", [])),
        "leases_stale": len(leases.get("stale", [])),
        "leases_released": len(leases.get("released", [])),
        "leases_expired": len(leases.get("expired", [])),
        "leases_errors": 0,
        "tasks_total": sum(len(v) for v in tasks.values()),
        "tasks_active": len(tasks.get("active", [])),
        "tasks_stale": len(tasks.get("stale", [])),
        "tasks_released": len(tasks.get("released", [])),
        "tasks_expired": len(tasks.get("expired", [])),
        "tasks_errors": 0,
    }
    stats["leases_cleanable"] = (
        stats["leases_stale"] + stats["leases_released"] + stats["leases_expired"]
    )
    stats["tasks_cleanable"] = (
        stats["tasks_stale"] + stats["tasks_released"] + stats["tasks_expired"]
    )
    stats["total_cleanable"] = stats["leases_cleanable"] + stats["tasks_cleanable"]
    return stats


def _print_report(stats: dict[str, int]) -> None:
    """Print a formatted cleanup report."""
    print("Coordination Lease Cleanup Report")
    print("=" * 40)
    print()

    print("Path Reservations (leases/paths/):")
    print(f"  Total:      {stats['leases_total']:>4}")
    print(f"  Active:     {stats['leases_active']:>4}")
    print(f"  Stale:      {stats['leases_stale']:>4}")
    print(f"  Released:   {stats['leases_released']:>4}")
    print(f"  Expired:    {stats['leases_expired']:>4}")
    if stats["leases_errors"]:
        print(f"  Errors:     {stats['leases_errors']:>4}")
    print(f"  Cleanable:  {stats['leases_cleanable']:>4}")
    print()

    print("Task Claims (tasks/):")
    print(f"  Total:      {stats['tasks_total']:>4}")
    print(f"  Active:     {stats['tasks_active']:>4}")
    print(f"  Stale:      {stats['tasks_stale']:>4}")
    print(f"  Released:   {stats['tasks_released']:>4}")
    print(f"  Expired:    {stats['tasks_expired']:>4}")
    if stats["tasks_errors"]:
        print(f"  Errors:     {stats['tasks_errors']:>4}")
    print(f"  Cleanable:  {stats['tasks_cleanable']:>4}")
    print()

    print(f"Total cleanable entries: {stats['total_cleanable']}")


def run_cleanup(
    coordination_root: Path,
    *,
    max_age_seconds: int = 86400,
    dry_run: bool = True,
    archive: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run coordination lease cleanup.

    Args:
        coordination_root: Path to coordination data root.
        max_age_seconds: Maximum age for active leases (default 24h).
        dry_run: If True, only report without making changes.
        archive: If True, move files to archive dir instead of deleting.
        confirm: If True, proceed with cleanup actions.

    Returns:
        Dict with stats and errors.
    """
    leases_dir = coordination_root / "leases" / "paths"
    tasks_dir = coordination_root / "tasks"

    leases = _scan_leases(leases_dir) if leases_dir.is_dir() else {}
    tasks = _scan_tasks(tasks_dir) if tasks_dir.is_dir() else {}

    stats = _compute_stats(leases, tasks)
    errors: list[str] = []

    _print_report(stats)

    if stats["total_cleanable"] == 0:
        print("\nNothing to clean up.")
        return {"stats": stats, "errors": errors, "action": "none"}

    if dry_run:
        print("\n[Dry-run mode — no changes made. Use --confirm to proceed.]")
        return {"stats": stats, "errors": errors, "action": "dry_run"}

    if not confirm:
        print("\n[No changes made. Use --confirm to proceed with cleanup.]")
        return {"stats": stats, "errors": errors, "action": "skipped"}

    cleanable_leases = (
        leases.get("stale", []) + leases.get("released", []) + leases.get("expired", [])
    )
    cleanable_tasks = (
        tasks.get("stale", []) + tasks.get("released", []) + tasks.get("expired", [])
    )

    if archive:
        archive_base = coordination_root / "archived"
        lease_archive = archive_base / "leases" / "paths"
        task_archive = archive_base / "tasks"

        errors.extend(_archive_files(cleanable_leases, lease_archive))
        errors.extend(_archive_files(cleanable_tasks, task_archive))

        print(f"\nArchived {len(cleanable_leases)} lease files to {lease_archive}")
        print(f"Archived {len(cleanable_tasks)} task files to {task_archive}")
        action = "archived"
    else:
        errors.extend(_delete_files(cleanable_leases))
        errors.extend(_delete_files(cleanable_tasks))

        print(f"\nDeleted {len(cleanable_leases)} lease files")
        print(f"Deleted {len(cleanable_tasks)} task files")
        action = "deleted"

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    return {"stats": stats, "errors": errors, "action": action}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean up stale coordination leases and task claims."
    )
    parser.add_argument(
        "--coordination-root",
        type=Path,
        default=DEFAULT_COORDINATION_ROOT,
        help="Path to coordination data root (default: .build/rig-relay/coordination)",
    )
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=86400,
        help="Maximum age in seconds for active leases (default: 86400 = 24h)",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry-run mode: report only, no changes (default).",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        default=False,
        help="Move files to archive dir instead of permanent deletion.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm and proceed with cleanup.",
    )
    parser.add_argument(
        "--authorization-receipt",
        type=Path,
        default=None,
        help="Path to a signed authorization receipt for destructive cleanup.",
    )
    parser.add_argument(
        "--dev-bypass",
        action="store_true",
        default=False,
        help="Skip authorization check (dev mode only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.coordination_root.is_dir():
        print(
            f"Error: Coordination root not found: {args.coordination_root}",
            file=sys.stderr,
        )
        return 1

    if not args.dry_run and args.confirm:
        action = "lease_cleanup.archive" if args.archive else "lease_cleanup.remove"
        if args.authorization_receipt:
            try:
                receipt_data = json.loads(
                    args.authorization_receipt.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as e:
                print(
                    f"Error: Failed to read authorization receipt: {e}", file=sys.stderr
                )
                return 1
            valid, reason = validate_receipt(receipt_data, action)
            if not valid:
                print(
                    f"Error: Authorization refused for '{action}' — {reason}",
                    file=sys.stderr,
                )
                return 1
        elif args.dev_bypass:
            print("Warning: Dev bypass enabled — no real authorization performed.")
        else:
            print(
                f"Error: Destructive cleanup requires --authorization-receipt "
                f"or --dev-bypass for action '{action}'. "
                f"Use --dry-run for safe preview.",
                file=sys.stderr,
            )
            return 1

    result = run_cleanup(
        coordination_root=args.coordination_root,
        max_age_seconds=args.max_age_seconds,
        dry_run=args.dry_run,
        archive=args.archive,
        confirm=args.confirm,
    )

    if result.get("errors"):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
