"""Release Evidence Gate — CLI entry point.

Parses arguments, loads policy, builds check registry, runs the gate,
and writes the canonical JSON receipt to disk.

Usage:
    uv run python scripts/rig_relay_release_evidence_gate.py --repo-root . --output .build/rig-relay/release-gate-test.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rig_relay.release_gate._checks_registry import build_default_registry
from rig_relay.release_gate.models import (
    CheckContext,
    GatePolicy,
    GateResult,
    GateStatus,
)
from rig_relay.release_gate.receipt import write_receipt
from rig_relay.release_gate.runner import GateRunner

DEFAULT_OUTPUT = Path("docs/json/release/release_evidence_gate_v1.json")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_path = Path(args.output) if args.output else repo_root / DEFAULT_OUTPUT
    policy = _load_policy(args.policy, repo_root)

    registry = build_default_registry(
        repo_root=repo_root, output_dir=output_path.parent
    )

    runner = GateRunner(checks=registry, policy=policy)
    ctx = CheckContext(
        repo_root=repo_root,
        output_dir=output_path.parent,
        head_sha=_resolve_head_sha(repo_root),
        branch=_resolve_branch(repo_root),
        policy=policy,
    )

    result = runner.run(
        ctx,
        include_checks=args.include_check or None,
        exclude_checks=args.exclude_check or None,
    )

    write_receipt(result, output_path)
    _print_summary(result, output_path)

    return _exit_code(result, args.strict)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-relay-release-gate",
        description="Release Evidence Gate v1 — deterministic release readiness verdict.",
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    parser.add_argument("--output", default=None, help="Output JSON receipt path")
    parser.add_argument(
        "--format", default="json", choices=["json"], help="Output format (json only)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on warnings if policy allows",
    )
    parser.add_argument(
        "--include-check",
        action="append",
        default=[],
        dest="include_check",
        help="Only run these check IDs (repeatable)",
    )
    parser.add_argument(
        "--exclude-check",
        action="append",
        default=[],
        dest="exclude_check",
        help="Exclude these check IDs (repeatable)",
    )
    parser.add_argument("--policy", default=None, help="Path to gate policy JSON")
    return parser.parse_args(argv)


def _load_policy(policy_path: str | None, repo_root: Path) -> GatePolicy:
    path = (
        Path(policy_path)
        if policy_path
        else repo_root / "docs" / "json" / "release" / "release_gate_policy.v1.json"
    )
    if not path.is_file():
        return GatePolicy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        from rig_relay.release_gate.models import GatePolicyOverrides

        overrides = [
            GatePolicyOverrides(
                check_id=ov["check_id"],
                severity=ov.get("severity"),
                release_blocking=ov.get("release_blocking"),
            )
            for ov in data.get("overrides", [])
        ]
        return GatePolicy(
            required_checks=data.get("required_checks", []),
            overrides=overrides,
            artifact_allowlist=data.get("artifact_allowlist", []),
            cache_policy=data.get("cache_policy", "default"),
            strict_warnings_exit_nonzero=data.get(
                "strict_warnings_exit_nonzero", False
            ),
        )
    except Exception:
        return GatePolicy()


def _resolve_head_sha(repo_root: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def _resolve_branch(repo_root: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def _print_summary(result: GateResult, output_path: Path) -> None:
    s = result.summary
    status_icon = _status_icon(result.overall_status)
    print(f"\n  Release Evidence Gate v1  {status_icon}  {result.overall_status}")
    print(f"  {'─' * 48}")
    print(
        f"  Checks:  {s.total_checks} total  |  {s.passed} passed  |  {s.failed} failed  |  {s.warning} warn  |  {s.skipped} skipped"
    )
    print(f"  Findings: {s.total_findings}")
    if s.findings_by_severity:
        sev_line = "  " + "  ".join(
            f"{k}: {v}" for k, v in s.findings_by_severity.items()
        )
        print(sev_line)
    print(f"  Receipt:  {output_path}")
    print()


def _status_icon(status: GateStatus) -> str:
    match str(status):
        case "passed":
            return "✅"
        case "failed":
            return "❌"
        case "warning":
            return "⚠️"
        case "skipped":
            return "⏭️"
        case _:
            return "❓"


def _exit_code(result: GateResult, strict: bool) -> int:
    match result.overall_status:
        case _ if str(result.overall_status) == "failed":
            return 1
        case _ if str(result.overall_status) == "warning" and strict:
            policy = result.policy
            if isinstance(policy, dict) and policy.get(
                "strict_warnings_exit_nonzero", False
            ):
                return 1
            return 0
        case _:
            return 0
