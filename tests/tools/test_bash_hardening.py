"""Tests for bash deterministic tool envelope hardening.

Covers the structured result model, output bounding, timeout behavior,
refusal behavior, content-light receipts, cwd handling, and environment
safety.
"""

from __future__ import annotations

import pytest

from rig_relay.core.tools.base import BaseToolState, ToolError, ToolPermission
from rig_relay.core.tools.builtins.bash import (
    Bash,
    BashArgs,
    BashReceipt,
    BashResult,
    BashToolConfig,
)
from tests.mock.utils import collect_result


@pytest.fixture
def bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = BashToolConfig()
    return Bash(config_getter=lambda: config, state=BaseToolState())


# ── Structured result model ──


@pytest.mark.asyncio
async def test_success_result_has_expected_fields(bash):
    result = await collect_result(bash.run(BashArgs(command="echo ok")))
    assert isinstance(result, BashResult)
    assert result.status == "success"
    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""
    assert result.duration_ms is not None
    assert result.duration_ms >= 0
    assert result.stdout_bytes > 0
    assert result.stderr_bytes == 0
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False
    assert result.error_kind is None
    assert result.refusal_reason is None


@pytest.mark.asyncio
async def test_failure_result_raises_tool_error(bash):
    with pytest.raises(Exception) as exc:
        await collect_result(bash.run(BashArgs(command="cat nonexistent_file_xyz")))
    assert "Command failed" in str(exc.value)
    assert "Return code: 1" in str(exc.value)


# ── Timeout behavior ──


@pytest.mark.asyncio
async def test_timeout_returns_structured_timed_out_result(bash):
    result = await collect_result(bash.run(BashArgs(command="sleep 2", timeout=1)))
    assert result.status == "timed_out"
    assert result.error_kind == "timeout"
    assert result.returncode == -1
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.duration_ms is not None and result.duration_ms > 0
    assert result.refusal_reason is not None
    assert "timed out" in result.refusal_reason


# ── Output bounding / truncation ──


@pytest.mark.asyncio
async def test_stdout_truncation_marks_truncated_flag(bash):
    config = BashToolConfig(max_output_bytes=5)
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(tool.run(BashArgs(command="printf 'abcdefghij'")))
    assert result.stdout == "abcde"
    assert result.stdout_truncated is True
    assert result.stdout_bytes >= 10


@pytest.mark.asyncio
async def test_stderr_truncation_marks_truncated_flag(bash):
    config = BashToolConfig(max_output_bytes=5, restrict_raw_shell=False)
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(tool.run(BashArgs(command="printf 'abcdefghij' >&2")))
    assert result.stderr == "abcde"
    assert result.stderr_truncated is True
    assert result.stderr_bytes >= 10


@pytest.mark.asyncio
async def test_per_stream_byte_cap_overrides_config(bash):
    config = BashToolConfig(max_output_bytes=100)
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(BashArgs(command="printf 'hello world'", max_stdout_bytes=5))
    )
    assert result.stdout == "hello"
    assert result.stdout_truncated is True
    assert result.stdout_bytes >= 11


@pytest.mark.asyncio
async def test_small_output_not_truncated(bash):
    result = await collect_result(bash.run(BashArgs(command="echo hi")))
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False


# ── Content-light receipt ──


@pytest.mark.asyncio
async def test_receipt_has_no_raw_output(bash):
    result = await collect_result(bash.run(BashArgs(command="echo secret_data")))
    receipt = bash.build_receipt(result)
    assert isinstance(receipt, BashReceipt)
    # No raw stdout/stderr in receipt
    assert not hasattr(receipt, "stdout")
    assert not hasattr(receipt, "stderr")
    # Has metadata only
    assert receipt.command == "echo secret_data"
    assert receipt.status == "success"
    assert receipt.exit_code == 0
    assert receipt.duration_ms is not None
    assert receipt.stdout_bytes > 0
    assert receipt.stdout_truncated is False
    assert receipt.stdout_sha256 is not None
    assert receipt.stderr_sha256 is None


@pytest.mark.asyncio
async def test_receipt_for_timed_out_command(bash):
    result = await collect_result(bash.run(BashArgs(command="sleep 2", timeout=1)))
    receipt = bash.build_receipt(result)
    assert receipt.status == "timed_out"
    assert receipt.exit_code == -1
    assert receipt.stdout_bytes == 0
    assert receipt.stderr_bytes == 0
    assert receipt.stdout_sha256 is None
    assert receipt.error_kind == "timeout"


@pytest.mark.asyncio
async def test_receipt_sha256_changes_with_output(bash):
    result_a = await collect_result(bash.run(BashArgs(command="echo alpha")))
    result_b = await collect_result(bash.run(BashArgs(command="echo beta")))
    receipt_a = bash.build_receipt(result_a)
    receipt_b = bash.build_receipt(result_b)
    assert receipt_a.stdout_sha256 != receipt_b.stdout_sha256


# ── cwd handling ──


@pytest.mark.asyncio
async def test_explicit_cwd_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    config = BashToolConfig()
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(tool.run(BashArgs(command="pwd", cwd=str(subdir))))
    assert result.stdout.strip() == str(subdir)


@pytest.mark.asyncio
async def test_cwd_defaults_to_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = BashToolConfig()
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(tool.run(BashArgs(command="pwd")))
    assert result.stdout.strip() == str(tmp_path)


# ── Environment safety ──


@pytest.mark.asyncio
async def test_environment_has_noninteractive_flags(bash):
    result = await collect_result(
        bash.run(BashArgs(command="echo $CI $NONINTERACTIVE $NO_TTY"))
    )
    parts = result.stdout.strip().split()
    assert "true" in parts
    assert "1" in parts


@pytest.mark.asyncio
async def test_env_does_not_leak_into_receipt(bash):
    result = await collect_result(bash.run(BashArgs(command="env")))
    receipt = bash.build_receipt(result)
    # Receipt has no raw stdout
    assert receipt.stdout_bytes > 0
    assert receipt.stdout_sha256 is not None
    # The raw env output is only in the result, not the receipt
    assert not hasattr(receipt, "stdout")


# ── Refusal behavior ──


def test_denylist_refuses_matched_command():
    """Denylist match in resolve_permission returns ToolPermission.NEVER."""
    config = BashToolConfig(denylist=["rm -rf"])
    tool = Bash(config_getter=lambda: config, state=BaseToolState())
    permission = tool.resolve_permission(BashArgs(command="rm -rf /tmp"))
    assert permission is not None
    assert permission.permission is ToolPermission.NEVER
    assert permission.reason is not None


# ── Duration tracking ──


@pytest.mark.asyncio
async def test_duration_is_measured_in_milliseconds(bash):
    result = await collect_result(bash.run(BashArgs(command="echo fast")))
    assert result.duration_ms is not None
    assert result.duration_ms > 0
    assert result.duration_ms < 10_000  # sanity bound


# ── Status field values ──


@pytest.mark.asyncio
async def test_success_status_is_success(bash):
    result = await collect_result(bash.run(BashArgs(command="true")))
    assert result.status == "success"


@pytest.mark.asyncio
async def test_failure_status_via_nonzero_exit(bash):
    with pytest.raises(ToolError):
        await collect_result(bash.run(BashArgs(command="false")))


# ── BashResult backwards compatibility ──


def test_bash_result_defaults():
    """BashResult can be constructed with only the original fields."""
    result = BashResult(command="echo hi", stdout="hi\n", stderr="", returncode=0)
    assert result.status == "success"
    assert result.duration_ms is None
    assert result.stdout_bytes == 0
    assert result.stdout_truncated is False
    assert result.error_kind is None
    assert result.refusal_reason is None


# ── BashReceipt construction ──


def test_bash_receipt_minimal():
    receipt = BashReceipt(command="echo hi", status="success", exit_code=0)
    assert receipt.stdout_bytes == 0
    assert receipt.stdout_sha256 is None


def test_bash_receipt_with_truncation():
    receipt = BashReceipt(
        command="big output",
        status="success",
        exit_code=0,
        stdout_bytes=5000,
        stdout_truncated=True,
    )
    assert receipt.stdout_bytes == 5000
    assert receipt.stdout_truncated is True
