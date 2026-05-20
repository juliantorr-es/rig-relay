#!/usr/bin/env python3
"""Rig Relay security remediation plan CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._security_remediation_plan import (
    _MAX_SELECTED,
    write_security_remediation_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_remediation_plan_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    policy = report.get("selection_policy")
    plans = report.get("remediation_plans")
    if not isinstance(policy, dict):
        policy = {}
    if not isinstance(plans, list):
        plans = []

    print("\nSecurity Remediation Plan Summary")
    print("-" * 36)
    print(
        f"  selected: {len(plans)} of {policy.get('items_selected', '?')} (from {policy.get('total_queue_items', '?')} queue items)"
    )
    print(f"  remote_mutation: {report.get('remote_mutation')}")
    print(f"  content_light: {report.get('content_light')}")
    print()
    for plan in plans:
        if isinstance(plan, dict):
            print(
                f"  #{plan.get('priority_rank')} [{plan.get('severity')}] {plan.get('source_surface')}: {plan.get('issue_summary_safe', '')[:80]}"
            )
            perms = plan.get("required_permissions")
            if isinstance(perms, dict):
                print(f"     read: {', '.join(perms.get('read', []))}")
                print(
                    f"     mutation (deferred): {', '.join(perms.get('mutation', []))}"
                )
            blocked = plan.get("blocked_reasons")
            if isinstance(blocked, list) and blocked:
                print(f"     blocked: {', '.join(blocked)}")
            print(f"     human review: {plan.get('human_review_required')}")
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-remediation-plan",
        description="Generate security remediation plan from queue.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-items",
        type=int,
        default=_MAX_SELECTED,
        help=f"Max items to select (default: {_MAX_SELECTED})",
    )
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_security_remediation_plan(
        output_path=args.output_json,
        max_selected=args.max_items,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
