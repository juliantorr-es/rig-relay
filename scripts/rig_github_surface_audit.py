#!/usr/bin/env python3
"""Rig Relay GitHub surface steward audit CLI.

Read-only audit of GitHub-facing public surfaces. No remote mutation.
Local-only by default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._surface_audit import (
    build_github_surface_audit,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_audit_v1.v1.json"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-surface-audit",
        description="Read-only GitHub surface steward audit.",
    )
    parser.add_argument(
        "--owner", type=str, default="juliantorr-es", help="Repository owner/login."
    )
    parser.add_argument(
        "--repo", type=str, default="rig-relay", help="Repository name."
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output audit artifact path.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact summary."
    )
    args = parser.parse_args(argv)

    audit = build_github_surface_audit(owner=args.owner, repo=args.repo)
    payload = safe_summary(audit)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("total_surfaces_audited", summary.get("total_surfaces_audited")),
            ("present_surface_count", summary.get("present_surface_count")),
            ("missing_surface_count", summary.get("missing_surface_count")),
            ("stale_surface_count", summary.get("stale_surface_count")),
            ("proposal_count", summary.get("proposal_count")),
            ("remote_mutation", payload.get("remote_mutation")),
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
