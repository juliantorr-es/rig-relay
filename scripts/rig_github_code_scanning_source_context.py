#!/usr/bin/env python3
"""Rig Relay code scanning source context acquisition CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_source_context import (
    write_code_scanning_source_context,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_source_context_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nSource Context Acquisition Summary")
    print("-" * 38)
    rows = [
        ("status", report.get("source_context_status")),
        ("acquisition_mode", report.get("acquisition_mode")),
        ("live_api_attempted", report.get("live_api_attempted")),
        ("safe_context_available", report.get("safe_context_available")),
        ("alert_number", report.get("selected_alert_number")),
        ("remote_mutation", report.get("remote_mutation_status")),
        ("local_mutation", report.get("local_mutation_status")),
    ]
    for label, value in rows:
        print(f"  {label:<22} {value}")
    unsafe = report.get("unsafe_context_reasons")
    if isinstance(unsafe, list) and unsafe:
        print("\n  Unavailable reasons:")
        for r in unsafe:
            print(f"    - {r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-source-context",
        description="Acquire source context for code scanning alert.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt live API acquisition (gated by RIG_LIVE_AUTH_TESTS=1).",
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_code_scanning_source_context(
        output_path=args.output_json,
        generated_at_utc=args.generated_at_utc,
        allow_live=args.live,
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
