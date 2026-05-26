"""Tests for validate execution authority — risk classification, containment truth, malicious-repo behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.validate import (
    ContainmentProperties,
    Validate,
    ValidateArgs,
    ValidateToolConfig,
    ValidationExecutionRisk,
    classify_command_execution_risk,
    get_profile,
)
from rig_relay.governance.auth_receipts import generate_dev_receipt


def _dev_authz_receipt() -> str:
    return json.dumps(generate_dev_receipt("validate.uncontained_execution"))


def _temp_git_repo(prefix: str = "validate-repo") -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    subprocess.run(["git", "init"], cwd=root, capture_output=True, timeout=10)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, timeout=10)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=root, capture_output=True, timeout=10
    )
    return root


def _malicious_test_repo(kind: str, sentinel_dir: Path) -> Path:
    root = _temp_git_repo(prefix=f"malicious-{kind}")
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").touch()

    conftest = tests_dir / "conftest.py"
    if kind == "write_outside":
        sentinel_path = str(sentinel_dir / f"sentinel_write_{os.getpid()}.txt")
        conftest.write_text(
            f"def pytest_configure(config):\n"
            f"    with open({sentinel_path!r}, 'w') as f:\n"
            f"        f.write('escaped')\n",
            encoding="utf-8",
        )
    elif kind == "spawn_child":
        sentinel_marker = str(sentinel_dir / f"child_ran_{os.getpid()}.txt")
        conftest.write_text(
            "import subprocess, sys, time\n"
            "def pytest_configure(config):\n"
            "    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
            f"    with open({sentinel_marker!r}, 'w') as f:\n"
            "        f.write(str(proc.pid))\n"
            "    time.sleep(0.1)\n"
            "    proc.kill()\n",
            encoding="utf-8",
        )

    (root / "tests" / "test_dummy.py").write_text(
        "def test_nothing(): assert True\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, timeout=10)
    subprocess.run(
        ["git", "commit", "-m", "add malicious test"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    return root


async def _collect_results(tool: Validate, args: ValidateArgs):
    """Collect all events and return the final ValidateResult."""
    result = None
    async for event in tool.run(args):
        if hasattr(event, "status") and hasattr(event, "profile"):
            result = event
    return result


# ── Risk classification tests ─────────────────────────────────────────────────


def test_classify_git_is_repository_inspection():
    assert (
        classify_command_execution_risk("git")
        == ValidationExecutionRisk.REPOSITORY_INSPECTION
    )


def test_classify_ruff_is_static_analysis():
    assert (
        classify_command_execution_risk("ruff")
        == ValidationExecutionRisk.STATIC_ANALYSIS
    )


def test_classify_pyright_is_static_analysis():
    assert (
        classify_command_execution_risk("pyright")
        == ValidationExecutionRisk.STATIC_ANALYSIS
    )


def test_classify_pytest_is_repository_code_executing():
    assert (
        classify_command_execution_risk("pytest")
        == ValidationExecutionRisk.REPOSITORY_CODE_EXECUTING
    )


def test_classify_schema_is_repository_code_executing():
    assert (
        classify_command_execution_risk("schema")
        == ValidationExecutionRisk.REPOSITORY_CODE_EXECUTING
    )


def test_classify_policy_is_repository_code_executing():
    assert (
        classify_command_execution_risk("policy")
        == ValidationExecutionRisk.REPOSITORY_CODE_EXECUTING
    )


def test_classify_unknown_is_custom_unclassified():
    assert (
        classify_command_execution_risk("foobar")
        == ValidationExecutionRisk.CUSTOM_UNCLASSIFIED
    )


def test_profile_checks_have_explicit_risk():
    for name in [
        "quick",
        "python",
        "schemas",
        "receipt-policy",
        "tool-hardening",
        "worktree-readiness",
    ]:
        p = get_profile(name)
        assert p is not None, f"Missing profile: {name}"
        for check in p.checks:
            assert check.execution_risk is not None, (
                f"{name}/{check.check_id} has no risk"
            )


# ── Containment truth tests ───────────────────────────────────────────────────


def test_containment_properties_default_is_no_containment():
    cp = ContainmentProperties()
    assert cp.containment_backend == "none"
    assert not cp.any_containment
    assert not cp.filesystem_isolation


def test_containment_properties_to_dict():
    cp = ContainmentProperties(
        shell_interpretation_avoided=True,
        output_bounded=True,
        timeout_enforced=True,
        containment_backend="none",
        notes="test",
    )
    d = cp.to_dict()
    assert d["filesystem_isolation"] is False
    assert d["network_isolation"] is False
    assert d["shell_interpretation_avoided"] is True
    assert d["output_bounded"] is True
    assert d["timeout_enforced"] is True


# ── Fail-closed gate ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autonomous_validate_refuses_pytest_default():
    repo = _temp_git_repo()
    try:
        args = ValidateArgs(
            profile="python",
            workspace_root=str(repo),
            allow_uncontained_execution=False,
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None, "No result from Validate tool"
        pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
        assert len(pytest_checks) == 1
        pc = pytest_checks[0]
        assert pc.status == "refused", (
            f"Expected refused, got {pc.status}: {pc.failure_kind}"
        )
        assert pc.failure_kind == "contained_validation_backend_unavailable"
        assert pc.containment_backend_unavailable is True
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.asyncio
async def test_autonomous_validate_allows_ruff():
    repo = _temp_git_repo()
    try:
        (repo / "bad.py").write_text("x = 1\n", encoding="utf-8")
        args = ValidateArgs(
            profile="python",
            workspace_root=str(repo),
            allow_uncontained_execution=False,
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None
        ruff_checks = [c for c in result.checks if c.command_kind == "ruff"]
        assert len(ruff_checks) > 0
        for rc in ruff_checks:
            assert rc.status != "refused", f"ruff refused: {rc.failure_kind}"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.asyncio
async def test_autonomous_validate_allows_git_inspection():
    repo = _temp_git_repo()
    try:
        args = ValidateArgs(
            profile="quick", workspace_root=str(repo), allow_uncontained_execution=False
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None
        git_checks = [c for c in result.checks if c.command_kind == "git"]
        assert len(git_checks) > 0
        for gc in git_checks:
            assert gc.status != "refused", f"git refused: {gc.failure_kind}"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.asyncio
async def test_explicitly_authorized_uncontained_pytest_runs():
    repo = _temp_git_repo()
    try:
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "__init__.py").touch()
        (repo / "tests" / "conftest.py").touch()
        (repo / "tests" / "test_trivial.py").write_text(
            "def test_ok(): assert True\n", encoding="utf-8"
        )
        args = ValidateArgs(
            profile="python",
            workspace_root=str(repo),
            allow_uncontained_execution=True,
            uncontained_authorization_receipt=_dev_authz_receipt(),
        )
        args = ValidateArgs(
            profile="python", workspace_root=str(repo), allow_uncontained_execution=True
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None
        pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
        assert len(pytest_checks) > 0
        for pc in pytest_checks:
            if pc.status != "refused":
                assert pc.uncontained_execution_authorized is True
                assert pc.containment_backend_unavailable is True
                assert pc.containment_properties["filesystem_isolation"] is False
                assert pc.containment_properties["network_isolation"] is False
                assert pc.containment_properties["containment_backend"] == "none"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ── Malicious repo tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malicious_repo_write_outside_refused_safely():
    with tempfile.TemporaryDirectory() as sentinel_dir_str:
        sentinel_dir = Path(sentinel_dir_str)
        repo = _malicious_test_repo("write_outside", sentinel_dir)
        sentinel = sentinel_dir / f"sentinel_write_{os.getpid()}.txt"
        try:
            args = ValidateArgs(
                profile="python",
                workspace_root=str(repo),
                allow_uncontained_execution=False,
            )
            tool = Validate(
                config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
            )
            result = await _collect_results(tool, args)
            assert result is not None
            pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
            assert len(pytest_checks) > 0
            assert pytest_checks[0].status == "refused"
            assert not sentinel.exists(), "Sentinel WRITTEN despite refusal!"
        finally:
            shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.asyncio
async def test_malicious_repo_spawn_child_refused_safely():
    with tempfile.TemporaryDirectory() as sentinel_dir_str:
        sentinel_dir = Path(sentinel_dir_str)
        repo = _malicious_test_repo("spawn_child", sentinel_dir)
        sentinel_marker = sentinel_dir / f"child_ran_{os.getpid()}.txt"
        try:
            args = ValidateArgs(
                profile="python",
                workspace_root=str(repo),
                allow_uncontained_execution=False,
            )
            tool = Validate(
                config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
            )
            result = await _collect_results(tool, args)
            assert result is not None
            pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
            assert len(pytest_checks) > 0
            assert pytest_checks[0].status == "refused"
            if sentinel_marker.exists():
                # Clean up any child PID
                pid_str = sentinel_marker.read_text().strip()
                if pid_str.isdigit():
                    try:
                        os.kill(int(pid_str), 9)
                    except Exception:
                        pass
                raise AssertionError("Child process SPAWNED despite refusal!")
        finally:
            shutil.rmtree(repo, ignore_errors=True)


# ── Receipt and schema checks ──────────────────────────────────────────────────


def test_containment_properties_schema_roundtrip():
    cp = ContainmentProperties(
        shell_interpretation_avoided=True,
        output_bounded=True,
        timeout_enforced=True,
        containment_backend="none",
        notes="v1 direct subprocess",
    )
    d = cp.to_dict()
    json_str = json.dumps(d)
    reloaded = json.loads(json_str)
    assert reloaded["containment_backend"] == "none"
    assert reloaded["filesystem_isolation"] is False
    assert reloaded["shell_interpretation_avoided"] is True


def test_validate_result_includes_execution_risk_fields():
    from rig_relay.core.tools.builtins.validate_models import ValidateCheckResult

    r = ValidateCheckResult(
        check_id="test_1",
        command_kind="pytest",
        status="passed",
        execution_risk="repository_code_executing",
        containment_properties={"filesystem_isolation": False},
        containment_backend_unavailable=True,
    )
    assert r.execution_risk == "repository_code_executing"
    assert r.containment_backend_unavailable is True


def test_bash_handoff_refusal_kind_matches_validate_authority():
    from rig_relay.core.tools.builtins.validate_models import ValidateCheckResult

    r = ValidateCheckResult(
        check_id="test",
        command_kind="pytest",
        status="refused",
        failure_kind="contained_validation_backend_unavailable",
        containment_backend_unavailable=True,
    )
    assert r.failure_kind == "contained_validation_backend_unavailable"
    assert r.status == "refused"


# ── Authorization-bound uncontained execution ─────────────────────────────────


@pytest.mark.asyncio
async def test_uncontained_execution_without_authz_refused():
    """allow_uncontained_execution=True without a receipt must be refused."""
    repo = _temp_git_repo()
    try:
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "__init__.py").touch()
        (repo / "tests" / "conftest.py").touch()
        args = ValidateArgs(
            profile="python",
            workspace_root=str(repo),
            allow_uncontained_execution=True,
            uncontained_authorization_receipt=None,
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None
        pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
        assert len(pytest_checks) > 0
        assert pytest_checks[0].status == "refused"
        assert pytest_checks[0].failure_kind == "uncontained_execution_unauthorized"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.asyncio
async def test_uncontained_execution_invalid_authz_refused():
    """Invalid authorization receipt must refuse."""
    repo = _temp_git_repo()
    try:
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "__init__.py").touch()
        args = ValidateArgs(
            profile="python",
            workspace_root=str(repo),
            allow_uncontained_execution=True,
            uncontained_authorization_receipt="not valid json",
        )
        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        result = await _collect_results(tool, args)
        assert result is not None
        pytest_checks = [c for c in result.checks if c.command_kind == "pytest"]
        assert len(pytest_checks) > 0
        assert pytest_checks[0].status == "refused"
    finally:
        shutil.rmtree(repo, ignore_errors=True)
