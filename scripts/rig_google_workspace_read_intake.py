#!/usr/bin/env python3
"""Rig Relay Google Workspace read intake CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.google_workspace._read_intake import (
    write_google_workspace_read_intake,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_read_intake_v1.v1.json"
)
DEFAULT_SCOPE_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "google_workspace_scope_manifest_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    summary_rows = [
        ("total_surfaces", summary.get("total_surfaces")),
        ("present_surfaces", summary.get("present_surfaces")),
        ("refused_surfaces", summary.get("refused_surfaces")),
        ("not_implemented_surfaces", summary.get("not_implemented_surfaces")),
        ("dry_run", report.get("dry_run")),
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
        prog="rig-google-workspace-read-intake",
        description="Collect read-only Google Workspace surface intake.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run without network calls (default).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live intake (requires RIG_LIVE_AUTH_TESTS=1).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output intake artifact path.",
    )
    parser.add_argument(
        "--scope-manifest",
        type=Path,
        default=DEFAULT_SCOPE_MANIFEST,
        help="Path to Google Workspace scope manifest.",
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

    report = write_google_workspace_read_intake(
        args.output_json,
        dry_run=args.dry_run,
        live=args.live,
        scope_manifest_path=args.scope_manifest,
        generated_at_utc=args.generated_at_utc,
    )
    if args.summary:
        _print_summary(report, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
