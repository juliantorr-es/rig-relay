#!/usr/bin/env python3
"""Rig Relay code scanning PR creation plan CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_pr_plan import (
    write_code_scanning_pr_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_creation_plan_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nPR Creation Plan Summary")
    print("-" * 26)
    rows = [
        ("status", report.get("status")),
        ("branch", report.get("proposed_branch_name")),
        (
            "pr_title",
            str(report.get("proposed_pr_title", ""))[:70]
            if report.get("proposed_pr_title")
            else "",
        ),
        ("remote_mutation", report.get("remote_mutation")),
        ("local_mutation", report.get("local_mutation")),
        ("alert_update", "deferred"),
        ("permissions_used", "none"),
    ]
    for label, value in rows:
        print(f"  {label:<18} {value}")
    blocked = report.get("blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print(f"\n  Blocked reasons ({len(blocked)}):")
        for r in blocked:
            print(f"    - {r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-pr-plan",
        description="Generate PR creation plan from candidate diff.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = write_code_scanning_pr_plan(
        output_path=args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
