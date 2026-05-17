from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.release_gate.models import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Finding,
    GatePolicy,
)


@pytest.fixture
def tmp_repo_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def base_ctx(tmp_repo_root: Path, output_dir: Path) -> CheckContext:
    return CheckContext(
        repo_root=tmp_repo_root,
        output_dir=output_dir,
        head_sha="abc1234",
        branch="main",
    )


@pytest.fixture
def default_policy() -> GatePolicy:
    return GatePolicy()


@pytest.fixture
def strict_policy() -> GatePolicy:
    return GatePolicy(
        required_checks=["required.check", "another.required"],
        strict_warnings_exit_nonzero=True,
    )


def make_fake_check(
    check_id: str,
    status: CheckStatus = CheckStatus.PASS,
    severity: CheckSeverity = CheckSeverity.MEDIUM,
    summary: str = "",
    findings: list[Finding] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        title=f"Fake check: {check_id}",
        status=status,
        severity=severity,
        summary=summary or f"Result: {status}",
        findings=findings or [],
    )


def make_finding(
    finding_id: str,
    severity: CheckSeverity = CheckSeverity.MEDIUM,
    check_id: str = "test.check",
    category: str = "test",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        category=category,
        description=f"Finding {finding_id}",
        severity=severity,
        source=f"{check_id}.py:1",
        recommendation="Fix it.",
    )


def make_check_fn(result: CheckResult):
    def _fn(ctx: CheckContext) -> CheckResult:
        return result

    return _fn
