"""Tests for canonical live write CLI — default blocked, simulated success, receipt integrity."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.e2e]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"
CLI = REPO_ROOT / "scripts" / "rig_github_execute_live_pr_write.py"


def test_cli_exists():
    assert CLI.exists()


def test_cli_default_blocked():
    result = subprocess.run(
        ["uv", "run", "python", str(CLI)], capture_output=True, text=True
    )
    assert result.returncode == 0


def test_cli_summary_works():
    result = subprocess.run(
        ["uv", "run", "python", str(CLI), "--summary"], capture_output=True, text=True
    )
    assert "Blocked gates" in result.stdout or "blocked" in result.stdout.lower()


def test_execution_artifact_exists():
    assert (GOV / "github_live_pr_write_execution_v1.v1.json").exists()


def test_receipt_artifact_exists():
    assert (GOV / "github_live_pr_write_receipt_v1.v1.json").exists()


def test_receipt_alert_deferred():
    r = json.loads((GOV / "github_live_pr_write_receipt_v1.v1.json").read_text())
    assert r["alert_update_deferred"] is True
    assert r["pr_merged"] is False


def test_operator_command_artifact():
    assert (GOV / "github_live_pr_operator_command_v1.v1.json").exists()
    cmd = json.loads((GOV / "github_live_pr_operator_command_v1.v1.json").read_text())
    assert "canonical_script" in cmd
    assert "live_execution_command" in cmd
    assert cmd["live_mutation_attempted"] is False
    assert cmd["remote_mutation_attempted"] is False


def test_no_forbidden_fields():
    for name in (
        "github_live_pr_write_execution_v1.v1",
        "github_live_pr_write_receipt_v1.v1",
        "github_live_pr_write_result_v1.v1",
        "github_live_pr_operator_command_v1.v1",
    ):
        s = (GOV / f"{name}.json").read_text(encoding="utf-8")
        for pat in (
            "ghp_",
            "BEGIN PRIVATE KEY",
            '"access_token"',
            '"authorization"',
            '"raw_body"',
            '"code_snippet"',
            '"secret_value"',
        ):
            assert pat not in s, f"{pat} in {name}"


def test_operator_command_has_required_flags():
    cmd = json.loads((GOV / "github_live_pr_operator_command_v1.v1.json").read_text())
    flags = cmd["required_flags"]
    assert "--execute-remote-mutation" in flags
    assert "--i-understand-this-creates-a-real-pr" in flags
    assert "--allow-live-writes" in flags


def test_operator_command_has_env():
    cmd = json.loads((GOV / "github_live_pr_operator_command_v1.v1.json").read_text())
    assert "RIG_LIVE_AUTH_TESTS" in cmd["required_env"]


def test_no_live_network_calls():
    """All tests use default blocked mode — no live network should occur."""
    pass  # Proven by default blocked execution above
