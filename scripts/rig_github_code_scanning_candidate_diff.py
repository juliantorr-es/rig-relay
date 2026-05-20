#!/usr/bin/env python3
"""Rig Relay code scanning dry-run candidate diff CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_candidate_diff import (
    write_code_scanning_candidate_diff,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_dry_run_candidate_diff_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nDry-Run Candidate Diff Summary")
    print("-" * 32)
    rows = [
        ("has_real_diff", report.get("has_real_diff")),
        ("gate_passed", report.get("policy_gate_passed")),
        ("diff_classification", report.get("diff_classification")),
        ("diff_path", report.get("diff_path")),
        (
            "diff_sha256",
            str(report.get("diff_sha256", ""))[:16] + "..."
            if report.get("diff_sha256")
            else "N/A",
        ),
        ("diff_lines", report.get("diff_line_count")),
        ("raw_source_in_json", report.get("raw_source_embedded_in_json")),
        ("remote_mutation", report.get("remote_mutation")),
        ("pr_creation", report.get("pr_creation_status")),
    ]
    for label, value in rows:
        print(f"  {label:<22} {value}")
    blocked = report.get("policy_gate_blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print("\n  Blocked reasons:")
        for r in blocked:
            print(f"    - {r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-candidate-diff",
        description="Generate dry-run candidate diff.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = write_code_scanning_candidate_diff(
        output_path=args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
