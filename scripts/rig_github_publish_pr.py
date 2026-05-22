#!/usr/bin/env python3
"""Rig Relay GitHub Publish PR CLI.

Produces a PR proposal for the GitHub Public Surface Program.
Dry-run by default. Remote mutation requires explicit --execute-remote.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.cli.governance_guard import (
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.integrations.github_provider._publish_pr import build_github_publish_pr
from rig_relay.integrations.github_provider._redaction import safe_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_publish_pr_v1.v1.json"
)
DEFAULT_PACKETS_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)
DEFAULT_PREVIEW_JSON = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_preview_v1.v1.json"
)

_USAGE = """\
uv run python scripts/rig_github_publish_pr.py \\
  --packets-json docs/json/governance/github_surface_packets_v1.v1.json \\
  --preview-json docs/json/governance/github_surface_preview_v1.v1.json \\
  --output-json docs/json/governance/github_publish_pr_v1.v1.json \\
  --summary"""


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-publish-pr",
        description="Produce a PR proposal for the GitHub Public Surface Program.",
        epilog=f"Example:\n{_USAGE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--packets-json",
        type=Path,
        default=DEFAULT_PACKETS_JSON,
        help="Path to surface packets JSON.",
    )
    parser.add_argument(
        "--preview-json",
        type=Path,
        default=DEFAULT_PREVIEW_JSON,
        help="Path to surface preview JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output publish PR artifact path.",
    )
    parser.add_argument("--summary", action="store_true", help="Print compact summary.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run mode: proposal only, no remote mutation (default).",
    )
    parser.add_argument(
        "--execute-remote",
        action="store_true",
        default=False,
        help="Execute remote PR creation. Requires --dry-run to be unset.",
    )
    args = parser.parse_args(argv)

    if args.execute_remote:
        governed = require_governed_execution_with_evidence(
            script_name="rig_github_publish_pr",
            authority_tier="remote_mutation",
            capability_id="github_pr_publish",
            execute_requested=True,
            allow_mutation=True,
            allow_network=True,
        )
        if governed.decision.decision.value in {"blocked", "requires_review"}:
            result = emit_structured_result(
                script_name="rig_github_publish_pr",
                authority_tier="remote_mutation",
                capability_id="github_pr_publish",
                dry_run=False,
                execute_requested=True,
                decision=governed.decision,
                status="blocked_by_governance",
                can_execute=governed.can_execute,
                evidence_ref=governed.evidence_ref,
                evidence_status=governed.evidence_status,
            )
            print(json.dumps(result, indent=2))
            return 1

    report = build_github_publish_pr(
        packets_path=args.packets_json,
        preview_path=args.preview_json,
        dry_run=args.dry_run,
        execute_remote=args.execute_remote,
    )
    payload = safe_summary(report)
    _write_json(args.output_json, payload)

    if args.summary:
        proposal = payload.get("proposal", {})
        if not isinstance(proposal, dict):
            proposal = {}
        rows = [
            ("schema_version", payload.get("schema_version")),
            ("mode", payload.get("mode")),
            ("result_status", payload.get("result_status")),
            ("dry_run", payload.get("dry_run")),
            ("execute_remote", payload.get("execute_remote_flag_passed")),
            ("remote_mutation", payload.get("remote_mutation")),
            ("local_mutation", payload.get("local_mutation")),
            ("proposed_branch", proposal.get("proposed_branch")),
            ("proposed_pr_title", proposal.get("proposed_pr_title")),
            ("refusal_count", len(payload.get("refusal_reasons", []))),
            ("remaining_seams", len(payload.get("remaining_seams", []))),
            ("output_json", str(args.output_json)),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{width}}  {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
