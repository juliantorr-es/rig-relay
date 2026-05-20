#!/usr/bin/env python3
"""Rig Relay GitHub security packet execution CLI.

Executes a bounded subset of GitHub security packet investigations.
Read-only. No remote mutation. No local mutation by default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._security_packet_execution import (
    build_github_security_packet_execution,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_packet_execution_v1.v1.json"
)
DEFAULT_PLAN_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_packet_runner_plan_v1.v1.json"
)

_USAGE = """\
uv run python scripts/rig_github_security_packet_execution.py \
  --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json \
  --output-json docs/json/governance/github_security_packet_execution_v1.v1.json \
  --limit 1 \
  --summary"""


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-packet-execution",
        description="Bounded local execution of GitHub security packet investigations.",
        epilog=f"Example:\n{_USAGE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--plan-json",
        dest="plan_json",
        type=Path,
        default=DEFAULT_PLAN_JSON,
        help="Path to runner plan JSON.",
    )
    parser.add_argument(
        "--operating-picture-json",
        type=Path,
        default=None,
        help="Path to operating picture JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output execution artifact path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum packets to execute (default: 1, max: 3).",
    )
    parser.add_argument(
        "--packet-id",
        type=str,
        action="append",
        dest="packet_ids",
        default=None,
        help="Select specific packet by ID (repeatable). Overrides --limit.",
    )
    parser.add_argument("--summary", action="store_true", help="Print compact summary.")
    parser.add_argument(
        "--refuse-local-apply",
        action="store_true",
        default=True,
        help="Refuse packets with apply_local=true (default).",
    )
    parser.add_argument(
        "--allow-local-apply",
        action="store_true",
        default=False,
        help="Allow packets with apply_local=true (v1 still refuses by default).",
    )
    args = parser.parse_args(argv)

    refuse_local_apply = args.refuse_local_apply and not args.allow_local_apply

    report = build_github_security_packet_execution(
        plan_path=args.plan_json,
        operating_picture_path=args.operating_picture_json,
        limit=args.limit,
        packet_ids=args.packet_ids,
        refuse_local_apply=refuse_local_apply,
    )
    payload = safe_summary(report)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("selected_count", summary.get("selected_count")),
            ("executed_count", summary.get("executed_count")),
            (
                "needs_local_remediation_count",
                summary.get("needs_local_remediation_count"),
            ),
            ("needs_human_review_count", summary.get("needs_human_review_count")),
            ("permission_blocked_count", summary.get("permission_blocked_count")),
            ("advisory_only_count", summary.get("advisory_only_count")),
            ("skipped_count", summary.get("skipped_count")),
            ("limit", payload.get("limit")),
            ("remote_mutation", payload.get("remote_mutation")),
            ("local_mutation", payload.get("local_mutation")),
            ("refuse_local_apply", payload.get("refuse_local_apply")),
            ("next_action", summary.get("next_recommended_action")),
            ("output_json", str(args.output_json)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
