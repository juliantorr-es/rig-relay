#!/usr/bin/env python3
"""Rig Relay GitHub security mission candidate routing CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._security_mission_candidates import (
    route_github_security_work_items_from_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_work_items_v1.v1.json"
)
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_candidates_v1.v1.json"
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-mission-candidates",
        description="Route GitHub security work items into local mission candidates.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_INPUT_JSON,
        help="Input GitHub security work-item artifact.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output mission-candidate artifact path.",
    )
    parser.add_argument(
        "--timestamp-utc",
        type=str,
        default=None,
        help="Override the routing timestamp for deterministic tests.",
    )
    args = parser.parse_args(argv)

    report = route_github_security_work_items_from_path(
        args.input_json, generated_at_utc=args.timestamp_utc
    )
    _write_json(args.output_json, report)

    print(
        json.dumps(
            {
                "mission_candidate_count": report.get("mission_candidate_count", 0),
                "route_group_count": report.get("route_group_count", 0),
                "ready_candidate_count": report.get("ready_candidate_count", 0),
                "blocked_candidate_count": report.get("blocked_candidate_count", 0),
                "advisory_candidate_count": report.get("advisory_candidate_count", 0),
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
