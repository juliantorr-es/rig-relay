"""Disposable Git repository fixtures for digestion testing.

Slice 1A.1: Preview Proof and Desktop Wiring.
Creates real temporary Git repositories for ecosystem intake testing.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import pytest


@pytest.fixture
def python_repo() -> Path:
    """Create a disposable Python project git repository."""
    return _create_repo("python", _build_python_repo)


@pytest.fixture
def typescript_repo() -> Path:
    """Create a disposable TypeScript project git repository."""
    return _create_repo("typescript", _build_typescript_repo)


@pytest.fixture
def rust_repo() -> Path:
    """Create a disposable Rust project git repository."""
    return _create_repo("rust", _build_rust_repo)


@pytest.fixture
def dirty_repo() -> Path:
    """Create a Python git repo with uncommitted changes."""
    repo = _create_repo("dirty", _build_python_repo)
    # Modify a tracked file without committing
    (repo / "src" / "my_package" / "core.py").write_text("# modified content\n")
    # Create an untracked file
    (repo / "untracked.txt").write_text("untracked\n")
    return repo


@pytest.fixture
def nested_instructions_repo() -> Path:
    """Create a Python repo with nested AGENTS.md instructions."""
    repo = _create_repo("nested", _build_python_repo)

    # Add nested instructions under src/subpackage/
    subpkg = repo / "src" / "my_package" / "subpackage"
    subpkg.mkdir(parents=True, exist_ok=True)
    (subpkg / "__init__.py").write_text("")
    (subpkg / "AGENTS.md").write_text("# Subpackage agent instructions\n")
    subprocess.run(["git", "--no-optional-locks", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "--no-optional-locks", "commit", "-m", "add nested instructions"],
        cwd=repo,
        check=True,
    )
    return repo


@pytest.fixture
def any_repo(python_repo: Path) -> Path:
    """Alias for python_repo — the most common test fixture."""
    return python_repo


def snapshot_dir(root: Path) -> dict[str, tuple[bool, int, bool]]:
    """Take a full filesystem snapshot of a directory.

    Returns a dict mapping relative_path → (is_dir, size, is_symlink).
    Includes ALL files including .git/ internals, ignored files, and
    untracked content. Used for Gate 0 before/after comparison.

    The snapshot is sorted by path for deterministic comparison.
    """
    snapshot: dict[str, tuple[bool, int, bool]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            full = Path(dirpath) / name
            rel = str(full.relative_to(root))
            is_dir = full.is_dir() and not full.is_symlink()
            is_sym = full.is_symlink()
            try:
                size = full.stat().st_size if not is_dir else 0
            except OSError:
                size = -1
            snapshot[rel] = (is_dir, size, is_sym)
    return snapshot


def snapshot_diff(
    before: dict[str, tuple[bool, int, bool]], after: dict[str, tuple[bool, int, bool]]
) -> list[str]:
    """Compare two filesystem snapshots and return human-readable diffs."""
    diffs: list[str] = []
    all_paths = set(before) | set(after)
    for path in sorted(all_paths):
        b = before.get(path)
        a = after.get(path)
        if b is None:
            diffs.append(f"ADDED: {path}")
        elif a is None:
            diffs.append(f"REMOVED: {path}")
        elif b != a:
            diffs.append(f"CHANGED: {path} (was {b}, now {a})")
    return diffs


def assert_no_filesystem_mutation(
    before: dict[str, tuple[bool, int, bool]],
    after: dict[str, tuple[bool, int, bool]],
    label: str = "",
) -> None:
    """Assert that the filesystem snapshot is unchanged.

    Raises AssertionError with human-readable diff if any mutation occurred.
    """
    diffs = snapshot_diff(before, after)
    prefix = f"[{label}] " if label else ""
    assert not diffs, (
        f"{prefix}Filesystem mutation detected during read-only preview intake:\n"
        + "\n".join(f"  {d}" for d in diffs)
    )


# ── Internal helpers ──────────────────────────────────────────────


def _create_repo(name: str, builder) -> Path:
    """Create a disposable git repository with one initial commit."""
    tmpdir = Path(tempfile.mkdtemp(prefix=f"rig_test_{name}_"))
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


def _write(repo: Path, rel_path: str, content: str) -> None:
    """Write a file inside the repo, creating parent directories."""
    full = repo / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _build_python_repo(repo: Path) -> None:
    _write(repo, "pyproject.toml", PYPROJECT_CONTENT)
    _write(repo, "uv.lock", "# uv lockfile\n")
    _write(repo, "src/my_package/__init__.py", "")
    _write(
        repo,
        "src/my_package/core.py",
        "# Core module\n\ndef hello():\n    return 'hello'\n",
    )
    _write(
        repo,
        "tests/test_core.py",
        "from my_package.core import hello\n\n\ndef test_hello():\n    assert hello() == 'hello'\n",
    )
    _write(
        repo, "AGENTS.md", "# Agent Instructions\n\nUse `uv run pytest` for testing.\n"
    )


def _build_typescript_repo(repo: Path) -> None:
    import json

    _write(
        repo,
        "package.json",
        json.dumps(
            {
                "name": "test-ts-project",
                "scripts": {"test": "jest", "lint": "eslint .", "build": "tsc"},
                "devDependencies": {
                    "jest": "^29.0.0",
                    "eslint": "^8.0.0",
                    "typescript": "^5.0.0",
                    "prettier": "^3.0.0",
                },
            },
            indent=2,
        ),
    )
    _write(
        repo,
        "tsconfig.json",
        json.dumps({"compilerOptions": {"strict": True}}, indent=2),
    )
    _write(repo, "src/index.ts", "export const hello = (): string => 'hello';\n")
    _write(
        repo,
        "__tests__/index.test.ts",
        "import { hello } from '../src/index';\n\ntest('hello', () => { expect(hello()).toBe('hello'); });\n",
    )


def _build_rust_repo(repo: Path) -> None:
    _write(repo, "Cargo.toml", CARGO_CONTENT)
    _write(repo, "src/main.rs", 'fn main() {\n    println!("Hello");\n}\n')
    _write(
        repo,
        "tests/integration_test.rs",
        "#[test]\nfn test_hello() {\n    assert_eq!(1 + 1, 2);\n}\n",
    )


PYPROJECT_CONTENT = """\
[project]
name = "my-project"
version = "1.0.0"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.14",
    "pyright>=1.1",
]
"""

CARGO_CONTENT = """\
[package]
name = "test-rust-project"
version = "1.0.0"
edition = "2021"

[[bin]]
name = "main"
path = "src/main.rs"
"""
