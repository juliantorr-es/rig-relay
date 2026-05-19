#!/usr/bin/env python3
"""Rig Relay Google Workspace Provider Check CLI — local, no network.

Exit codes: 0=allowed, 1=error, 2=refused.

Usage:
    uv run python scripts/rig_google_workspace_check.py --capability google_workspace.gmail.labels.list
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.google_workspace._adapter import run_local_workspace_read
from rig_relay.integrations.google_workspace._auth_state_store import (
    read_workspace_auth_state,
)
from rig_relay.integrations.google_workspace._models import GoogleWorkspaceAuthState
from rig_relay.integrations.google_workspace._status import build_status_snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="rig-google-workspace-check",
        description="Evaluate a Google Workspace capability with local auth state.",
    )
    p.add_argument("--auth-state", type=Path, help="Path to auth state JSON")
    p.add_argument("--capability", required=True, help="Capability ID")
    p.add_argument("--subject-hash", default="", help="SHA-256 of user subject email")
    p.add_argument("--customer-hash", default="", help="SHA-256 of customer ID")
    p.add_argument("--resource-hash", default="", help="SHA-256 of resource ID")
    p.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / ".build" / "rig-relay" / "google-workspace",
        help="Output root",
    )
    p.add_argument("--fail-on-refusal", action="store_true")
    p.add_argument("--json", action="store_true", dest="json_output")
    args = p.parse_args(argv)

    auth = (
        read_workspace_auth_state(args.auth_state)
        if args.auth_state
        else GoogleWorkspaceAuthState()
    )
    args.output_root.mkdir(parents=True, exist_ok=True)

    receipt = run_local_workspace_read(
        "cli-op",
        args.capability,
        auth,
        args.subject_hash,
        args.customer_hash,
        args.resource_hash,
    )
    rpath = args.output_root / "operation_receipt.v1.json"
    rpath.write_text(
        json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    snap = build_status_snapshot(auth)
    spath = args.output_root / "status_snapshot.v1.json"
    spath.write_text(
        json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.json_output:
        print(
            json.dumps(
                {
                    "verdict": receipt.verdict,
                    "refusal_code": receipt.refusal_code,
                    "receipt_path": str(rpath),
                    "snapshot_path": str(spath),
                },
                indent=2,
            )
        )
    else:
        print(
            f"Google Workspace check complete. Capability: {args.capability}, Verdict: {receipt.verdict}, Refusal: {receipt.refusal_code}"
        )

    match receipt.verdict:
        case "allowed":
            return 0
        case "refused":
            return 2
        case _:
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
