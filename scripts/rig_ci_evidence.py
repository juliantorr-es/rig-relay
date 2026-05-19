#!/usr/bin/env python3
"""Rig Relay CI Evidence Producer CLI.

Produces schema-governed CI evidence artifacts and writes a verdict.
Exit codes: 0 for pass, 1 for fail, 2 for hold.

Usage:
    uv run python scripts/rig_ci_evidence.py
    uv run python scripts/rig_ci_evidence.py --output-dir .build/rig-relay/evidence/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.ci_evidence import produce_ci_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-ci-evidence",
        description="Produce schema-governed CI evidence artifacts and write a verdict.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory for CI evidence artifacts (default: .build/rig-relay/evidence/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output verdict as JSON to stdout",
    )
    args = parser.parse_args(argv)

    result = produce_ci_evidence(output_dir=args.output_dir)

    if args.json_output:
        print(
            json.dumps(
                {
                    "verdict": result.verdict,
                    "run_id": result.verdict_path.stem.replace("ci_", "").replace(
                        "_verdict", ""
                    ),
                    "blocking_reasons": result.blocking_reasons,
                    "warnings": result.warnings,
                    "evidence_paths": result.evidence_paths,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print("CI evidence producer completed.")
        print(f"  Verdict:          {result.verdict}")
        print(f"  Blocking reasons: {len(result.blocking_reasons)}")
        for reason in result.blocking_reasons:
            print(f"    - {reason}")
        print(f"  Warnings:         {len(result.warnings)}")
        for warning in result.warnings:
            print(f"    - {warning}")
        print(f"  Evidence paths:   {len(result.evidence_paths)}")
        for ep in result.evidence_paths:
            print(f"    - {ep}")

    match result.verdict:
        case "pass":
            return 0
        case "fail":
            return 1
        case _:
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
