#!/usr/bin/env python3
"""Rig Relay Storage Audit — thin CLI wrapper.

Core implementation is in ``rig_relay.evidence._storage_audit``.

Usage:
    uv run python scripts/rig_relay_storage_audit.py
    uv run python scripts/rig_relay_storage_audit.py --root .build/rig-relay --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from rig_relay.evidence._storage_audit import (
    DEFAULT_BUDGET,
    _default_build_root,
    audit_storage,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Rig Relay build artifacts and compute storage budget status. Never deletes anything."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_build_root(),
        help=f"Build root directory (default: {_default_build_root()})",
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


def main(argv: list[str] | None = None) -> int:
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
