#!/usr/bin/env python3
"""Rig Relay GitHub Provider Check CLI — local, no network.

Evaluates a capability operation against a local auth state and manifest,
emits receipt and optional status snapshot. Never calls GitHub.

Exit codes: 0=allowed, 1=infra/schema error, 2=refused.

Usage:
    uv run python scripts/rig_github_provider_check.py \\
        --auth-state .rig/relay/github_auth_state.v1.json \\
        --capability github.repo.metadata.read \\
        --output-root .build/rig-relay/github-provider
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider import (
    GitHubProviderAuthState,
    load_github_capability_manifest,
    read_auth_state,
)
from rig_relay.integrations.github_provider._adapter import run_local_read_operation
from rig_relay.integrations.github_provider._status import build_status_snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-provider-check",
        description="Evaluate a GitHub provider capability with local auth state.",
    )
    parser.add_argument(
        "--auth-state",
        type=Path,
        help="Path to auth state JSON (default: .rig/relay/github_auth_state.v1.json)",
    )
    parser.add_argument(
        "--capability",
        required=True,
        help="Capability ID to evaluate (e.g., github.repo.metadata.read)",
    )
    parser.add_argument(
        "--repository-hash",
        default="",
        help="SHA-256 hash of target repository (owner/repo)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / ".build" / "rig-relay" / "github-provider",
        help="Output root for receipts and snapshots",
    )
    parser.add_argument(
        "--fail-on-refusal",
        action="store_true",
        help="Exit code 2 instead of 0 for refused operations",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output receipt as JSON to stdout",
    )
    args = parser.parse_args(argv)

    if args.auth_state:
        auth = read_auth_state(args.auth_state)
    else:
        auth = GitHubProviderAuthState()

    manifest = load_github_capability_manifest()

    args.output_root.mkdir(parents=True, exist_ok=True)

    receipt = run_local_read_operation(
        operation_id="cli-op",
        capability_id=args.capability,
        auth_state=auth,
        repository_hash=args.repository_hash,
        manifest=manifest,
    )

    receipt_path = args.output_root / "operation_receipt.v1.json"
    receipt_path.write_text(
        json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    snapshot = build_status_snapshot(auth, manifest)
    snapshot_path = args.output_root / "status_snapshot.v1.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.json_output:
        print(
            json.dumps(
                {
                    "verdict": receipt.verdict,
                    "refusal_code": receipt.refusal_code,
                    "receipt_path": str(receipt_path),
                    "snapshot_path": str(snapshot_path),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print("GitHub provider check complete.")
        print(f"  Capability:      {args.capability}")
        print(f"  Verdict:         {receipt.verdict}")
        print(f"  Refusal code:    {receipt.refusal_code}")
        print(f"  Receipt:         {receipt_path}")
        print(f"  Status snapshot: {snapshot_path}")

    match receipt.verdict:
        case "allowed":
            return 0
        case "refused":
            return 2
        case "failed":
            return 1
        case _:
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
