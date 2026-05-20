#!/usr/bin/env python3
"""Rig Relay — first governed live GitHub PR write CLI.

Branch → file → PR. Gated. Alert deferred. Default blocked.

Usage (dry/summary):
  uv run python scripts/rig_github_execute_live_pr_write.py --summary

Usage (live, all gates must pass):
  RIG_LIVE_AUTH_TESTS=1 uv run python scripts/rig_github_execute_live_pr_write.py \\
    --execute-remote-mutation \\
    --i-understand-this-creates-a-real-pr \\
    --allow-live-writes \\
    --summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.integrations.github_provider._code_scanning_live_pr_rehearsal import (
    build_operator_checklist,
    build_live_pr_rehearsal,
)
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)
from rig_relay.integrations.github_provider._real_github_boundary import (
    create_real_boundary,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOV = REPO_ROOT / "docs" / "json" / "governance"
BUILD = REPO_ROOT / ".build" / "rig-relay" / "evidence"

_EXECUTION_JSON = GOV / "github_live_pr_write_execution_v1.v1.json"
_RECEIPT_JSON = GOV / "github_live_pr_write_receipt_v1.v1.json"
_RESULT_JSON = GOV / "github_live_pr_write_result_v1.v1.json"
_OPERATOR_JSON = GOV / "github_live_pr_operator_command_v1.v1.json"
_REPORT_JSON = BUILD / "live_pr_write_execution_v1_report.v1.json"

_FORBIDDEN = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "code_snippet",
    "vulnerable_code",
    "secret_value",
    "file_body",
    "auth_header",
    "bearer",
    "source_content",
    "raw_file",
})

_LIVE_ENV = "RIG_LIVE_AUTH_TESTS"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _assert_clean(s: str) -> None:
    for k in _FORBIDDEN:
        if f'"{k}"' in s:
            raise ValueError(f"forbidden:{k}")
    for pat in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        if pat in s:
            raise ValueError(f"forbidden_pattern:{pat}")


def run_live_pr_write(
    *,
    execute_remote: bool = False,
    operator_acknowledged: bool = False,
    allow_writes: bool = False,
    approval: bool = False,
    simulate: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, object]:
    fb = (
        FakeGitHubBoundary()
        if simulate
        else create_real_boundary("juliantorr-es", "rig-relay")
    )
    report = build_live_pr_rehearsal(
        allow_execute=execute_remote,
        operator_acknowledged=operator_acknowledged,
        allow_live_writes=allow_writes,
        approval_ok=approval,
        fake_boundary=fb,
        generated_at_utc=generated_at_utc,
    )

    # Always write the execution + receipt + result artifacts
    gen_at = generated_at_utc or _now_iso()
    execution = {
        "schema_version": "rig.github.live_pr_write_execution.v1",
        "generated_at": gen_at,
        "content_light": True,
        "status": report["status"],
        "gates": report["gates"],
        "blocked_reasons": report["blocked_reasons"],
        "remote_mutation_attempted": report["remote_mutation_succeeded"],
    }
    receipt = {
        "schema_version": "rig.github.live_pr_write_receipt.v1",
        "generated_at": gen_at,
        "content_light": True,
        "branch_created": report["branch_created"],
        "file_written": report["file_written"],
        "pr_created": report["pr_created"],
        "alert_updated": report["alert_updated"],
        "alert_update_deferred": report["alert_update_deferred"],
        "pr_merged": report["pr_merged"],
    }
    result = {
        "schema_version": "rig.github.live_pr_write_result.v1",
        "generated_at": gen_at,
        "content_light": True,
        "live_mutation_succeeded": report["remote_mutation_succeeded"],
        "status": report["status"],
        "blocked_reasons": report["blocked_reasons"],
    }

    checklist = build_operator_checklist(
        "rig/security/fix-5", "README.md", "candidate-hash"
    )
    operator_cmd = {
        "schema_version": "rig.github.live_pr_operator_command.v1",
        "generated_at": gen_at,
        "content_light": True,
        "canonical_script": "scripts/rig_github_execute_live_pr_write.py",
        "dry_summary_command": "uv run python scripts/rig_github_execute_live_pr_write.py --summary",
        "live_readiness_command": f"{_LIVE_ENV}=1 uv run python scripts/rig_github_execute_live_pr_write.py --execute-remote-mutation --i-understand-this-creates-a-real-pr --allow-live-writes --summary",
        "live_execution_command": f"{_LIVE_ENV}=1 uv run python scripts/rig_github_execute_live_pr_write.py --execute-remote-mutation --i-understand-this-creates-a-real-pr --allow-live-writes",
        "required_env": [_LIVE_ENV],
        "required_flags": [
            "--execute-remote-mutation",
            "--i-understand-this-creates-a-real-pr",
            "--allow-live-writes",
        ],
        "required_artifacts": [str(checklist) if isinstance(checklist, dict) else ""],
        "expected_operations": ["create_branch", "write_file", "create_pr"],
        "forbidden_operations": [
            "alert_update",
            "pr_merge",
            "default_branch_write",
            "workflow_path_write",
        ],
        "redaction_status": {"content_light": True},
        "live_mutation_attempted": False,
        "remote_mutation_attempted": False,
        "result_status": "blocked"
        if not report["remote_mutation_succeeded"]
        else "ready",
    }

    _write_json(_EXECUTION_JSON, execution)
    _write_json(_RECEIPT_JSON, receipt)
    _write_json(_RESULT_JSON, result)
    _write_json(_OPERATOR_JSON, operator_cmd)
    _write_json(_REPORT_JSON, {"status": report["status"], **report})

    s = json.dumps(report, sort_keys=True)
    _assert_clean(s)
    return report


def _print_summary(report: dict[str, object]) -> None:
    print("\nLive PR Write Summary")
    print("-" * 22)
    rows: list[tuple[str, object]] = [
        ("status", report.get("status")),
        ("branch_created", report.get("branch_created")),
        ("file_written", report.get("file_written")),
        ("pr_created", report.get("pr_created")),
        ("alert_deferred", report.get("alert_update_deferred")),
        ("pr_merged", report.get("pr_merged")),
    ]
    for label, value in rows:
        print(f"  {label:<16} {value}")
    blocked = report.get("blocked_reasons")
    if isinstance(blocked, list) and blocked:
        print(f"\n  Blocked gates ({len(blocked)}):")
        for r in blocked:
            print(f"    - {r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-execute-live-pr-write",
        description="First governed live GitHub PR write CLI.",
    )
    parser.add_argument(
        "--execute-remote-mutation",
        action="store_true",
        help="Allow real GitHub branch/file/PR creation.",
    )
    parser.add_argument(
        "--i-understand-this-creates-a-real-pr",
        action="store_true",
        help="Operator confirmation.",
    )
    parser.add_argument(
        "--allow-live-writes", action="store_true", help="Enable live writes."
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use fake GitHub boundary (default: no boundary unless simulating).",
    )
    parser.add_argument(
        "--approval", action="store_true", help="Approval receipt present."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--generated-at-utc", type=str, default=None)
    args = parser.parse_args(argv)

    report = run_live_pr_write(
        execute_remote=args.execute_remote_mutation,
        operator_acknowledged=args.i_understand_this_creates_a_real_pr,
        allow_writes=args.allow_live_writes,
        approval=args.approval,
        simulate=args.simulate,
        generated_at_utc=args.generated_at_utc,
    )

    if args.summary:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
