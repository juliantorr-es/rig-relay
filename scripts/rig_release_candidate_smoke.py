#!/usr/bin/env python3
"""Batteries-included release candidate smoke test.

Runs a bounded local path with no live network by default and emits a
structured smoke report. Each check gates on a specific release surface.

Usage:
    uv run python scripts/rig_release_candidate_smoke.py
    uv run python scripts/rig_release_candidate_smoke.py --run-id my-run
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD_DIR = _REPO_ROOT / ".build" / "rig-relay" / "release-candidate-smoke"

SMOKE_REPORT_SCHEMA = "rig.relay.release_candidate_smoke.v1"


def _compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd or _REPO_ROOT),
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_schema_validation() -> dict:
    """Run schema validation script."""
    started = time.monotonic()
    code, stdout, stderr = _run_cmd(
        ["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"], timeout=300
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    passed = code == 0 and "All schemas valid" in stdout
    total = 0
    for line in stdout.split("\n"):
        if "Total:" in line:
            try:
                total = int(line.split(":")[1].strip())
            except ValueError:
                pass
    return {
        "check_id": "schema_validation",
        "status": "pass" if passed else "fail",
        "duration_ms": elapsed_ms,
        "detail": f"{total} schemas validated" if total else stdout[:200],
        "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
    }


def check_cli_entrypoints() -> list[dict]:
    """Smoke the CLI entrypoints."""
    results = []
    for entrypoint, args in [("rig-relay", ["--help"]), ("rig-relay-acp", ["--help"])]:
        started = time.monotonic()
        code, stdout, _ = _run_cmd(["uv", "run", entrypoint, *args], timeout=30)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        results.append({
            "check_id": f"cli_{entrypoint.replace('-', '_')}_help",
            "status": "pass" if code == 0 else "fail",
            "duration_ms": elapsed_ms,
            "detail": f"exit={code}, output={len(stdout)} chars",
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        })
    return results


def check_protocol_sdk_smoke() -> list[dict]:
    """Run SDK and A2A tests without network."""
    results = []
    for test_path, label in [
        ("tests/sdk/test_sdk_v1.py", "sdk_v1"),
        ("tests/protocols/a2a/test_a2a_v1.py", "a2a_v1"),
    ]:
        started = time.monotonic()
        code, stdout, stderr = _run_cmd(
            ["uv", "run", "pytest", test_path, "-v", "--tb=short"], timeout=120
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        results.append({
            "check_id": f"test_{label}",
            "status": "pass" if code == 0 else "fail",
            "duration_ms": elapsed_ms,
            "detail": f"exit={code}" if code != 0 else "all tests passed",
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        })
    return results


def check_ci_evidence_production() -> dict:
    """Produce CI evidence artifact."""
    started = time.monotonic()
    try:
        code, stdout, stderr = _run_cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.ci_evidence import produce_ci_evidence; "
                "result = produce_ci_evidence(job_name='smoke_test', conclusion='success'); "
                "print(f'verdict={result.verdict}'); "
                "print(f'reasons={result.blocking_reasons}')",
            ],
            timeout=60,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = code == 0 and "verdict=pass" in stdout
        return {
            "check_id": "ci_evidence_production",
            "status": "pass" if passed else "fail",
            "duration_ms": elapsed_ms,
            "detail": stdout[:200] if stdout else f"exit={code}",
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "check_id": "ci_evidence_production",
            "status": "fail",
            "duration_ms": elapsed_ms,
            "detail": str(e)[:200],
            "output_hash": "",
        }


def check_pyproject_parseable() -> dict:
    """Verify pyproject.toml parses."""
    started = time.monotonic()
    try:
        code, stdout, stderr = _run_cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(f'name={d[\"project\"][\"name\"]}'); print(f'version={d[\"project\"][\"version\"]}')",
            ],
            timeout=30,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = code == 0 and "name=rig-relay" in stdout
        return {
            "check_id": "pyproject_parseable",
            "status": "pass" if passed else "fail",
            "duration_ms": elapsed_ms,
            "detail": stdout.strip()[:200],
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "check_id": "pyproject_parseable",
            "status": "fail",
            "duration_ms": elapsed_ms,
            "detail": str(e)[:200],
            "output_hash": "",
        }


def check_mcp_local_runtime() -> dict:
    """Verify MCP models import and server class exists."""
    started = time.monotonic()
    try:
        code, stdout, stderr = _run_cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.protocols.mcp.server import RigMCPServer; "
                "from rig_relay.protocols.mcp.models import MCPToolTier, READ_ONLY_TOOLS, GATED_TOOLS; "
                "s = RigMCPServer(); "
                "print(f'tools={len(s.list_tools())}'); "
                "print(f'resources={len(s.list_resources())}'); "
                "print(f'prompts={len(s.list_prompts())}'); "
                "print('mcp_server_ok')",
            ],
            timeout=30,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = code == 0 and "mcp_server_ok" in stdout
        return {
            "check_id": "mcp_local_runtime",
            "status": "pass" if passed else "fail",
            "duration_ms": elapsed_ms,
            "detail": stdout.strip()[:200] if stdout else f"exit={code}",
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "check_id": "mcp_local_runtime",
            "status": "fail",
            "duration_ms": elapsed_ms,
            "detail": str(e)[:200],
            "output_hash": "",
        }


def check_acp_local_runtime() -> dict:
    """Verify ACP disabled tools module imports correctly."""
    started = time.monotonic()
    try:
        code, stdout, stderr = _run_cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.acp._disabled_tools import NON_INTERACTIVE_DISABLED_TOOLS; "
                "assert isinstance(NON_INTERACTIVE_DISABLED_TOOLS, list); "
                "assert 'exit_plan_mode' in NON_INTERACTIVE_DISABLED_TOOLS; "
                "print(f'acp_disabled_tools_count={len(NON_INTERACTIVE_DISABLED_TOOLS)}'); "
                "print('acp_local_ok')",
            ],
            timeout=30,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = code == 0 and "acp_local_ok" in stdout
        return {
            "check_id": "acp_local_runtime",
            "status": "pass" if passed else "fail",
            "duration_ms": elapsed_ms,
            "detail": stdout.strip()[:200] if stdout else f"exit={code}",
            "output_hash": _compute_sha256(stdout)[:16] if stdout else "",
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "check_id": "acp_local_runtime",
            "status": "fail",
            "duration_ms": elapsed_ms,
            "detail": str(e)[:200],
            "output_hash": "",
        }


def check_no_raw_secrets() -> dict:
    """Scan for raw secrets in repo artifacts."""
    started = time.monotonic()
    secret_patterns = [
        r"sk-[a-zA-Z0-9]{20,}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"github_pat_[a-zA-Z0-9_]{22,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"ya29\.[0-9A-Za-z\-_]+",
    ]
    found = []
    scan_dirs = ["rig_relay/", "scripts/", "tests/"]
    for d in scan_dirs:
        path = _REPO_ROOT / d
        if not path.exists():
            continue
        for pattern in secret_patterns:
            result = subprocess.run(
                ["rg", "-l", pattern, str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                found.extend(result.stdout.strip().split("\n"))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    passed = len(found) == 0
    return {
        "check_id": "no_raw_secrets",
        "status": "pass" if passed else "warn",
        "duration_ms": elapsed_ms,
        "detail": "no secrets found"
        if passed
        else f"potential secrets in: {found[:5]}",
        "output_hash": _compute_sha256(json.dumps(found))[:16] if found else "",
    }


def check_docs_json_validity() -> dict:
    """Verify all JSON artifacts under docs/json/ are valid JSON."""
    started = time.monotonic()
    errors = []
    doc_json = _REPO_ROOT / "docs" / "json"
    if doc_json.exists():
        for f in doc_json.rglob("*.json"):
            try:
                json.loads(f.read_text())
            except json.JSONDecodeError as e:
                errors.append(f"{f.relative_to(_REPO_ROOT)}: {e}")
    elapsed_ms = int((time.monotonic() - started) * 1000)
    passed = len(errors) == 0
    return {
        "check_id": "docs_json_validity",
        "status": "pass" if passed else "fail",
        "duration_ms": elapsed_ms,
        "detail": "all valid" if passed else str(errors[:3])[:200],
        "output_hash": "",
    }


def check_release_gate_artifacts() -> dict:
    """Verify release gate artifacts exist and are valid JSON."""
    started = time.monotonic()
    artifacts = [
        "docs/json/release_gate/rc_readiness_gate.v1.json",
        "docs/json/release_gate/rc_candidate_verdict.v1.json",
        "docs/json/release_gate/rc_blockers.v1.jsonl",
        "docs/json/release_gate/rc_deferred_risks.v1.jsonl",
        "docs/json/release_candidate/rc_installability_verdict.v1.json",
        "docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
        "docs/json/protocols/a2a_promotion_readiness.v1.json",
    ]
    missing = []
    for path in artifacts:
        if not (_REPO_ROOT / path).exists():
            missing.append(path)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    passed = len(missing) == 0
    return {
        "check_id": "release_gate_artifacts",
        "status": "pass" if passed else "fail",
        "duration_ms": elapsed_ms,
        "detail": "all present" if passed else f"missing: {missing}",
        "output_hash": "",
    }


def run_smoke() -> dict:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    checks = []
    overall = "pass"

    # Schema validation
    checks.append(check_schema_validation())

    # CLI entrypoints
    checks.extend(check_cli_entrypoints())

    # Protocol SDK tests
    checks.extend(check_protocol_sdk_smoke())

    # CI evidence
    checks.append(check_ci_evidence_production())

    # pyproject.toml
    checks.append(check_pyproject_parseable())

    # MCP local runtime
    checks.append(check_mcp_local_runtime())

    # ACP local runtime
    checks.append(check_acp_local_runtime())

    # Secret scan
    checks.append(check_no_raw_secrets())

    # Docs JSON validity
    checks.append(check_docs_json_validity())

    # Release gate artifacts
    checks.append(check_release_gate_artifacts())

    # Determine overall status
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "pass_with_warnings"

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    warned = sum(1 for c in checks if c["status"] == "warn")

    return {
        "schema_version": SMOKE_REPORT_SCHEMA,
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "checks_total": len(checks),
        "checks_passed": passed,
        "checks_failed": failed,
        "checks_warned": warned,
        "checks": checks,
        "telemetry_redaction_notes": (
            "No raw content, secrets, or private data in smoke report. "
            "Output hashes use SHA-256 truncated to 16 chars."
        ),
        "network_enabled": False,
        "external_provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batteries-included release candidate smoke test"
    )
    parser.add_argument("--run-id", help="Override auto-generated run ID", default="")
    parser.add_argument(
        "--json", action="store_true", help="Output only the JSON report to stdout"
    )
    args = parser.parse_args()

    print("Rig Relay — Batteries-Included Release Candidate Smoke", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    report = run_smoke()

    if args.run_id:
        report["run_id"] = args.run_id

    run_dir = _BUILD_DIR / report["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "smoke_report.v1.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nReport: {report_path}", file=sys.stderr)
    print(f"Status: {report['overall_status']}", file=sys.stderr)
    print(
        f"Passed: {report['checks_passed']}/{report['checks_total']}", file=sys.stderr
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for c in report["checks"]:
            icon = {"pass": "[PASS]", "fail": "[FAIL]", "warn": "[WARN]"}.get(
                c["status"], "[????]"
            )
            print(f"  {icon} {c['check_id']}: {c['detail']}", file=sys.stderr)

    if report["overall_status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
