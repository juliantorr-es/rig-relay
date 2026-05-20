#!/usr/bin/env python3
"""Rig Relay code scanning PR mutation readiness CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_pr_mutation_readiness import (
    write_mutation_readiness,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_mutation_readiness_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nMutation Readiness Summary")
    print("-" * 28)
    rows = [
        ("status", report.get("status")),
        ("branch", report.get("proposed_branch_name")),
        ("mutation_gates", report.get("mutation_gates_passed")),
        ("remote_mutation", report.get("remote_mutation")),
        ("local_mutation", report.get("local_repository_mutation")),
        ("alert_update", report.get("alert_update")),
        ("alert_deferred", report.get("alert_update_deferred")),
        ("approval_status", report.get("approval_status")),
        ("live_mutation", report.get("live_mutation_enabled")),
    ]
    for label, value in rows:
        print(f"  {label:<18} {value}")
    blocked = report.get("blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print(f"\n  Blocked reasons ({len(blocked)}):")
        for r in blocked:
            print(f"    - {r}")
    sim = report.get("simulation")
    if isinstance(sim, dict) and sim.get("simulation_run"):
        print(
            f"\n  Temp repo simulation: {'PASSED' if sim.get('simulation_passed') else 'FAILED'}"
        )
        print(f"    steps: {', '.join(sim.get('steps', []))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-mutation-readiness",
        description="Evaluate PR mutation readiness.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--simulate", action="store_true", help="Run temp-repo mutation simulation."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_mutation_readiness(
        output_path=args.output_json,
        simulate_temp_repo_flag=args.simulate,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
