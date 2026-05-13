from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from vibe.core.guard import DirtyFileGuard, get_guard, reset_guard


@pytest.fixture(autouse=True)
def _reset_guard():
    reset_guard()
    yield
    reset_guard()


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True,
    )


def _git_add_commit(path: Path, message: str = "init") -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True, check=True)


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


# ── guard capture tests ──────────────────────────────────────────


def test_guard_captures_clean_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("x = 1\n")
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    guard.capture()

    assert not guard.dirty_snapshots
    assert not guard.is_protected("clean.py")


def test_guard_captures_modified_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "mod.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "mod.py").write_text("modified\n")

    guard = DirtyFileGuard()
    guard.capture()

    assert guard.is_protected("mod.py")
    snap = guard.snapshot_for("mod.py")
    assert snap is not None
    assert not snap.is_untracked
    assert not snap.is_conflicted
    assert snap.file_bytes_sha256 == _sha256(tmp_path / "mod.py")


def test_guard_captures_untracked_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "tracked.py").write_text("tracked\n")
    _git_add_commit(tmp_path)
    (tmp_path / "untracked.py").write_text("new\n")

    guard = DirtyFileGuard()
    guard.capture()

    assert guard.is_protected("untracked.py")
    snap = guard.snapshot_for("untracked.py")
    assert snap is not None
    assert snap.is_untracked
    assert snap.blob_before_sha256 is None


def test_guard_captures_staged_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "staged.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "staged.py").write_text("staged change\n")
    subprocess.run(["git", "add", "staged.py"], cwd=tmp_path, capture_output=True, check=True)

    guard = DirtyFileGuard()
    guard.capture()

    assert guard.is_protected("staged.py")
    snap = guard.snapshot_for("staged.py")
    assert snap is not None
    assert snap.index_status != " "


# ── write_file guard tests ───────────────────────────────────────


def test_write_file_allowed_for_clean_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("content\n")
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    result = guard.check_write_file("clean.py")
    assert result.allowed
    assert result.reason == "file_was_clean"


def test_write_file_refused_for_protected_without_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    guard = DirtyFileGuard()
    result = guard.check_write_file("dirty.py")
    assert not result.allowed
    assert result.reason == "protected_file_no_overwrite_flag"


def test_write_file_refused_for_protected_missing_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    guard = DirtyFileGuard()
    result = guard.check_write_file("dirty.py", allow_overwrite_protected=True)
    assert not result.allowed
    assert result.reason == "protected_file_missing_expected_hash"


def test_write_file_refused_for_stale_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    guard = DirtyFileGuard()
    result = guard.check_write_file(
        "dirty.py",
        allow_overwrite_protected=True,
        expected_before_sha256="sha256:" + "0" * 64,
    )
    assert not result.allowed
    assert result.reason == "protected_file_stale_hash"


def test_write_file_allowed_with_correct_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    current_hash = _sha256(tmp_path / "dirty.py")
    guard = DirtyFileGuard()
    result = guard.check_write_file(
        "dirty.py",
        allow_overwrite_protected=True,
        expected_before_sha256=current_hash,
    )
    assert result.allowed
    assert result.reason == "protected_file_hash_matched"


# ── search_replace guard tests ───────────────────────────────────


def test_search_replace_allowed_for_clean_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("content\n")
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    result = guard.check_search_replace("clean.py")
    assert result.allowed


def test_search_replace_refused_for_protected_missing_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    guard = DirtyFileGuard()
    result = guard.check_search_replace("dirty.py")
    assert not result.allowed
    assert result.reason == "protected_file_missing_expected_hash"


def test_search_replace_allowed_with_correct_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    current_hash = _sha256(tmp_path / "dirty.py")
    guard = DirtyFileGuard()
    result = guard.check_search_replace(
        "dirty.py",
        expected_before_sha256=current_hash,
    )
    assert result.allowed


# ── destructive git command tests ────────────────────────────────


def test_guard_blocks_git_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, reason = guard.is_destructive_git_command("git restore some_file.py")
    assert blocked
    assert "git restore" in reason


def test_guard_blocks_git_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git reset --hard HEAD")
    assert blocked


def test_guard_blocks_git_clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git clean -fd")
    assert blocked


def test_guard_blocks_git_stash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git stash")
    assert blocked


def test_guard_allows_safe_git_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    guard = DirtyFileGuard()
    blocked, _ = guard.is_destructive_git_command("git status")
    assert not blocked
    blocked, _ = guard.is_destructive_git_command("git diff")
    assert not blocked
    blocked, _ = guard.is_destructive_git_command("git log --oneline")
    assert not blocked


# ── tracking and report tests ────────────────────────────────────


def test_guard_tracks_touched_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "a.py").write_text("a\n")
    (tmp_path / "b.py").write_text("b\n")
    _git_add_commit(tmp_path)

    guard = DirtyFileGuard()
    guard.mark_touched("a.py")
    guard.mark_touched("b.py")

    assert "a.py" in guard.touched_files
    assert "b.py" in guard.touched_files


def test_guard_tracks_skipped_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()
    guard.mark_skipped("dirty.py", "conflict_with_existing_edits")

    assert "dirty.py" in guard.skipped_files
    assert guard.skipped_files["dirty.py"] == "conflict_with_existing_edits"


def test_guard_records_refusals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()
    guard.record_refusal("dirty.py", "protected_file_no_overwrite_flag")

    assert len(guard.refused_writes) == 1
    assert guard.refused_writes[0]["path"] == "dirty.py"


def test_guard_report_distinguishes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("clean\n")
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()
    guard.mark_touched("dirty.py")

    report = guard.report()
    assert "clean.py" not in report["dirty_files_before_mission"]
    assert "dirty.py" in report["dirty_files_before_mission"]
    assert "dirty.py" in report["files_touched_by_mission"]


def test_guard_skipped_cleared_on_touch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("changed\n")

    guard = DirtyFileGuard()
    guard.capture()
    guard.mark_skipped("dirty.py", "test")
    assert "dirty.py" in guard.skipped_files

    guard.mark_touched("dirty.py")
    assert "dirty.py" not in guard.skipped_files
    assert "dirty.py" in guard.touched_files


# ── singleton tests ──────────────────────────────────────────────


def test_get_guard_returns_singleton():
    reset_guard()
    g1 = get_guard()
    g2 = get_guard()
    assert g1 is g2


def test_reset_guard_creates_new_instance():
    reset_guard()
    g1 = get_guard()
    reset_guard()
    g2 = get_guard()
    assert g1 is not g2
