#!/usr/bin/env python3
"""MCP Hardened Read-Only Surface Release Gate Runner.

Runs all MCP hardening phase tests and emits structured JSON gate result.
Usage:
    uv run python scripts/rig_mcp_hardened_read_only_gate.py [--json]

Exit code:
    0 — all tests passed
    1 — one or more tests failed or could not be imported
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MCP_TEST_FILES = [
    "tests/protocols/mcp/test_mcp_descriptor_integrity_v1.py",
    "tests/protocols/mcp/test_mcp_roots_boundary_v1.py",
    "tests/protocols/mcp/test_mcp_content_light_v1.py",
    "tests/protocols/mcp/test_mcp_receipt_envelope_adoption.py",
    "tests/protocols/mcp/test_mcp_scan_receipt_convergence_v1.py",
    "tests/protocols/mcp/test_mcp_auth_v1.py",
]

INVARIANTS = [
    "descriptor_integrity: verify_hash_on_dispatch_and_list",
    "roots_boundary: refuse_traversal_symlink_escape",
    "content_light_scan: classify_output_refuse_secret_and_forbidden",
    "receipt_persistence: persist_every_outcome_when_store_provided",
    "local_session_auth: refuse_missing_or_invalid_token_before_dispatch",
    "pipeline_order: auth_before_descriptor_before_tier_before_dispatch",
    "token_safety: raw_token_never_in_response_log_or_error",
    "mutation_blocked: tier_4_5_permanently_blocked",
]


def _get_head_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _get_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def run_gate(json_output: bool = False) -> int:
    head = _get_head_commit()
    branch = _get_branch()
    test_args = [
        "uv",
        "run",
        "pytest",
        *MCP_TEST_FILES,
        "-q",
        "--tb=no",
        "--override-ini=addopts=",
        "--noconftest",
    ]

    start = datetime.now(UTC)
    result = subprocess.run(test_args, capture_output=True, text=True, cwd=REPO_ROOT)
    elapsed_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)

    passed = False
    test_count = 0
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if "passed" in line and "failed" not in line:
                try:
                    parts = line.split()
                    test_count = int(parts[0])
                    passed = True
                except (ValueError, IndexError):
                    pass

    gate_result = {
        "schema_version": "rig.relay.mcp_hardened_read_only_surface_release_gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "branch": branch,
        "head_commit": head,
        "test_count": test_count,
        "passed": passed,
        "elapsed_ms": elapsed_ms,
        "invariants_protected": INVARIANTS,
        "verdict": "PASS" if passed else "FAIL",
    }

    if json_output:
        print(json.dumps(gate_result, indent=2))
    else:
        status = f"{test_count} passed" if passed else "FAIL"
        print(f"MCP Hardened Read-Only Gate: {status} ({elapsed_ms}ms)")
        print(f"  invariants: {len(INVARIANTS)} protected")
        if not passed:
            print("  stdout:", result.stdout[-500:] if result.stdout else "none")
            print("  stderr:", result.stderr[-500:] if result.stderr else "none")

    return 0 if passed else 1


if __name__ == "__main__":
    json_mode = "--json" in sys.argv
    sys.exit(run_gate(json_output=json_mode))
