#!/usr/bin/env python3
"""Rig Relay GitHub security work-item projection CLI.

Reads the canonical security intake artifact and emits a deterministic,
content-light work-item projection. No network. No secrets. No mutation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._security_work_items import (
    project_github_security_work_items_from_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_intake_result.v1.json"
)
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_security_work_items_v1.v1.json"
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-work-items",
        description="Project GitHub security intake into local work-item candidates.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_INPUT_JSON,
        help="Input GitHub security intake artifact.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output work-item artifact path.",
    )
    parser.add_argument(
        "--timestamp-utc",
        type=str,
        default=None,
        help="Override the projection timestamp for deterministic tests.",
    )
    args = parser.parse_args(argv)

    report = project_github_security_work_items_from_path(
        args.input_json, generated_at_utc=args.timestamp_utc
    )
    _write_json(args.output_json, report)

    print(
        json.dumps(
            {
                "work_item_count": report.get("work_item_count", 0),
                "candidate_group_count": report.get("candidate_group_count", 0),
                "refused_surface_count": report.get("refused_surface_count", 0),
                "output_json": str(args.output_json),
                "remote_mutation": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
