"""Tests for repo_map — verifies git-based repo topology scanning.

Uses a temporary git repository to test against real data.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.repo_map import (
    build_repo_info,
    build_subsystem_map,
    git_ls_files,
    git_status_short,
)


def _init_git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo with some files."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)

    # Create some files
    (tmp_path / "README.md").write_text("# Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "main.py").write_text("def main(): pass")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")

    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

    # Create an untracked file
    (tmp_path / "untracked.txt").write_text("untracked")

    return tmp_path


class TestBuildRepoInfo:
    def test_repo_info_has_branch_and_head(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        info = build_repo_info(repo)
        assert info.root == str(repo.resolve())
        assert info.branch == "main"
        assert len(info.head) >= 7

    def test_dirty_summary_detects_untracked(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        info = build_repo_info(repo)
        assert info.dirty_summary["untracked"] >= 1

    def test_repo_info_no_git(self, tmp_path: Path) -> None:
        info = build_repo_info(tmp_path)
        assert info.head == "unknown"
        assert info.branch == "unknown"


class TestBuildSubsystemMap:
    def test_subsystems_detected(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        subsystems = build_subsystem_map(repo)
        names = [s.name for s in subsystems]
        assert "src" in names
        assert "docs" in names
        assert "tests" in names
        assert "README.md" in names

    def test_entry_points_detected(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        subsystems = build_subsystem_map(repo)
        for s in subsystems:
            if s.name == "src":
                assert "__init__.py" in s.entry_points[0]
                break

    def test_config_files_detected(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        subsystems = build_subsystem_map(repo)
        all_configs = []
        for s in subsystems:
            all_configs.extend(s.config_files)
        assert any("pyproject.toml" in c for c in all_configs)

    def test_tests_detected(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        subsystems = build_subsystem_map(repo)
        for s in subsystems:
            if s.name == "tests":
                assert len(s.tests) >= 1
                break


class TestGitHelpers:
    def test_git_ls_files(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        files = git_ls_files(repo)
        assert len(files) >= 4

    def test_git_status_short(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path)
        status = git_status_short(repo)
        assert "?" in status  # untracked file

    def test_git_ls_files_no_git(self, tmp_path: Path) -> None:
        files = git_ls_files(tmp_path)
        assert files == []
