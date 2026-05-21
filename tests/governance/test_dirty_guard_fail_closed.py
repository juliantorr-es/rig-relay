from __future__ import annotations

import logging
from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.integration]

from rig_relay.core.guard import (
    DirtyFileGuard,
    DirtyGuardFailurePolicy,
    GuardCaptureReason,
    reset_guard,
)


@pytest.fixture(autouse=True)
def _reset_guard():
    reset_guard()
    yield
    reset_guard()


def _init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _git_add_commit(path: Path, message: str = "init") -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=path, capture_output=True, check=True
    )


# ── capture failure fields ────────────────────────────────────────


def test_capture_failure_sets_capture_failed_true_and_captured_false(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard.capture()

    assert guard._captured and not guard._capture_failed
    assert guard.capture_succeeded
    assert not guard.capture_failed


def test_capture_failure_sets_baseline_id_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard.capture()

    assert guard.baseline_id
    assert guard._capture_failed is False

    assert guard.capture_succeeded


def test_capture_failure_when_git_absent(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    caplog.set_level(logging.WARNING)

    guard = DirtyFileGuard()
    guard.capture()

    assert guard._capture_failed
    assert not guard._captured
    assert guard.baseline_id == ""
    assert guard._capture_error is not None
    assert not guard.capture_succeeded
    assert guard.capture_failed

    assert any("git status failed" in r.message for r in caplog.records)


# ── write validation refuses when capture failed ──────────────────


def test_write_file_refused_when_capture_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard._capture_failed = True
    guard._capture_error = "simulated git failure"

    result = guard.check_write_file("any_file.py")
    assert not result.allowed
    assert result.reason == "dirty_guard_capture_failed"
    assert result.detail is not None
    assert "simulated git failure" in result.detail


def test_search_replace_refused_when_capture_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard._capture_failed = True
    guard._capture_error = "simulated git failure"

    result = guard.check_search_replace("any_file.py")
    assert not result.allowed
    assert result.reason == "dirty_guard_capture_failed"


def test_write_file_refused_regardless_of_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard.failure_policy = DirtyGuardFailurePolicy.WARN_ALLOW
    guard._capture_failed = True
    guard._capture_error = "simulated git failure"

    result = guard.check_write_file("any_file.py")
    assert not result.allowed
    assert result.reason == "dirty_guard_capture_failed"


# ── snapshot includes capture_failed ──────────────────────────────


def test_report_includes_capture_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard._capture_failed = True
    guard._capture_error = "simulated git failure"

    report = guard.report()
    assert report["capture_failed"] is True
    assert report["capture_succeeded"] is False
    assert report["capture_error"] == "simulated git failure"


# ── trace event emitted on capture failure ────────────────────────


def test_capture_failure_emits_trace_event(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    caplog.set_level(logging.ERROR)

    guard = DirtyFileGuard()
    guard.capture()

    assert any("dirty_guard.capture_failed" in r.message for r in caplog.records)
    assert any("severity=critical" in r.message for r in caplog.records)


# ── init blocks when guard capture failed ─────────────────────────


def test_init_blocks_mutation_tools_when_capture_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard.failure_policy = DirtyGuardFailurePolicy.WARN_ALLOW
    guard._capture_failed = True
    guard._capture_error = "simulated failure"

    assert guard.failure_policy == DirtyGuardFailurePolicy.WARN_ALLOW

    guard.failure_policy = DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION

    assert guard.failure_policy == DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION

    result = guard.check_write_file("any_file.py")
    assert not result.allowed
    assert result.reason == "dirty_guard_capture_failed"


# ── read-only tools still work when guard capture failed ──────────


def test_is_protected_returns_false_when_capture_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "clean.py").write_text("x = 1\n")
    _init_git_repo(tmp_path)
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    guard._capture_failed = True
    guard._capture_error = "simulated git failure"

    assert not guard.is_protected("clean.py")


def test_is_destructive_git_command_still_works_when_capture_failed(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )

    guard = DirtyFileGuard()
    guard._capture_failed = True
    guard._capture_error = "simulated failure"

    blocked, _ = guard.is_destructive_git_command("git restore some_file.py")
    assert blocked

    blocked, _ = guard.is_destructive_git_command("git status")
    assert not blocked


# ── git status success still works normally ───────────────────────


def test_capture_success_works_normally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("x = 1\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()

    assert guard._captured
    assert not guard._capture_failed
    assert guard.capture_succeeded
    assert not guard.capture_failed
    assert guard.baseline_id

    assert guard.is_protected("dirty.py")
    assert not guard.is_protected("clean.py")

    result = guard.check_write_file("clean.py")
    assert result.allowed


def test_subagent_blocks_mutation_on_capture_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "some.py").write_text("content\n")
    _init_git_repo(tmp_path)
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    guard.capture(
        reason=GuardCaptureReason.FORK_CHILD,
        failure_policy=DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION,
    )

    assert guard.capture_succeeded

    guard._capture_failed = True
    guard._capture_error = "simulated"

    result = guard.check_write_file("some.py")
    assert not result.allowed
    assert result.reason == "dirty_guard_capture_failed"
