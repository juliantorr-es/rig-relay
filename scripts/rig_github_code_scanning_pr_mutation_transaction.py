#!/usr/bin/env python3
"""Rig Relay code scanning PR mutation transaction harness CLI."""

from __future__ import annotations

import argparse

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_transaction import (
    SCENARIOS,
    write_transaction_report,
)


def _print_summary(report: dict[str, object]) -> None:
    print(f"\nTransaction Summary: {report.get('scenario')}")
    print("-" * 36)
    rows = [
        ("status", report.get("status")),
        ("transaction_id", str(report.get("transaction_id", ""))[:16] + "..."),
        ("steps", len(report.get("steps", []))),
        (
            "recovery_needed",
            report.get("recovery", {}).get("manual_review_required", True)
            if isinstance(report.get("recovery"), dict)
            else True,
        ),
    ]
    for label, value in rows:
        print(f"  {label:<20} {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-pr-mutation-transaction",
        description="Transaction harness for PR mutation.",
    )
    parser.add_argument(
        "--simulate-scenario",
        type=str,
        choices=SCENARIOS,
        default="complete_success",
        help="Fake boundary scenario.",
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = write_transaction_report(scenario=args.simulate_scenario)
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
