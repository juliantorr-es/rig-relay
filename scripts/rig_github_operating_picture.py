#!/usr/bin/env python3
"""Rig Relay GitHub operating picture CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._operating_picture import (
    write_github_operating_picture,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    packet_summary = report.get("packet_summary")
    if not isinstance(packet_summary, dict):
        packet_summary = {}
    candidate_summary = report.get("candidate_summary")
    if not isinstance(candidate_summary, dict):
        candidate_summary = {}
    local_patch_lane_summary = report.get("local_patch_lane_summary")
    if not isinstance(local_patch_lane_summary, dict):
        local_patch_lane_summary = {}
    summary_rows = [
        ("packet_index_stale", packet_summary.get("packet_index_stale")),
        ("packet_count", packet_summary.get("packet_count")),
        ("excluded_candidate_count", packet_summary.get("excluded_candidate_count")),
        (
            "ready_for_investigation_count",
            candidate_summary.get("ready_for_investigation_count"),
        ),
        ("permission_blocked", local_patch_lane_summary.get("permission_blocked")),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
    ]
    width = max(len(label) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-operating-picture",
        description="Build the GitHub provider operating picture from local artifacts.",
    )
    parser.add_argument(
        "--owner", type=str, default=None, help="Repository owner metadata."
    )
    parser.add_argument(
        "--repo", type=str, default=None, help="Repository name metadata."
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output operating-picture artifact path.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero if the packet index is stale.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact content-light summary."
    )
    args = parser.parse_args(argv)

    report = write_github_operating_picture(
        args.output_json,
        owner=args.owner,
        repo=args.repo,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report, args.output_json)
    packet_summary = report.get("packet_summary")
    if not isinstance(packet_summary, dict):
        packet_summary = {}
    if args.fail_on_stale and packet_summary.get("packet_index_stale"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
