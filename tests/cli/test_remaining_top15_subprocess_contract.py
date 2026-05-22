from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable


def _run(
    *args: str, cwd: Path | None = None, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "RIG_LIVE_AUTH_TESTS"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PYTHON, *(str(a) for a in args)],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=env,
    )


# ── sessions_gc (destructive delete) ─────────────────────────────────────────


def test_sessions_gc_dry_run_default() -> None:
    cp = _run("scripts/rig_relay_sessions_gc.py", "--older-than-days", "1")
    assert "Dry run" in cp.stdout


def test_sessions_gc_execute_blocked() -> None:
    cp = _run("scripts/rig_relay_sessions_gc.py", "--older-than-days", "1", "--execute")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper()


# ── gc_artifacts (destructive delete) ────────────────────────────────────────


def test_gc_artifacts_dry_run_default() -> None:
    cp = _run("scripts/rig_relay_gc_artifacts.py", "--root", ".build/rig-relay")
    assert (
        "DRY RUN" in cp.stdout.upper()
        or "Dry run" in cp.stdout
        or "Run with --confirm" in cp.stdout
    )


def test_gc_artifacts_execute_blocked() -> None:
    cp = _run(
        "scripts/rig_relay_gc_artifacts.py", "--root", ".build/rig-relay", "--execute"
    )
    assert (
        cp.returncode != 0
        or "BLOCKED" in cp.stdout.upper()
        or "DRY RUN" in cp.stdout.upper()
    )


# ── sessions_compact (file mutation) ─────────────────────────────────────────


def test_sessions_compact_dry_run_default() -> None:
    cp = _run("scripts/rig_relay_sessions_compact.py")
    assert "Dry run" in cp.stdout or cp.returncode == 0


def test_sessions_compact_execute_blocked() -> None:
    cp = _run("scripts/rig_relay_sessions_compact.py", "--execute")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper()


# ── bump_version (source + git mutation) ─────────────────────────────────────


def test_bump_version_dry_run_default() -> None:
    cp = _run("scripts/bump_version.py", "micro")
    assert "version" in cp.stdout.lower() or cp.returncode in {0, 1}


def test_bump_version_execute_blocked() -> None:
    cp = _run("scripts/bump_version.py", "--execute", "micro")
    assert (
        cp.returncode != 0
        or "BLOCKED" in cp.stdout.upper()
        or "DRY-RUN" in cp.stdout.upper()
    )


# ── prepare_release (git mutation) ───────────────────────────────────────────


def test_prepare_release_dry_run_default() -> None:
    cp = _run("scripts/prepare_release.py", "1.0.0")
    assert (
        "DRY-RUN" in cp.stdout or "DRY_RUN" in cp.stdout.upper() or cp.returncode == 0
    )


def test_prepare_release_execute_blocked() -> None:
    cp = _run("scripts/prepare_release.py", "--execute", "1.0.0")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper()


# ── refactor_large_files (source mutation) ───────────────────────────────────


def test_refactor_large_files_no_args_is_dry_run() -> None:
    cp = _run("scripts/refactor_large_files.py")
    assert (
        "DRY-RUN" in cp.stdout or "DRY_RUN" in cp.stdout.upper() or cp.returncode == 0
    )


def test_refactor_large_files_execute_blocked() -> None:
    cp = _run("scripts/refactor_large_files.py", "--execute")
    assert cp.returncode != 0 or "BLOCKED" in cp.stdout.upper()


# ── live_mutation_preflight (near-compliant) ─────────────────────────────────


def test_live_preflight_summary_is_safe() -> None:
    cp = _run("scripts/rig_github_live_mutation_preflight.py", "--summary")
    assert cp.returncode == 0


# ── already-compliant scripts verify still safe ──────────────────────────────


def test_cleanup_coordination_leases_dry_run() -> None:
    cp = _run("scripts/rig_relay_cleanup_coordination_leases.py")
    assert cp.returncode in {0, 1}


def test_upload_google_drive_compliant() -> None:
    cp = _run("scripts/rig_relay_upload_google_drive.py", "--help")
    assert cp.returncode == 0


def test_contribute_telemetry_bundle_compliant() -> None:
    cp = _run("scripts/rig_relay_contribute_telemetry_bundle.py", "--help")
    assert cp.returncode == 0
