#!/usr/bin/env python3
"""Rig Relay profile README live check CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.integrations.github_provider._profile_readme_live_check import (
    is_live_auth_available,
    write_profile_readme_check_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "json" / "governance"


def _print_summary(
    check: dict[str, object], preview: dict[str, object], audit: dict[str, object]
) -> None:
    perm_class = audit.get("permission_classification")
    publish_possible = "N/A"
    if isinstance(perm_class, dict):
        publish_possible = perm_class.get("publish_possible", "N/A")
    rows = [
        ("owner", check.get("owner")),
        ("profile_repo", check.get("profile_repo_name")),
        ("profile_repo_exists", check.get("profile_repo_exists")),
        ("readme_exists", check.get("readme_exists")),
        ("status", check.get("status")),
        ("preview_status", preview.get("preview_status")),
        ("dry_run", check.get("dry_run")),
        ("live_network", check.get("live_network")),
        ("remote_mutation", preview.get("remote_mutation")),
        ("content_light", preview.get("content_light")),
        ("publish_possible", publish_possible),
        ("recommended_action", audit.get("recommended_action")),
    ]
    width = max(len(str(k)) for k, _ in rows)
    for label, value in rows:
        print(f"{label:<{width}}  {value}")

    perms = audit.get("explicitly_not_required")
    if isinstance(perms, list) and perms:
        print("\nExplicitly not required:")
        for p in perms:
            if isinstance(p, dict):
                print(f"  - {p.get('permission_id')}: {p.get('reason')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-profile-readme-live-check",
        description="Check GitHub profile README status, generate preview, and audit publish PR permissions.",
    )
    parser.add_argument(
        "--owner",
        type=str,
        required=True,
        help="GitHub username/owner for profile README check.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for artifacts.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live network check (requires RIG_LIVE_AUTH_TESTS=1 and valid token).",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
    )
    parser.add_argument("--summary", action="store_true", help="Print compact summary.")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Allow remote PR creation. Default: dry-run only.",
    )
    args = parser.parse_args(argv)

    dry_run = not args.live
    if args.live and not is_live_auth_available():
        print(
            "Live mode requested but RIG_LIVE_AUTH_TESTS is not set. Falling back to dry-run."
        )
        dry_run = True

    access_token = ""
    if args.live and is_live_auth_available():
        import os

        access_token = os.environ.get("GITHUB_TOKEN", "")

    check, preview, audit = write_profile_readme_check_artifacts(
        args.owner,
        output_dir=args.output_dir,
        dry_run=dry_run,
        access_token=access_token,
        generated_at_utc=args.generated_at_utc,
    )

    if args.summary:
        _print_summary(check, preview, audit)

    # Generate PR plan (always dry-run by default)
    from rig_relay.integrations.github_provider._profile_readme_pr_plan import (
        write_pr_plan_artifacts,
    )

    plan = write_pr_plan_artifacts(
        args.owner,
        allow_publish=args.publish,
        generated_at_utc=args.generated_at_utc,
        output_dir=args.output_dir,
    )
    if args.summary:
        print(f"\nPR Plan: {plan['publish_gate_status']}")
        for r in plan.get("blocked_reasons", []):
            print(f"  blocked: {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
