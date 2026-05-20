#!/usr/bin/env python3
"""Evaluate whether DeepSeek router lanes are ready for promotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.integrations.deepseek_routing import (
    build_router_promotion_report,
    format_router_promotion_report_table,
    load_router_promotion_policy,
    validate_router_promotion_outputs,
    write_router_promotion_report,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        required=True,
        help="Root directory containing routing receipts and task outcome receipts.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        required=True,
        help="Path to the DeepSeek router promotion policy artifact.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Where to write the promotion gate report JSON.",
    )
    parser.add_argument(
        "--fail-on-hold",
        action="store_true",
        help="Return non-zero when the gate recommendation is hold or rollback.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        policy = load_router_promotion_policy(args.policy)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"policy error: {exc}", file=sys.stderr)
        return 1

    try:
        report = build_router_promotion_report(
            args.receipts_dir, policy=policy, output_json=args.output_json
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"promotion gate error: {exc}", file=sys.stderr)
        return 1

    errors = validate_router_promotion_outputs(report)
    if errors:
        print("promotion report validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    write_router_promotion_report(report, args.output_json)
    print(format_router_promotion_report_table(report))

    if args.fail_on_hold and report["recommendation"] in {"hold", "rollback"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
