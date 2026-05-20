#!/usr/bin/env python3
"""Rig Relay GitHub security/quality intake CLI.

Read-only by design. Dry-run is the default and performs no network calls.
Live mode requires RIG_LIVE_AUTH_TESTS=1 and GitHub App installation creds.
Outputs content-light JSON only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rig_relay.integrations.github_provider._live_auth import (
    GitHubPermissionMode,
    normalize_permission_mode,
)
from rig_relay.integrations.github_provider._redaction import safe_summary
from rig_relay.integrations.github_provider._security_intake import (
    build_github_security_intake_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PERMISSION_MODE_ENV_KEY = "RIG_GITHUB_PERMISSION_MODE"


def _permission_mode_from_value(value: str | None) -> GitHubPermissionMode:
    return normalize_permission_mode(
        value if value is not None else os.environ.get(PERMISSION_MODE_ENV_KEY)
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-intake",
        description="Read-only GitHub security/quality intake.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="No network calls.")
    mode.add_argument(
        "--live",
        action="store_true",
        help="Perform live read-only API calls (requires RIG_LIVE_AUTH_TESTS=1).",
    )
    parser.add_argument("--owner", required=True, help="Repository owner/login.")
    parser.add_argument("--repo", required=True, help="Repository name.")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPO_ROOT
        / "docs"
        / "json"
        / "governance"
        / "github_security_intake_result.v1.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--permission-mode",
        type=str,
        default=None,
        choices=["development_debug", "preproduction", "public_release"],
        help="Permission posture mode used for token narrowing and reporting.",
    )
    args = parser.parse_args(argv)
    permission_mode = _permission_mode_from_value(args.permission_mode)

    live = bool(args.live)
    if not live and not args.dry_run:
        args.dry_run = True

    report = build_github_security_intake_report(
        args.owner, args.repo, live=live, permission_mode=permission_mode
    )
    payload = safe_summary(report)
    _write_json(args.output_json, payload)

    print(
        json.dumps(
            {
                "schema_version": payload.get("schema_version", ""),
                "dry_run": payload.get("dry_run", False),
                "content_light": payload.get("content_light", True),
                "remote_mutation": payload.get("remote_mutation", False),
                "permission_mode": payload.get(
                    "permission_mode", permission_mode.value
                ),
                "code_scanning_total": payload.get("counts", {}).get(
                    "code_scanning_total", 0
                ),
                "dependabot_total": payload.get("counts", {}).get(
                    "dependabot_total", 0
                ),
                "refused_surfaces": payload.get("counts", {}).get(
                    "refused_surfaces", 0
                ),
                "output_json": str(args.output_json),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    if live and os.environ.get("RIG_LIVE_AUTH_TESTS") != "1":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
