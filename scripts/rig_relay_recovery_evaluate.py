"""CLI entry point for D1A offline recovery evaluation.

Reads a JSONL corpus of emission cases, runs them through the D0
recovery pipeline, writes evaluation JSONL evidence and a report.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("RIG_RELAY_DISABLE_LEGACY_CONFIG", "1")


from rig_relay.recovery.models import CanonicalToolSurfaceManifest


def _build_manifest() -> CanonicalToolSurfaceManifest:
    from rig_relay.core.config.harness_files._harness_manager import (
        init_harness_files_manager,
    )

    init_harness_files_manager()

    from rig_relay.core.tools.manager import ToolManager
    from rig_relay.recovery.models import CanonicalToolSurfaceManifest
    from rig_relay.recovery.tool_surface_manifest import build_tool_surface_manifest
    from tests.conftest import build_test_vibe_config

    config = build_test_vibe_config(
        system_prompt_id="tests", include_project_context=False
    )
    tm = ToolManager(lambda: config)
    result = build_tool_surface_manifest(tm.available_tools)
    if not isinstance(result, CanonicalToolSurfaceManifest):
        print(f"Manifest construction failed: {result}", file=sys.stderr)
        sys.exit(1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="D1A offline recovery evaluation")
    parser.add_argument(
        "--corpus", required=True, type=Path, help="JSONL file of emission cases"
    )
    parser.add_argument(
        "--output-dir",
        default=Path(".build/rig-relay/recovery-eval"),
        type=Path,
        help="Output directory for evaluation artifacts",
    )
    parser.add_argument(
        "--report", action="store_true", help="Also generate a recovery report"
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict] = []
    with open(args.corpus) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    manifest = _build_manifest()

    from rig_relay.recovery.evaluation import evaluate_cases

    ledger_path = args.output_dir / "evaluation_events.jsonl"
    events = evaluate_cases(manifest, cases, ledger_path=ledger_path)

    print(f"Evaluated {len(events)} cases → {ledger_path}")

    if args.report:
        from rig_relay.recovery.report import write_report

        report_path = args.output_dir / "evaluation_report.json"
        report = write_report(events, report_path)
        print(f"Report: {report_path}")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
