"""Disposable Git repository fixtures for Repository Estate testing.

Creates real temporary Git repositories on disk and provides a
pre-configured RepositoryEstateService pointing at an isolated
evidence store.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

import pytest

from rig_relay.repository_estate._service import RepositoryEstateService


@pytest.fixture
def clean_repo() -> Path:
    """Create a disposable git repository with one initial commit and clean working tree."""
    return _create_repo("clean", _build_basic_repo)


@pytest.fixture
def dirty_repo() -> Path:
    """Create a git repo with uncommitted changes (modified + untracked)."""
    repo = _create_repo("dirty", _build_basic_repo)
    (repo / "src" / "main.py").write_text("# modified content\n")
    (repo / "untracked.txt").write_text("untracked\n")
    return repo


@pytest.fixture
def detached_repo() -> Path:
    """Create a git repo with detached HEAD."""
    repo = _create_repo("detached", _build_basic_repo)
    # Create a second commit and checkout the first commit to detach
    (repo / "README.md").write_text("# Detached test\n")
    subprocess.run(
        ["git", "--no-optional-locks", "add", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "second commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "checkout", "HEAD~1"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


@pytest.fixture
def estate_service(tmp_path: Path) -> RepositoryEstateService:
    """Create a RepositoryEstateService with an isolated evidence store."""
    store_root = tmp_path / "repository_estate"
    return RepositoryEstateService(store_root)


@pytest.fixture
def non_repo_path(tmp_path: Path) -> Path:
    """Create a directory that is not a git repository."""
    p = tmp_path / "not_a_repo"
    p.mkdir()
    (p / "file.txt").write_text("not a repo\n")
    return p


# ── Internal helpers ──────────────────────────────────────────────


def _create_repo(name: str, builder) -> Path:
    """Create a disposable git repository with one initial commit."""
    tmpdir = Path(tempfile.mkdtemp(prefix=f"rig_test_re_{name}_"))
    builder(tmpdir)
    subprocess.run(
        ["git", "--no-optional-locks", "init", "-b", "main"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.email", "test@rig.relay"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "config", "user.name", "Rig Test"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "add", "."],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "initial commit"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    return tmpdir


def _build_basic_repo(repo: Path) -> None:
    _write(repo, "AGENTS.md", "# Agent instructions\n\nUse `uv run pytest`.\n")
    _write(repo, "README.md", "# Test Project\n")
    _write(repo, "src/main.py", "def hello():\n    return 'hello'\n")
    _write(
        repo,
        "tests/test_main.py",
        "from src.main import hello\n\ndef test_hello():\n    assert hello() == 'hello'\n",
    )


def _write(repo: Path, rel_path: str, content: str) -> None:
    full = repo / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
