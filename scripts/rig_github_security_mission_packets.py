#!/usr/bin/env python3
"""Rig Relay GitHub security mission packet generation CLI.

Reads the canonical security mission-candidate artifact and emits a
deterministic, content-light mission packet index. Packet files are written to
the default transient packet directory unless overridden.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._security_mission_packets import (
    project_github_security_mission_packets_from_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_JSON = (
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
    / "github_security_mission_packets_v1.v1.json"
)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-security-mission-packets",
        description="Project GitHub security mission candidates into local mission packets.",
    )
    parser.add_argument(
        "--input-json",
        type=Path,
        default=DEFAULT_INPUT_JSON,
        help="Input GitHub security mission-candidate artifact.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output mission-packet index path.",
    )
    parser.add_argument(
        "--packet-dir",
        type=Path,
        default=None,
        help="Directory for per-packet JSON files. Defaults to the transient packet directory.",
    )
    parser.add_argument(
        "--timestamp-utc",
        type=str,
        default=None,
        help="Override the generation timestamp for deterministic tests.",
    )
    args = parser.parse_args(argv)

    packet_dir = args.packet_dir or (
        REPO_ROOT / ".build" / "rig-relay" / "security-mission-packets"
    )
    report = project_github_security_mission_packets_from_path(
        args.input_json,
        source_artifact_path=None,
        packet_dir=packet_dir,
        generated_at_utc=args.timestamp_utc,
    )
    _write_json(args.output_json, report)

    print(
        json.dumps(
            {
                "packet_count": report.get("packet_count", 0),
                "excluded_candidate_count": report.get("excluded_candidate_count", 0),
                "excluded_by_route": report.get("excluded_by_route", {}),
                "source_artifact_hash": report.get("source_artifact_hash", ""),
                "remote_mutation": False,
                "output_json": str(args.output_json),
                "packet_dir": str(packet_dir),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
