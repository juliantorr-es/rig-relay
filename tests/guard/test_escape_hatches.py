"""Escape-hatch tests for the Git destructive command guard.

Uses real temp git repos to prove that git options (-c, -C, --git-dir, etc.)
cannot bypass destructive command blocking, and that git commit --amend and
git push --force/--force-with-lease are in the blocked set per AGENTS.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.integration]

from rig_relay.core.guard import DirtyFileGuard, reset_guard


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


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


# ── escape hatch: git -c option bypass ──────────────────────────


def test_git_c_bypass_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, reason = guard.is_destructive_git_command(
        "git -c user.name=attacker reset --hard HEAD"
    )
    assert blocked, "git -c option bypass must be blocked"
    assert reason is not None
    assert "git reset" in reason


def test_git_c_bypass_blocked_multiple_opts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()

    blocked, _ = guard.is_destructive_git_command("git -c foo=bar -c baz=qux clean -fd")
    assert blocked, "Multiple -c options must not bypass git clean"

    blocked, _ = guard.is_destructive_git_command("git --git-dir=/tmp/.git stash")
    assert blocked, "--git-dir= must not bypass git stash"

    blocked, _ = guard.is_destructive_git_command(
        "git --git-dir /tmp/.git restore some_file.py"
    )
    assert blocked, "--git-dir must not bypass git restore"

    blocked, _ = guard.is_destructive_git_command("git -C /tmp checkout -- file.py")
    assert blocked, "-C must not bypass git checkout"

    blocked, _ = guard.is_destructive_git_command(
        "git --no-optional-locks reset HEAD~1"
    )
    assert blocked, "--no-optional-locks must not bypass git reset"

    blocked, _ = guard.is_destructive_git_command("git --no-pager clean -fd")
    assert blocked, "--no-pager must not bypass git clean"


# ── escape hatch: git commit --amend ────────────────────────────


def test_git_commit_amend_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, reason = guard.is_destructive_git_command("git commit --amend")
    assert blocked, "git commit --amend must be in the blocked set"
    assert reason is not None
    assert "git commit --amend" in reason


def test_git_commit_amend_with_message_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git commit --amend -m 'updated'")
    assert blocked, "git commit --amend -m must be blocked"


def test_git_commit_amend_no_edit_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git commit --amend --no-edit")
    assert blocked, "git commit --amend --no-edit must be blocked"


# ── escape hatch: git push --force / --force-with-lease ─────────


def test_git_push_force_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, reason = guard.is_destructive_git_command("git push --force")
    assert blocked, "git push --force must be in the blocked set"
    assert reason is not None
    assert "git push --force" in reason


def test_git_push_force_origin_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git push --force origin main")
    assert blocked, "git push --force origin main must be blocked"


def test_git_push_force_with_lease_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, reason = guard.is_destructive_git_command("git push --force-with-lease")
    assert blocked, "git push --force-with-lease must be in the blocked set"
    assert reason is not None
    assert "git push --force-with-lease" in reason


def test_git_push_force_with_lease_refspec_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command(
        "git push --force-with-lease=refs/heads/main"
    )
    assert blocked, "--force-with-lease=refname variant must be blocked"


def test_git_push_force_with_lease_origin_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command(
        "git push --force-with-lease origin main"
    )
    assert blocked, "git push --force-with-lease origin main must be blocked"


# ── safe commands still work ────────────────────────────────────


def test_safe_commands_still_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()

    safe_commands = [
        "git status",
        "git diff",
        "git log --oneline",
        "git branch",
        "git add file.py",
        "git commit -m 'msg'",
        "git push",
        "git fetch",
        "git show HEAD",
    ]

    for cmd in safe_commands:
        blocked, reason = guard.is_destructive_git_command(cmd)
        assert not blocked, f"Safe command '{cmd}' should not be blocked"


def test_safe_commands_with_global_options_still_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()

    safe_with_opts = [
        "git -c user.name=test status",
        "git --no-optional-locks diff",
        "git --no-pager log --oneline",
        "git -C . branch",
        "git -c foo=bar add file.py",
        "git --git-dir=.git show HEAD",
    ]

    for cmd in safe_with_opts:
        blocked, reason = guard.is_destructive_git_command(cmd)
        assert not blocked, (
            f"Safe command with global options '{cmd}' should not be blocked; reason: {reason}"
        )


# ── dirty file preservation still works ─────────────────────────


def test_dirty_file_preservation_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "dirty.py").write_text("modified\n")

    guard = DirtyFileGuard()
    guard.capture()

    assert guard.is_protected("dirty.py"), "Modified file must be protected"

    result = guard.check_write_file("dirty.py")
    assert not result.allowed
    assert result.reason == "protected_file_no_overwrite_flag"

    current_hash = _sha256(tmp_path / "dirty.py")
    result = guard.check_write_file(
        "dirty.py", allow_overwrite_protected=True, expected_before_sha256=current_hash
    )
    assert result.allowed
    assert result.reason == "protected_file_hash_matched"

    result = guard.check_search_replace("dirty.py", expected_before_sha256=current_hash)
    assert result.allowed


def test_dirty_file_marking_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()
    guard.mark_touched("dirty.py")
    guard.record_refusal("dirty.py", "test_refusal")

    report = guard.report()
    assert "dirty.py" in report["files_touched_by_mission"]
    assert len(report["refused_write_attempts"]) == 1
    assert report["refused_write_attempts"][0]["path"] == "dirty.py"


# ── edge cases ──────────────────────────────────────────────────


def test_non_git_commands_not_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("echo hello")
    assert not blocked
    blocked, _ = guard.is_destructive_git_command("ls -la")
    assert not blocked


def test_git_with_no_subcommand_not_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git")
    assert not blocked
    blocked, _ = guard.is_destructive_git_command("git --version")
    assert not blocked
    blocked, _ = guard.is_destructive_git_command("git --help")
    assert not blocked


def test_whitespace_handling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("  git reset --hard HEAD  ")
    assert blocked, "Leading/trailing whitespace must not bypass check"
