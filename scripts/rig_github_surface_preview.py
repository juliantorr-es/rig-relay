#!/usr/bin/env python3
"""Rig Relay GitHub surface preview CLI.

Local dry-run preview of GitHub public surface mutations. No remote mutation.
Simulates what would change without writing files or mutating remote surfaces.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._surface_preview import (
    build_github_surface_preview,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKETS_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-surface-preview",
        description="Local dry-run preview of GitHub public surface mutations.",
    )
    parser.add_argument(
        "--packets-json",
        type=Path,
        default=DEFAULT_PACKETS_JSON,
        help="Path to surface packets JSON input.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output preview artifact path.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact summary."
    )
    args = parser.parse_args(argv)

    preview = build_github_surface_preview(
        packets_path=args.packets_json, output_path=args.output_json
    )
    payload = safe_summary(preview)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("total_packets", summary.get("total_packets")),
            ("previewed_count", summary.get("previewed_count")),
            ("blocked_count", summary.get("blocked_count")),
            ("not_rendered_count", summary.get("not_rendered_count")),
            ("remote_mutation", payload.get("remote_mutation")),
            ("local_mutation", payload.get("local_mutation")),
            ("content_light", payload.get("content_light")),
            ("next_recommended_action", summary.get("next_recommended_action")),
            ("output_json", str(args.output_json)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
