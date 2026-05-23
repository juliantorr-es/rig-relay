#!/usr/bin/env python3
"""Rig Relay Coordination Lease Cleanup — CLI wrapper.

Dry-run first, conservative by default. Pass --execute to perform
actual cleanup. Governance gating required for destructive operations.

The core implementation lives in ``rig_relay.coordination.cleanup_leases``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.coordination.cleanup_leases import (
    DEFAULT_COORDINATION_ROOT,
    _compute_stats,
    _print_report,
    _scan_leases,
    _scan_tasks,
    run_cleanup,
)


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
        action="store_true",
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
        "--execute",
        action="store_true",
        default=False,
        help="Execute destructive cleanup operations. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()

    if not args.coordination_root.is_dir():
        print(
            f"Error: Coordination root not found: {args.coordination_root}",
            file=sys.stderr,
        )
        return 1

    execute = args.execute or args.confirm
    governed = require_governed_execution_with_evidence(
        script_name="rig_relay_cleanup_coordination_leases",
        authority_tier="local_mutation",
        capability_id="coordination_lease_cleanup",
        execute_requested=execute,
    )

    if not args.execute and not args.confirm:
        _print_report(
            _compute_stats(
                _scan_leases(args.coordination_root / "leases" / "paths"),
                _scan_tasks(args.coordination_root / "tasks"),
            )
        )
        if args.json:
            d = governed.decision
            r = emit_structured_result(
                script_name="rig_relay_cleanup_coordination_leases",
                authority_tier="local_mutation",
                capability_id="coordination_lease_cleanup",
                dry_run=True,
                execute_requested=False,
                decision=d,
                status="dry_run",
            )
            print(json.dumps(r, indent=2))
        return 0

    if not governed.can_execute:
        r = emit_structured_result(
            script_name="rig_relay_cleanup_coordination_leases",
            authority_tier="local_mutation",
            capability_id="coordination_lease_cleanup",
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
                print("  EVIDENCE: persistence failed — cleanup blocked (fail-closed)")
        return 1

    result = run_cleanup(
        coordination_root=args.coordination_root,
        max_age_seconds=args.max_age_seconds,
        dry_run=False,
        archive=args.archive,
        confirm=True,
    )

    if args.json:
        r = emit_structured_result(
            script_name="rig_relay_cleanup_coordination_leases",
            authority_tier="local_mutation",
            capability_id="coordination_lease_cleanup",
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=True,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
            artifacts=result,
        )
        print(json.dumps(r, indent=2))

    if result.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
