#!/usr/bin/env python3
"""Rig Relay Google Workspace surface packets CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.google_workspace._surface_packets import (
    write_google_workspace_surface_packets,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_surface_packets_v1.v1.json"
)
DEFAULT_OP_PICTURE = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_operating_picture_v1.v1.json"
)
DEFAULT_READ_INTAKE = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_read_intake_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    summary_rows = [
        ("total_packets", summary.get("total_packets")),
        ("ready_packets", summary.get("ready_packets")),
        ("blocked_packets", summary.get("blocked_packets")),
        ("deferred_packets", summary.get("deferred_packets")),
        ("next_action", summary.get("next_action")),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
        ("content_light", report.get("content_light")),
    ]
    width = max(len(label) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-google-workspace-surface-packets",
        description="Project Google Workspace surface packets from operating picture and read intake.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output surface packets artifact path.",
    )
    parser.add_argument(
        "--operating-picture",
        type=Path,
        default=DEFAULT_OP_PICTURE,
        help="Path to operating picture artifact.",
    )
    parser.add_argument(
        "--read-intake",
        type=Path,
        default=DEFAULT_READ_INTAKE,
        help="Path to read intake artifact.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact content-light summary."
    )
    args = parser.parse_args(argv)

    report = write_google_workspace_surface_packets(
        args.output_json,
        operating_picture_path=args.operating_picture,
        read_intake_path=args.read_intake,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
