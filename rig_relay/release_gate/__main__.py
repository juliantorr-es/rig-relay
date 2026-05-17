"""Release evidence gate CLI — runs all registered checks via GateRunner.

Usage:
    uv run python -m rig_relay.release_gate [--output FILE] [--include-check ID]...

Exit codes:
    0 — gate passed or warning
    1 — gate failed (blockers)
    2 — gate error (unhandled exception)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.release_gate._checks_registry import build_default_registry
from rig_relay.release_gate.models import CheckContext, GateStatus
from rig_relay.release_gate.runner import GateRunner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Release Evidence Gate v1 — all-lane check runner (CI-safe, non-mutating)"
    )
    p.add_argument(
        "--output", type=Path, default=None, help="Write gate result JSON to this path"
    )
    p.add_argument(
        "--include-check",
        action="append",
        default=[],
        dest="include_check",
        help="Only run these check IDs (repeatable)",
    )
    p.add_argument(
        "--exclude-check",
        action="append",
        default=[],
        dest="exclude_check",
        help="Exclude these check IDs (repeatable)",
    )
    return p


def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = Path.cwd()
    output_dir = repo_root / ".build" / "rig-relay"

    try:
        registry = build_default_registry(repo_root=repo_root, output_dir=output_dir)
    except Exception as exc:
        print(f"gate: error building registry: {exc}", file=sys.stderr)
        return 2

    ctx = CheckContext(repo_root=repo_root, output_dir=output_dir)
    runner = GateRunner(checks=registry)

    try:
        result = runner.run(
            ctx,
            include_checks=set(args.include_check) if args.include_check else None,
            exclude_checks=set(args.exclude_check) if args.exclude_check else None,
        )
    except Exception as exc:
        print(f"gate: error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict

        output = {
            "schema_version": result.schema_version,
            "gate_id": result.gate_id,
            "overall_status": result.overall_status.value,
            "summary": asdict(result.summary),
            "checks": result.checks,
            "findings": result.findings,
        }
        output_path.write_text(
            json.dumps(output, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"gate: wrote {output_path}")

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
