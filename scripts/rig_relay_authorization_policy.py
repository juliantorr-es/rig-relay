#!/usr/bin/env python3
# ruff: noqa: PLR0911
"""Rig Relay Authorization Policy — Step-Up Gate Helper.

Loads an authorization policy and validates authorization receipts against
high-authority actions.

This slice implements the policy check and receipt validator.
No real biometric/passkey flow. Dev bypass (none_dev_only) is supported.

Usage:
    uv run python scripts/rig_relay_authorization_policy.py --check-action remote_upload.confirm
    uv run python scripts/rig_relay_authorization_policy.py --validate-receipt receipt.json --action remote_upload.confirm
    uv run python scripts/rig_relay_authorization_policy.py --dev-generate-receipt --action remote_upload.confirm
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from vibe.core.auth.receipt import (
    DEFAULT_POLICY,
    action_requires_authorization,
    generate_dev_receipt,
    validate_receipt,
)


def _load_policy(path: Path | None = None) -> dict[str, Any]:
    """Load authorization policy from path or return defaults."""
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return dict(DEFAULT_POLICY)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rig Relay Authorization Policy — Step-Up Gate Helper"
    )
    parser.add_argument(
        "--check-action",
        type=str,
        default=None,
        help="Check whether an action requires authorization.",
    )
    parser.add_argument(
        "--validate-receipt",
        type=Path,
        default=None,
        help="Validate an authorization receipt against an action.",
    )
    parser.add_argument(
        "--action",
        type=str,
        default=None,
        help="Action name for validation or receipt generation.",
    )
    parser.add_argument(
        "--action-scope",
        type=Path,
        default=None,
        help="Path to a JSON file with action scope (target_sha256, target_path).",
    )
    parser.add_argument(
        "--dev-generate-receipt",
        action="store_true",
        default=False,
        help="Generate a dev/test authorization receipt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for generated receipt JSON.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="Path to a custom authorization policy JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.check_action:
        requires = action_requires_authorization(args.check_action)
        status = (
            "requires authorization" if requires else "read-only (no auth required)"
        )
        print(f"Action '{args.check_action}': {status}")
        return 0

    if args.validate_receipt:
        if not args.action:
            print("Error: --action required for receipt validation", file=sys.stderr)
            return 1
        try:
            receipt = json.loads(args.validate_receipt.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        scope = None
        if args.action_scope:
            scope = json.loads(args.action_scope.read_text(encoding="utf-8"))

        valid, reason = validate_receipt(receipt, args.action, action_scope=scope)
        status = "VALID" if valid else "INVALID"
        print(f"Receipt {args.validate_receipt}: {status} — {reason}")
        return 0 if valid else 1

    if args.dev_generate_receipt:
        if not args.action:
            print("Error: --action required for receipt generation", file=sys.stderr)
            return 1
        scope = None
        if args.action_scope:
            scope = json.loads(args.action_scope.read_text(encoding="utf-8"))
        receipt = generate_dev_receipt(args.action, action_scope=scope)
        if args.output:
            args.output.write_text(json.dumps(receipt, indent=2) + "\n")
            print(f"Dev receipt written to {args.output}")
        else:
            print(json.dumps(receipt, indent=2))
        return 0

    print(
        "No action specified. Use --check-action, --validate-receipt, or --dev-generate-receipt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
