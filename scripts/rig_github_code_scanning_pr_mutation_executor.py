#!/usr/bin/env python3
"""Rig Relay gated PR mutation executor CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_executor import (
    write_mutation_execution,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_pr_mutation_execution_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nPR Mutation Execution Summary")
    print("-" * 30)
    rows = [
        ("status", report.get("operation_status")),
        ("remote_attempted", report.get("remote_mutation_attempted")),
        ("remote_succeeded", report.get("remote_mutation_succeeded")),
        ("pr_created", report.get("pr_created")),
        ("alert_updated", report.get("alert_updated")),
        ("gates_passed", report.get("gates_passed")),
        ("permissions_used", report.get("permissions_used")),
    ]
    for label, value in rows:
        print(f"  {label:<18} {value}")
    blocked = report.get("blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print(f"\n  Blocked ({len(blocked)}): " + ", ".join(str(r) for r in blocked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-pr-mutation-executor",
        description="Execute gated PR mutation.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use deterministic fake GitHub boundary.",
    )
    parser.add_argument(
        "--execute-remote-mutation",
        action="store_true",
        help="Allow real remote mutation (gated).",
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = write_mutation_execution(
        output_path=args.output_json,
        allow_remote=args.execute_remote_mutation,
        simulate=args.simulate,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
