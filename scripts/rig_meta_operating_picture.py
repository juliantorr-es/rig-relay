#!/usr/bin/env python3
"""Rig Relay Meta operating picture CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.meta_provider._operating_picture import (
    write_meta_operating_picture,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "meta_operating_picture_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    config = report.get("configured_summary")
    if not isinstance(config, dict):
        config = {}
    surfaces = report.get("surface_summary")
    if not isinstance(surfaces, dict):
        surfaces = {}
    safety = report.get("safety_posture")
    if not isinstance(safety, dict):
        safety = {}
    next_action = report.get("next_recommended_action")
    if isinstance(next_action, list) and next_action:
        primary_action = next_action[0]
    else:
        primary_action = "no_action"

    summary_rows = [
        ("app_id_configured", config.get("app_id_configured")),
        ("access_token_configured", config.get("access_token_configured")),
        ("facebook_pages", surfaces.get("facebook_pages")),
        ("instagram_graph", surfaces.get("instagram_graph")),
        ("whatsapp_business_cloud", surfaces.get("whatsapp_business_cloud")),
        ("publishing", surfaces.get("publishing")),
        ("messaging", surfaces.get("messaging")),
        ("public_release_ready", safety.get("public_release_ready")),
        ("next_action", primary_action),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
    ]
    width = max(len(label) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-meta-operating-picture",
        description="Build the Meta provider operating picture from local configuration.",
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
        dest="generated_at",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact content-light summary."
    )
    args = parser.parse_args(argv)

    report = write_meta_operating_picture(
        args.output_json, generated_at=args.generated_at
    )
    if args.summary:
        _print_summary(report, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
