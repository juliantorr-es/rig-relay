#!/usr/bin/env python3
"""Rig Relay GitHub surface packets CLI.

Generates reviewable public-surface proposal packets from surface audit findings.
Read-only. No remote mutation. No local apply.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._surface_packets import (
    build_github_surface_packets,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-surface-packets",
        description="Generate reviewable public-surface proposal packets from audit findings.",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default="juliantorr-es",
        help="GitHub owner (default: juliantorr-es).",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="rig-relay",
        help="GitHub repo (default: rig-relay).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output surface packets artifact path.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact summary."
    )
    args = parser.parse_args(argv)

    packets = build_github_surface_packets(owner=args.owner, repo=args.repo)
    payload = safe_summary(packets)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("total_packets", summary.get("total_packets")),
            ("packet_type_counts", json.dumps(summary.get("packet_type_counts", {}))),
            ("next_recommended_action", summary.get("next_recommended_action")),
            ("content_light", payload.get("content_light")),
            ("remote_mutation", payload.get("remote_mutation")),
            ("local_mutation", payload.get("local_mutation")),
            ("output_json", str(args.output_json)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
