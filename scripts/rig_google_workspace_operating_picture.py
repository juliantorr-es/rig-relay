#!/usr/bin/env python3
"""Rig Relay Google Workspace operating picture CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.google_workspace._operating_picture import (
    write_google_workspace_operating_picture,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_operating_picture_v1.v1.json"
)


def _print_summary(report: dict[str, object], output_json: Path) -> None:
    auth_summary = report.get("auth_summary")
    scope_posture = report.get("scope_posture")
    refusals = report.get("refusals")
    if not isinstance(auth_summary, dict):
        auth_summary = {}
    if not isinstance(scope_posture, dict):
        scope_posture = {}
    refusal_count = len(refusals) if isinstance(refusals, list) else 0

    summary_rows = [
        ("oauth_configured", auth_summary.get("oauth_configured")),
        ("token_hash_present", auth_summary.get("token_hash_present")),
        ("requested_scope_count", auth_summary.get("requested_scope_count")),
        ("restricted_scope_count", auth_summary.get("restricted_scope_count")),
        ("consent_mode", auth_summary.get("consent_mode")),
        ("verification_required", scope_posture.get("verification_required")),
        ("public_release_ready", scope_posture.get("public_release_ready")),
        ("refusal_count", refusal_count),
        ("output_json", str(output_json)),
        ("remote_mutation", report.get("remote_mutation")),
        ("content_light", report.get("content_light")),
    ]
    width = max(len(label) for label, _ in summary_rows)
    for label, value in summary_rows:
        print(f"{label:<{width}}  {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-google-workspace-operating-picture",
        description="Build the Google Workspace provider operating picture from local artifacts.",
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
        "--fail-on-missing-auth",
        action="store_true",
        help="Exit non-zero if auth is not configured.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact content-light summary."
    )
    args = parser.parse_args(argv)

    report = write_google_workspace_operating_picture(
        args.output_json, generated_at_utc=args.generated_at_utc
    )
    if args.summary:
        _print_summary(report, args.output_json)

    if args.fail_on_missing_auth:
        auth_summary = report.get("auth_summary")
        if isinstance(auth_summary, dict) and not auth_summary.get("oauth_configured"):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
