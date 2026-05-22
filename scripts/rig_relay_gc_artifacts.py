#!/usr/bin/env python3
"""Rig Relay Artifact Garbage Collection — CLI entry point.

Thin wrapper over rig_relay.evidence.artifact_gc for command-line use.
All GC business logic lives in the package module.

Usage:
    uv run python scripts/rig_relay_gc_artifacts.py
    uv run python scripts/rig_relay_gc_artifacts.py --root .build/rig-relay --dry-run
    uv run python scripts/rig_relay_gc_artifacts.py --root .build/rig-relay --confirm
    uv run python scripts/rig_relay_gc_artifacts.py --root .build/rig-relay --confirm --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.evidence.artifact_gc import run_artifact_gc

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retention-based garbage collection for Rig Relay build artifacts. "
        "Dry-run by default. Use --confirm to act."
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
        help="Path to storage budget JSON file (default: embedded defaults)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report what would be done without acting (default).",
    )
    parser.add_argument(
        "--confirm",
        action="store_false",
        dest="dry_run",
        help="Actually delete or archive files.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive directory instead of deleting. Files are moved here.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip budget checks (allow GC even if large).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute destructive GC operations. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
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

    confirm = not args.dry_run
    execute = args.execute or confirm
    governed = require_governed_execution_with_evidence(
        script_name="rig_relay_gc_artifacts",
        authority_tier="local_mutation",
        capability_id="artifact_gc",
        execute_requested=execute,
    )

    if execute and not governed.can_execute:
        r = emit_structured_result(
            script_name="rig_relay_gc_artifacts",
            authority_tier="local_mutation",
            capability_id="artifact_gc",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=False,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            print(json.dumps(r, indent=2))
        else:
            print(f"BLOCKED: {governed.decision.decision.value}")
            if governed.evidence_status == "persistence_failed":
                print("  EVIDENCE: persistence failed — GC blocked (fail-closed)")
        return 1

    manifest = run_artifact_gc(
        root=root,
        budget=budget,
        confirm=confirm,
        force=args.force,
        archive_dir=args.archive,
    )

    if manifest["summary"]["dry_run"]:
        print("=== DRY RUN — No files deleted ===")
    else:
        print("=== GC Complete ===")

    s = manifest["summary"]
    print(
        f"Candidates: {s['total_candidates']} total, "
        f"{s['deleted']} deleted, {s['archived']} archived, "
        f"{s['skipped']} skipped"
    )
    print(f"Freed: {s['freed_mb']:.1f} MB")

    if manifest["candidates"]:
        top = sorted(manifest["candidates"], key=lambda x: -x["size_mb"])[:10]
        print()
        print("--- Top Candidates ---")
        for c in top:
            print(
                f"  [{c['action']:12s}] {c['size_mb']:>7.2f} MB  {c['relative_path']}"
            )

    for w in manifest["warnings"]:
        print(f"WARNING: {w}")

    if not confirm and manifest["summary"]["total_candidates"] > 0:
        print()
        print("Run with --confirm to delete or --archive <dir> to archive.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
