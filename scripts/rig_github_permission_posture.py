#!/usr/bin/env python3
"""Rig Relay GitHub App permission posture planner CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rig_relay.integrations.github_provider._live_auth import (
    GitHubPermissionMode,
    normalize_permission_mode,
)
from rig_relay.integrations.github_provider._permission_posture import (
    build_github_permission_posture_report_from_paths,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PERMISSION_MODE_ENV_KEY = "RIG_GITHUB_PERMISSION_MODE"


def _permission_mode_from_value(value: str | None) -> GitHubPermissionMode:
    return normalize_permission_mode(
        value if value is not None else os.environ.get(PERMISSION_MODE_ENV_KEY)
    )


DEFAULT_LIVE_AUTH_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "live_github_auth_result.v1.json"
)
DEFAULT_SECURITY_INTAKE_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_intake_result.v1.json"
)
DEFAULT_WORK_ITEMS_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_work_items_v1.v1.json"
)
DEFAULT_MISSION_CANDIDATES_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_app_permission_posture_v1.v1.json"
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-permission-posture",
        description="Plan GitHub App permission posture from local evidence artifacts.",
    )
    parser.add_argument(
        "--live-auth-json",
        type=Path,
        default=DEFAULT_LIVE_AUTH_JSON,
        help="Input live auth artifact path.",
    )
    parser.add_argument(
        "--security-intake-json",
        type=Path,
        default=DEFAULT_SECURITY_INTAKE_JSON,
        help="Input security intake artifact path.",
    )
    parser.add_argument(
        "--work-items-json",
        type=Path,
        default=DEFAULT_WORK_ITEMS_JSON,
        help="Input security work-item artifact path.",
    )
    parser.add_argument(
        "--mission-candidates-json",
        type=Path,
        default=DEFAULT_MISSION_CANDIDATES_JSON,
        help="Input security mission-candidate artifact path.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output permission-posture artifact path.",
    )
    parser.add_argument(
        "--timestamp-utc",
        type=str,
        default=None,
        help="Override the planner timestamp for deterministic tests.",
    )
    parser.add_argument(
        "--permission-mode",
        type=str,
        default=None,
        choices=["development_debug", "preproduction", "public_release"],
        help="Permission posture mode to record for the planner.",
    )
    args = parser.parse_args(argv)
    permission_mode = _permission_mode_from_value(args.permission_mode)

    report = build_github_permission_posture_report_from_paths(
        live_auth_json=args.live_auth_json,
        security_intake_json=args.security_intake_json,
        work_items_json=args.work_items_json,
        mission_candidates_json=args.mission_candidates_json,
        permission_mode=permission_mode,
        generated_at_utc=args.timestamp_utc,
    )
    _write_json(args.output_json, report)

    print(
        json.dumps(
            {
                "observed_permission_count": report.get("summary", {}).get(
                    "observed_permission_count", 0
                ),
                "missing_permission_count": report.get("summary", {}).get(
                    "missing_permission_count", 0
                ),
                "permission_request_count": report.get("summary", {}).get(
                    "permission_request_count", 0
                ),
                "blocked_candidate_count": report.get("summary", {}).get(
                    "blocked_candidate_count", 0
                ),
                "permission_mode": report.get("permission_mode", permission_mode.value),
                "mutation_permissions_requested": False,
                "remote_mutation": False,
                "output_json": str(args.output_json),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
