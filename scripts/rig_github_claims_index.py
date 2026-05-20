#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._claims_index import (
    build_github_claims_index,
)
from rig_relay.integrations.github_provider._redaction import safe_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_evidence_backed_claims_index_v1.v1.json"
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-claims-index",
        description="Build evidence-backed claims index from README and operating picture.",
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
        help="Output claims index artifact path.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print a compact summary."
    )
    args = parser.parse_args(argv)

    claims_index = build_github_claims_index(owner=args.owner, repo=args.repo)
    payload = safe_summary(claims_index)
    _write_json(args.output_json, payload)

    if args.summary:
        summary = payload.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows = [
            ("total_claims", summary.get("total_claims")),
            ("supported_count", summary.get("supported_count")),
            ("unsupported_count", summary.get("unsupported_count")),
            ("partially_supported_count", summary.get("partially_supported_count")),
            ("contradicted_count", summary.get("contradicted_count")),
            ("unknown_count", summary.get("unknown_count")),
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
