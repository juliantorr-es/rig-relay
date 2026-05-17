"""Release evidence gate CLI — non-mutating mode for CI.

Usage:
    uv run python -m rig_relay.release_gate [--output FILE] [--skip CHECK_ID]...

Exit codes:
    0 — gate passed (all checks pass or warn with no blockers)
    1 — gate failed (blockers or hard failures)
    2 — gate error (unhandled exception during gate execution)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.release_gate import run_all_runtime_checks
from rig_relay.release_gate.models import GateStatus


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Release Evidence Gate v1 — runtime readiness scanner (CI-safe, non-mutating)"
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write gate result JSON to this path (default: stdout summary only)",
    )
    p.add_argument(
        "--skip",
        action="append",
        default=[],
        dest="skip_ids",
        help="Check ID to skip (repeatable)",
    )
    p.add_argument(
        "--triage", type=Path, default=None, help="Path to triage policy JSON file"
    )
    return p


def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    triage = None
    if args.triage:
        from rig_relay.release_gate._runtime_readiness import load_triage_policy

        triage = load_triage_policy(args.triage)

    try:
        result = run_all_runtime_checks(
            triage=triage, skip=set(args.skip_ids) if args.skip_ids else None
        )
    except Exception as exc:
        print(f"gate: error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        import dataclasses

        output = {
            "schema_version": result.schema_version,
            "gate_id": result.gate_id,
            "overall_status": result.overall_status.value,
            "summary": dataclasses.asdict(result.summary),
            "checks": result.checks,
        }
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"gate: wrote {args.output}")

    print(
        f"gate: {result.overall_status.value} — {result.summary.total_checks} checks, "
        f"{result.summary.passed} passed, {result.summary.failed} failed, "
        f"{result.summary.warning} warnings, {result.summary.skipped} skipped, "
        f"{result.summary.total_findings} findings"
    )

    if result.overall_status in {GateStatus.FAILED}:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_main())
