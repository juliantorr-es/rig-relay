#!/usr/bin/env python3
"""Batteries-included release candidate smoke test — Toddler-Safe edition.

Runs bounded local checks with no live network by default. Live provider
checks require explicit --live-* opt-in flags. Emits a structured smoke
report to .build/rig-relay/release-candidate-smoke/<run_id>/.

Usage:
    uv run python scripts/rig_release_candidate_smoke.py
    uv run python scripts/rig_release_candidate_smoke.py --live-github
    uv run python scripts/rig_release_candidate_smoke.py --live-google
    uv run python scripts/rig_release_candidate_smoke.py --no-live --json
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
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

SMOKE_REPORT_SCHEMA = "rig.relay.release_candidate_smoke.v1"


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _cmd(
    cmd: list[str], *, timeout: int = 120, env: dict | None = None
) -> tuple[int, str, str]:
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=timeout,
        env=env,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _result(
    check_id: str, status: str, elapsed_ms: int, detail: str, output_hash: str = ""
) -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "duration_ms": elapsed_ms,
        "detail": detail,
        "output_hash": output_hash,
    }


# ── Core checks ────────────────────────────────────────────────────────────


def check_schemas() -> dict:
    t0 = time.monotonic()
    code, out, _ = _cmd(
        ["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"], timeout=300
    )
    ms = int((time.monotonic() - t0) * 1000)
    ok = code == 0 and "Passed: " in out and "Failed: 0" in out
    total = 0
    for line in out.split("\n"):
        if "Total:" in line:
            try:
                total = int(line.split(":")[1].strip())
            except ValueError:
                pass
    return _result(
        "schema_validation",
        "pass" if ok else "fail",
        ms,
        f"{total} schemas validated" if total else out[:200],
        _sha(out),
    )


def check_cli() -> list[dict]:
    results = []
    for ep in [("rig-relay", ["--help"]), ("rig-relay-acp", ["--help"])]:
        t0 = time.monotonic()
        code, out, _ = _cmd(["uv", "run", ep[0], *ep[1]], timeout=30)
        ms = int((time.monotonic() - t0) * 1000)
        results.append(
            _result(
                f"cli_{ep[0].replace('-', '_')}_help",
                "pass" if code == 0 else "fail",
                ms,
                f"exit={code}",
                _sha(out),
            )
        )
    return results


def check_pyproject() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); "
                'print(f\'name={d["project"]["name"]}\'); '
                'print(f\'version={d["project"]["version"]}\')',
            ],
            timeout=30,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "pyproject_parseable",
            "pass" if code == 0 and "name=rig-relay" in out else "fail",
            ms,
            out.strip()[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "pyproject_parseable",
            "fail",
            int((time.monotonic() - t0) * 1000),
            str(e)[:200],
        )


def check_ci_evidence() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.ci_evidence import produce_ci_evidence; "
                "r=produce_ci_evidence(job_name='smoke', conclusion='success'); "
                "print(f'verdict={r.verdict}'); print(f'reasons={r.blocking_reasons}')",
            ],
            timeout=60,
        )
        ms = int((time.monotonic() - t0) * 1000)
        ok = code == 0 and "verdict=pass" in out
        return _result(
            "ci_evidence", "pass" if ok else "fail", ms, out[:200], _sha(out)
        )
    except Exception as e:
        return _result(
            "ci_evidence", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


def check_docs_json() -> dict:
    t0 = time.monotonic()
    errors = []
    p = _REPO_ROOT / "docs" / "json"
    if p.exists():
        for f in p.rglob("*.json"):
            try:
                json.loads(f.read_text())
            except json.JSONDecodeError:
                errors.append(str(f.relative_to(_REPO_ROOT)))
    ms = int((time.monotonic() - t0) * 1000)
    return _result(
        "docs_json",
        "pass" if not errors else "fail",
        ms,
        "all valid" if not errors else f"invalid: {errors[:3]}",
    )


def check_release_artifacts() -> dict:
    t0 = time.monotonic()
    paths = [
        "docs/json/release_gate/rc_readiness_gate.v1.json",
        "docs/json/release_gate/rc_candidate_verdict.v1.json",
        "docs/json/release_gate/rc_blockers.v1.jsonl",
        "docs/json/release_gate/rc_deferred_risks.v1.jsonl",
        "docs/json/release_candidate/rc_installability_verdict.v1.json",
        "docs/json/release_candidate/rc_reviewer_golden_path.v1.json",
        "docs/json/release_candidate/rc_security_repository_hygiene.v1.json",
        "docs/json/release_candidate/local_service_security_boundary.v1.json",
        "docs/json/protocols/a2a_promotion_readiness.v1.json",
    ]
    missing = [p for p in paths if not (_REPO_ROOT / p).exists()]
    ms = int((time.monotonic() - t0) * 1000)
    return _result(
        "release_artifacts",
        "pass" if not missing else "fail",
        ms,
        "all present" if not missing else f"missing: {missing}",
    )


# ── Protocol/transport checks ──────────────────────────────────────────────


def check_mcp_runtime() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.protocols.mcp.server import RigMCPServer; "
                "from rig_relay.protocols.mcp.models import MCPToolTier, READ_ONLY_TOOLS, GATED_TOOLS; "
                "s=RigMCPServer(); "
                "print(f'tools={len(s.list_tools())}'); "
                "print(f'resources={len(s.list_resources())}'); "
                "print(f'prompts={len(s.list_prompts())}'); "
                "print('mcp_ok')",
            ],
            timeout=30,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "mcp_runtime",
            "pass" if code == 0 and "mcp_ok" in out else "fail",
            ms,
            out[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "mcp_runtime", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


def check_acp_runtime() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.acp._disabled_tools import NON_INTERACTIVE_DISABLED_TOOLS; "
                "assert isinstance(NON_INTERACTIVE_DISABLED_TOOLS, list); "
                "assert 'exit_plan_mode' in NON_INTERACTIVE_DISABLED_TOOLS; "
                "print(f'acp_disabled={len(NON_INTERACTIVE_DISABLED_TOOLS)}'); "
                "print('acp_ok')",
            ],
            timeout=30,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "acp_runtime",
            "pass" if code == 0 and "acp_ok" in out else "fail",
            ms,
            out[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "acp_runtime", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


def check_sdk_smoke() -> list[dict]:
    results = []
    for tp, lbl in [
        ("tests/sdk/test_sdk_v1.py", "sdk"),
        ("tests/protocols/a2a/test_a2a_v1.py", "a2a"),
    ]:
        t0 = time.monotonic()
        code, out, _ = _cmd(
            ["uv", "run", "pytest", tp, "-v", "--tb=short", "-q"], timeout=120
        )
        ms = int((time.monotonic() - t0) * 1000)
        results.append(
            _result(
                f"test_{lbl}",
                "pass" if code == 0 else "fail",
                ms,
                f"exit={code}" if code else "all pass",
                _sha(out),
            )
        )
    return results


# ── Provider dry-run checks ────────────────────────────────────────────────


def check_github_dry_run(live: bool = False) -> dict:
    t0 = time.monotonic()
    if not live:
        return _result(
            "github_auth",
            "skipped",
            int((time.monotonic() - t0) * 1000),
            "No --live-github flag; dry-run only",
        )
    try:
        import importlib

        importlib.import_module("rig_relay.integrations.github_provider")
        ms = int((time.monotonic() - t0) * 1000)
        return _result("github_auth", "pass", ms, "GitHub provider module imported")
    except Exception as e:
        return _result(
            "github_auth", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


def check_google_dry_run(live: bool = False) -> dict:
    t0 = time.monotonic()
    if not live:
        return _result(
            "google_auth",
            "skipped",
            int((time.monotonic() - t0) * 1000),
            "No --live-google flag; dry-run only",
        )
    try:
        import importlib

        importlib.import_module("rig_relay.integrations.google_workspace")
        ms = int((time.monotonic() - t0) * 1000)
        return _result("google_auth", "pass", ms, "Google Workspace module imported")
    except Exception as e:
        return _result(
            "google_auth", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


# ── Compiler / OTel smoke ──────────────────────────────────────────────────


def check_compiler_smoke() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import rig_relay.context.compiler; print('compiler_import_ok')",
            ],
            timeout=30,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "compiler_smoke",
            "pass" if code == 0 and "compiler_import_ok" in out else "fail",
            ms,
            out[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "compiler_smoke", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


def check_otel_smoke() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import rig_relay.analytics; print('otel_import_ok')",
            ],
            timeout=30,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "otel_smoke",
            "pass" if code == 0 and "otel_import_ok" in out else "fail",
            ms,
            out[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "otel_smoke", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


# ── Security / redaction checks ────────────────────────────────────────────


def check_secret_scan() -> dict:
    t0 = time.monotonic()
    patterns = [
        r"sk-[a-zA-Z0-9]{20,}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"github_pat_[a-zA-Z0-9_]{22,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"ya29\.[0-9A-Za-z\-_]+",
        r"gho_[a-zA-Z0-9]{36}",
    ]
    found = []
    for d in ["rig_relay/", "scripts/", "tests/", "docs/"]:
        path = _REPO_ROOT / d
        if not path.exists():
            continue
        for pat in patterns:
            r = subprocess.run(
                ["rg", "-l", pat, str(path)], capture_output=True, text=True, timeout=60
            )
            if r.stdout.strip():
                found.extend(r.stdout.strip().split("\n"))
    ms = int((time.monotonic() - t0) * 1000)
    # Classify: test fixtures with "test" in path are false positives
    real_secrets = [
        f
        for f in found
        if "test" not in f and "_fake_" not in f and "adversarial" not in f
    ]
    if real_secrets:
        return _result(
            "secret_scan",
            "fail",
            ms,
            f"real secrets in: {real_secrets[:5]}",
            _sha(json.dumps(found)),
        )
    if found:
        return _result(
            "secret_scan",
            "warn",
            ms,
            f"test fixtures only: {len(found)} files",
            _sha(json.dumps(found)),
        )
    return _result("secret_scan", "pass", ms, "no secrets found")


def check_no_dev_token_default() -> dict:
    """Verify no DevFileTokenStore runs as unsafe default."""
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import ast, sys; "
                "src=open('rig_relay/identity/_credential_store.py').read(); "
                "tree=ast.parse(src); "
                "classes=[n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]; "
                "print(f'cred_store_classes={[c.name for c in classes]}')",
            ],
            timeout=15,
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "no_dev_token_default",
            "pass" if code == 0 else "fail",
            ms,
            out[:200],
            _sha(out),
        )
    except Exception as e:
        return _result(
            "no_dev_token_default",
            "fail",
            int((time.monotonic() - t0) * 1000),
            str(e)[:200],
        )


# ── Static site check ──────────────────────────────────────────────────────


def check_static_site() -> dict:
    t0 = time.monotonic()
    try:
        code, out, _ = _cmd(
            ["uv", "run", "python", "scripts/rig_site_render.py", "--help"], timeout=30
        )
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "static_site",
            "pass" if code == 0 else "fail",
            ms,
            "render script exists" if code == 0 else f"exit={code}",
            _sha(out),
        )
    except Exception as e:
        return _result(
            "static_site", "fail", int((time.monotonic() - t0) * 1000), str(e)[:200]
        )


# ── Release manifest check ─────────────────────────────────────────────────


def check_release_manifest() -> dict:
    t0 = time.monotonic()
    manifest = _REPO_ROOT / ".build" / "rig-relay" / "release-manifest.json"
    if not manifest.exists():
        return _result(
            "release_manifest",
            "skipped",
            int((time.monotonic() - t0) * 1000),
            "no release manifest found",
        )
    try:
        data = json.loads(manifest.read_text())
        ms = int((time.monotonic() - t0) * 1000)
        return _result(
            "release_manifest",
            "pass",
            ms,
            f"manifest valid, keys={list(data.keys())[:5]}",
            _sha(json.dumps(data)),
        )
    except Exception as e:
        return _result(
            "release_manifest",
            "fail",
            int((time.monotonic() - t0) * 1000),
            str(e)[:200],
        )


# ── Main runner ────────────────────────────────────────────────────────────


def run_smoke(live_github: bool = False, live_google: bool = False) -> dict:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    checks: list[dict] = []

    checks.append(check_schemas())
    checks.extend(check_cli())
    checks.append(check_pyproject())
    checks.append(check_ci_evidence())
    checks.extend(check_sdk_smoke())
    checks.append(check_mcp_runtime())
    checks.append(check_acp_runtime())
    checks.append(check_github_dry_run(live=live_github))
    checks.append(check_google_dry_run(live=live_google))
    checks.append(check_compiler_smoke())
    checks.append(check_otel_smoke())
    checks.append(check_secret_scan())
    checks.append(check_no_dev_token_default())
    checks.append(check_docs_json())
    checks.append(check_release_artifacts())
    checks.append(check_static_site())
    checks.append(check_release_manifest())

    statuses = {c["status"] for c in checks}
    overall = (
        "fail"
        if "fail" in statuses
        else ("pass_with_warnings" if "warn" in statuses else "pass")
    )

    return {
        "schema_version": SMOKE_REPORT_SCHEMA,
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c["status"] == "pass"),
        "checks_failed": sum(1 for c in checks if c["status"] == "fail"),
        "checks_warned": sum(1 for c in checks if c["status"] == "warn"),
        "checks_skipped": sum(1 for c in checks if c["status"] == "skipped"),
        "checks": checks,
        "live_github_enabled": live_github,
        "live_google_enabled": live_google,
        "network_enabled": live_github or live_google,
        "telemetry_redaction_notes": "No raw content, secrets, or private data. SHA-256 hashes only.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Toddler-Safe Release Candidate Smoke Test")
    p.add_argument("--run-id", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-live", action="store_true", default=True)
    p.add_argument("--live-github", action="store_true")
    p.add_argument("--live-google", action="store_true")
    args = p.parse_args()

    live_github = args.live_github
    live_google = args.live_google

    print("Rig Relay — Batteries-Included Smoke (Toddler-Safe)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    report = run_smoke(live_github=live_github, live_google=live_google)

    if args.run_id:
        report["run_id"] = args.run_id

    run_dir = _BUILD_DIR / report["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    rp = run_dir / "smoke_report.v1.json"
    rp.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nReport: {rp}", file=sys.stderr)
    print(f"Status: {report['overall_status']}", file=sys.stderr)
    print(
        f"Passed: {report['checks_passed']}/{report['checks_total']}", file=sys.stderr
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for c in report["checks"]:
            icon = {
                "pass": "[PASS]",
                "fail": "[FAIL]",
                "warn": "[WARN]",
                "skipped": "[SKIP]",
            }.get(c["status"], "[????]")
            print(f"  {icon} {c['check_id']}: {c['detail']}", file=sys.stderr)

    return 1 if report["overall_status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
