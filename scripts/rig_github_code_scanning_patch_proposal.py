#!/usr/bin/env python3
"""Rig Relay code scanning fix patch proposal CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_patch_proposal import (
    write_code_scanning_patch_proposal,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_patch_proposal_v1.v1.json"
)


def _print_summary(report: dict[str, object]) -> None:
    print("\nCode Scanning Patch Proposal Summary")
    print("-" * 40)
    blocked_raw = report.get("blocked_reasons")
    blocked_joined = (
        ", ".join(blocked_raw)
        if isinstance(blocked_raw, list) and blocked_raw
        else "none"
    )
    rows = [
        ("alert_number", report.get("alert_number")),
        ("severity", report.get("severity")),
        ("rule_category", report.get("rule_category")),
        ("location_summary", report.get("location_summary_safe")),
        ("remote_mutation", report.get("remote_mutation_status")),
        ("pr_creation", report.get("pr_creation_status")),
        ("alert_update", report.get("alert_update_status")),
        ("human_review", report.get("human_review_required")),
        ("blocked", blocked_joined),
    ]
    for label, value in rows:
        print(f"  {label:<20} {value}")
    summary_safe = report.get("patch_summary_safe", "")
    print(f"\nStrategy: {str(summary_safe)[:120]}...")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-code-scanning-patch-proposal",
        description="Generate code scanning fix patch proposal from remediation plan.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at-utc", type=str, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    report = write_code_scanning_patch_proposal(
        output_path=args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
