#!/usr/bin/env python3
"""Rig Relay live mutation preflight CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.integrations.github_provider._live_mutation_preflight import (
    write_live_mutation_preflight,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_live_mutation_preflight_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nLive Mutation Preflight Summary")
    print("-" * 32)
    rows = [
        ("status", report.get("status")),
        ("live_api_attempted", report.get("live_api_attempted")),
        ("live_mutation_attempted", report.get("live_mutation_attempted")),
        ("remote_mutation_attempted", report.get("remote_mutation_attempted")),
        ("gates_passed", report.get("gates_passed")),
    ]
    for label, value in rows:
        print(f"  {label:<24} {value}")
    blocked = report.get("blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print(f"\n  Blocked ({len(blocked)}): " + ", ".join(str(r) for r in blocked))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-live-mutation-preflight",
        description="Live mutation preflight gate.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--live-preflight",
        action="store_true",
        help="Perform read-only live preflight (gated).",
    )
    parser.add_argument(
        "--simulate", action="store_true", help="Use fake HTTP boundary."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    if args.live_preflight:
        governed = require_governed_execution_with_evidence(
            script_name="rig_github_live_mutation_preflight",
            authority_tier="remote_mutation",
            capability_id="github_live_preflight",
            execute_requested=True,
            allow_mutation=True,
            allow_network=True,
        )
        if not governed.can_execute:
            print(
                f"BLOCKED: {governed.decision.decision.value} — live preflight requires governance approval"
            )
            return 1

    report = write_live_mutation_preflight(
        output_path=args.output_json,
        allow_live=args.live_preflight,
        simulate=args.simulate,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
