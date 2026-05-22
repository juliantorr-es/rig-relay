#!/usr/bin/env python3
"""Rig Relay PR mutation chaos lab CLI — generate, replay, verify, repair."""

from __future__ import annotations

import argparse
import json

from rig_relay.cli.governance_guard import emit_structured_result
from rig_relay.integrations.github_provider._pr_mutation_chaos_lab import (
    run_chaos_lab,
    generate_chaos_scenarios,
    run_replay_verifier,
    generate_repair_plan,
)


def _print_summary(report: dict[str, object]) -> None:
    print(f"\nChaos Lab Summary")
    print("-" * 20)
    rows = [
        ("scenarios", report.get("scenarios_generated")),
        ("replayed", report.get("scenarios_replayed")),
        ("invariants", report.get("invariants_checked")),
        ("failed", report.get("invariants_failed")),
        ("corruption_cases", report.get("corruption_cases_checked")),
        ("no_live_network", report.get("no_live_network")),
        ("no_remote_mutation", report.get("no_remote_mutation")),
        ("no_alert_update", report.get("no_alert_update")),
    ]
    for label, value in rows:
        print(f"  {label:<18} {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-pr-mutation-chaos-lab",
        description="PR mutation chaos + replay verification lab.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-scenarios", type=int, default=75)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--repair-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON result.",
    )
    args = parser.parse_args(argv)

    if args.generate_only:
        s, m = generate_chaos_scenarios(seed=args.seed, count=args.max_scenarios)
        if args.summary:
            print(f"Generated {len(s)} scenarios (seed={args.seed})")
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "rig.chaos_lab.v1",
                        "mode": "generate_only",
                        "scenarios_generated": len(s),
                        "seed": args.seed,
                        "content_light": True,
                    },
                    indent=2,
                )
            )
    elif args.verify_only:
        r = run_replay_verifier()
        if args.summary:
            print(
                f"Verified {r['invariants_checked']} invariants, {r['invariants_failed']} failed"
            )
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "rig.chaos_lab.v1",
                        "mode": "verify_only",
                        "invariants_checked": r.get("invariants_checked"),
                        "invariants_failed": r.get("invariants_failed"),
                        "content_light": True,
                    },
                    indent=2,
                )
            )
    elif args.repair_only:
        r = generate_repair_plan()
        if args.summary:
            print(f"Repair plan: {len(r['corruption_cases'])} corruption cases")
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "rig.chaos_lab.v1",
                        "mode": "repair_only",
                        "corruption_cases": len(r.get("corruption_cases", [])),
                        "content_light": True,
                    },
                    indent=2,
                )
            )
    else:
        report = run_chaos_lab(seed=args.seed, count=args.max_scenarios)
        if args.summary:
            _print_summary(report)
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "rig.chaos_lab.v1",
                        "mode": "full",
                        "scenarios_generated": report.get("scenarios_generated"),
                        "scenarios_replayed": report.get("scenarios_replayed"),
                        "invariants_checked": report.get("invariants_checked"),
                        "invariants_failed": report.get("invariants_failed"),
                        "no_live_network": report.get("no_live_network"),
                        "no_remote_mutation": report.get("no_remote_mutation"),
                        "content_light": True,
                    },
                    indent=2,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
