"""Issue-ledger reconciliation CLI for Rig Relay.

Owns: reconciliation of validation evidence into append-only issue history.
Does not own: steward queue selection, docs rendering, or validation execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.cli._steward._issues import reconcile_issue_ledger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rig Relay issue ledger commands.")
    sub = parser.add_subparsers(dest="command", required=True)

    reconcile = sub.add_parser(
        "reconcile",
        help="Append resolved issue rows when a validation run has passed.",
    )
    reconcile.add_argument("--project-root", type=Path, default=Path.cwd())
    reconcile.add_argument(
        "--validation-run",
        type=Path,
        required=True,
        help="Path to a rig.release_gate.validation_run.v1 JSON artifact.",
    )
    reconcile.add_argument(
        "--issue-id",
        type=str,
        default=None,
        help="Resolve a specific issue id instead of auto-matching evidence.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "reconcile":
        parser.error(f"Unsupported command: {args.command}")

    root = args.project_root.resolve()
    validation_run_path = args.validation_run.resolve()
    if not validation_run_path.exists():
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "validation_run_missing",
                    "validation_run_path": str(validation_run_path),
                },
                indent=2,
            )
        )
        return 1

    validation_run = json.loads(validation_run_path.read_text(encoding="utf-8"))
    summary = reconcile_issue_ledger(
        root,
        validation_run,
        issue_id=args.issue_id,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


__all__ = ["main"]
