#!/usr/bin/env python3
"""Rig Relay GitHub security packet runner CLI.

Turns security mission packets into bounded local execution plans.
Read-only by default. No remote mutation. No local apply unless explicitly gated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._security_packet_runner import (
    build_github_security_packet_runner_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_packet_runner_plan_v1.v1.json"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-packet-runner",
        description="Bounded local execution plan for GitHub security mission packets.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Generate plan only (default). No patches applied.",
        default=True,
    )
    parser.add_argument(
        "--limit", type=int, default=3, help="Maximum packets to select (default: 3)."
    )
    parser.add_argument(
        "--packet-id",
        type=str,
        action="append",
        dest="packet_ids",
        default=None,
        help="Select specific packet by ID (repeatable). Overrides --limit.",
    )
    parser.add_argument(
        "--packet-index-path",
        type=Path,
        default=None,
        help="Path to mission packet index JSON.",
    )
    parser.add_argument(
        "--operating-picture-path",
        type=Path,
        default=None,
        help="Path to operating picture JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output plan artifact path.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact summary."
    )
    args = parser.parse_args(argv)

    plan = build_github_security_packet_runner_plan(
        packet_index_path=args.packet_index_path,
        operating_picture_path=args.operating_picture_path,
        limit=args.limit,
        packet_ids=args.packet_ids,
    )
    payload = safe_summary(plan)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("plan_item_count", summary.get("plan_item_count")),
            ("refusal_count", summary.get("refusal_count")),
            ("selected_packet_count", payload.get("selected_packet_count")),
            ("total_available_packets", payload.get("total_available_packets")),
            ("selection_mode", payload.get("selection_mode")),
            ("remote_mutation", payload.get("remote_mutation")),
            ("apply_local", payload.get("apply_local")),
            ("output_json", str(args.output_json)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    if payload.get("refusals"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
