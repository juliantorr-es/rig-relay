#!/usr/bin/env python3
"""Rig Relay Meta permissions inventory CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.meta_provider._permissions_inventory import (
    write_meta_permissions_inventory,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "meta_permissions_inventory_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    summary_rows = [
        ("total_capabilities", report.get("capability_count")),
        ("supported_readonly", summary.get("supported_readonly_count")),
        ("refused", report.get("refused_count")),
        ("deferred", report.get("deferred_count")),
        ("high_risk", summary.get("high_risk_count")),
        ("app_review_likely", summary.get("app_review_likely_count")),
        (
            "business_verification_likely",
            summary.get("business_verification_likely_count"),
        ),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
        ("live_network", report.get("live_network")),
    ]
    width = max(len(label) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-meta-permissions-inventory",
        description="Build the Meta provider permissions inventory from static analysis.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output permissions-inventory artifact path.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
        dest="generated_at",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact content-light summary."
    )
    args = parser.parse_args(argv)

    report = write_meta_permissions_inventory(
        args.output_json, generated_at=args.generated_at
    )
    if args.summary:
        _print_summary(report, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
