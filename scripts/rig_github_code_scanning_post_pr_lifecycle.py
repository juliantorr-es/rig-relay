#!/usr/bin/env python3
"""Rig Relay post-PR lifecycle governance CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_post_pr_lifecycle import (
    write_post_pr_lifecycle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_post_pr_lifecycle_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nPost-PR Lifecycle Summary")
    print("-" * 27)
    rows = [
        ("pr_state", report.get("pr_lifecycle_state")),
        ("alert_state", report.get("alert_lifecycle_state")),
        ("alert_update", report.get("alert_update")),
        ("alert_deferred", report.get("alert_update_deferred")),
        ("remote_mutation", report.get("remote_mutation")),
    ]
    plan = report.get("alert_state_plan")
    if isinstance(plan, dict):
        rows.append(("recommended", plan.get("recommended_path")))
        blocked = plan.get("blocked_reasons")
        if isinstance(blocked, list) and blocked:
            rows.append(("blocked", ", ".join(str(r) for r in blocked)))
    for label, value in rows:
        print(f"  {label:<16} {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-post-pr-lifecycle",
        description="Post-PR security lifecycle governance.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate post-PR lifecycle via fake GitHub boundary.",
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_post_pr_lifecycle(
        output_path=args.output_json,
        simulate=args.simulate,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
