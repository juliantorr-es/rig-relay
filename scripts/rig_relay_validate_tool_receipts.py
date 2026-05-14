#!/usr/bin/env python3
"""Read-only tool receipt content-light policy validator.

Scans an observability JSONL file for ``rig.relay.tool_receipt.captured``
events and checks them against the content-light receipt policy.

Usage:

    # Validate a single JSONL file:
    uv run python scripts/rig_relay_validate_tool_receipts.py path/to/observability.jsonl

    # Validate a session directory (finds observability.jsonl inside):
    uv run python scripts/rig_relay_validate_tool_receipts.py path/to/session/

Exit codes:
    0 — no violations found
    1 — one or more violations found
    2 — input file not found or unreadable
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


def find_observability_log(path: Path) -> Path | None:
    """Resolve an observability JSONL path from a file or session dir."""
    if path.is_file():
        return path
    if path.is_dir():
        candidate = path / "observability.jsonl"
        if candidate.is_file():
            return candidate
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(
            "Usage: uv run python scripts/rig_relay_validate_tool_receipts.py <path>",
            file=sys.stderr,
        )
        return 2

    input_path = Path(args[0])
    log_path = find_observability_log(input_path)

    if log_path is None:
        print(f"Error: No observability log found at {input_path}", file=sys.stderr)
        return 2

    from rig_relay.evidence.tool_receipt_policy import validate_file

    findings = validate_file(log_path)

    if not findings:
        result = {
            "status": "pass",
            "file": str(log_path),
            "violations": 0,
            "warnings": 0,
            "findings": [],
        }
        print(json.dumps(result, indent=2))
        return 0

    violations = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warn"]

    result = {
        "status": "fail" if violations else "warn",
        "file": str(log_path),
        "violations": len(violations),
        "warnings": len(warnings),
        "findings": [f.as_dict() for f in findings],
    }
    print(json.dumps(result, indent=2))

    if violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
