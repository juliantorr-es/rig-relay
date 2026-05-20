#!/usr/bin/env python3
"""Rig Relay unified security queue CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._security_queue import write_security_queue

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_queue_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    summary = report.get("queue_summary")
    risk = report.get("risk_summary")
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(risk, dict):
        risk = {}

    rem = report.get("remediation_readiness_summary")
    rem_possible = rem.get("remediation_possible") if isinstance(rem, dict) else False
    rows = [
        ("total_queue_items", summary.get("total_queue_items")),
        ("blocked_items", summary.get("blocked_item_count")),
        ("open_items", risk.get("open_items")),
        ("highest_severity", risk.get("highest_severity_present")),
        ("remote_mutation", report.get("remote_mutation")),
        ("content_light", report.get("content_light")),
        ("remediation_possible", rem_possible),
    ]
    print("\nSecurity Queue Summary")
    print("-" * 30)
    for label, value in rows:
        print(f"  {label:<24} {value}")

    surfaces = report.get("input_surfaces")
    if isinstance(surfaces, list):
        print("\nSource Surfaces:")
        for s in surfaces:
            if isinstance(s, dict):
                print(
                    f"  {s.get('surface'):<30} {s.get('status'):<15} {s.get('item_count', 0)} items"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-queue",
        description="Build unified GitHub security queue.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output queue artifact path.",
    )
    parser.add_argument(
        "--generated-at-utc", type=str, default=None, help="Override timestamp."
    )
    parser.add_argument("--summary", action="store_true", help="Print summary.")
    args = parser.parse_args(argv)

    report = write_security_queue(
        output_path=args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
