"""Gate 0 filesystem snapshot and ecosystem detection tests.

Slice 1A.1: Preview Proof and Desktop Wiring.
Proves that read-only intake creates zero filesystem mutations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.digestion.identity import resolve_git_porcelain_v2
from rig_relay.digestion.intake import RepositoryIntakeService
from tests.digestion.conftest import assert_no_filesystem_mutation, snapshot_dir


@pytest.fixture
def intake_service() -> RepositoryIntakeService:
    return RepositoryIntakeService()


def _run_intake(repo: Path) -> None:
    """Run intake on a repo. Used for Gate 0 — we don't assert the result,
    we assert the repo is unchanged.
    """
    service = RepositoryIntakeService()
    service.open_local_repository(repo)


# ── Gate 0: Filesystem mutation tests ─────────────────────────────


def test_gate_0_python_repo_untouched(python_repo: Path) -> None:
    """Gate 0: Intake does not mutate a Python repository."""
    before = snapshot_dir(python_repo)
    _run_intake(python_repo)
    after = snapshot_dir(python_repo)
    assert_no_filesystem_mutation(before, after, "python_repo")


def test_gate_0_typescript_repo_untouched(typescript_repo: Path) -> None:
    """Gate 0: Intake does not mutate a TypeScript repository."""
    before = snapshot_dir(typescript_repo)
    _run_intake(typescript_repo)
    after = snapshot_dir(typescript_repo)
    assert_no_filesystem_mutation(before, after, "typescript_repo")


def test_gate_0_rust_repo_untouched(rust_repo: Path) -> None:
    """Gate 0: Intake does not mutate a Rust repository."""
    before = snapshot_dir(rust_repo)
    _run_intake(rust_repo)
    after = snapshot_dir(rust_repo)
    assert_no_filesystem_mutation(before, after, "rust_repo")


def test_gate_0_dirty_repo_untouched(dirty_repo: Path) -> None:
    """Gate 0: Intake reads dirty state but does not modify uncommitted changes."""
    before = snapshot_dir(dirty_repo)
    _run_intake(dirty_repo)
    after = snapshot_dir(dirty_repo)
    assert_no_filesystem_mutation(before, after, "dirty_repo")


def test_gate_0_git_directory_included_in_snapshot(python_repo: Path) -> None:
    """Gate 0: The filesystem snapshot includes .git/ internals (index, HEAD, refs)."""
    before = snapshot_dir(python_repo)
    _run_intake(python_repo)
    after = snapshot_dir(python_repo)

    # Verify .git/ is present in the snapshot
    git_entries = [k for k in before if k.startswith(".git/")]
    assert len(git_entries) > 0, "Snapshot must include .git/ directory contents"

    # Verify .git/index specifically is in the snapshot and unchanged
    assert ".git/index" in before, "Snapshot must include .git/index"
    assert before[".git/index"] == after[".git/index"], (
        ".git/index must be unchanged after read-only intake"
    )


def test_gate_0_porcelain_v2_unchanged(python_repo: Path) -> None:
    """Gate 0: git status --porcelain=v2 output is identical before/after intake."""
    before = resolve_git_porcelain_v2(python_repo)
    _run_intake(python_repo)
    after = resolve_git_porcelain_v2(python_repo)
    assert before == after, (
        "git status --porcelain=v2 must be unchanged after read-only intake"
    )


# ── Ecosystem detection tests ─────────────────────────────────────


def test_python_ecosystem_detection(python_repo: Path) -> None:
    """Python repo: detect python ecosystem with definite confidence."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(python_repo)
    picture = result.operating_picture
    ecosystems = picture.detected_ecosystems

    assert len(ecosystems) >= 1
    python = next(e for e in ecosystems if e.language == "python")
    assert python.confidence == "definite"
    assert "pyproject.toml" in python.evidence_files
    assert python.package_manager is not None
    assert "pytest" in python.test_frameworks
    assert "ruff" in python.lint_tools
    assert "pyright" in python.type_checkers


def test_typescript_ecosystem_detection(typescript_repo: Path) -> None:
    """TypeScript repo: detect typescript ecosystem."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(typescript_repo)
    picture = result.operating_picture
    ecosystems = picture.detected_ecosystems

    assert len(ecosystems) >= 1
    ts = ecosystems[0]
    assert ts.language == "typescript"
    assert ts.confidence == "definite"
    assert "package.json" in ts.evidence_files
    assert "tsconfig.json" in ts.evidence_files
    assert "tsc" in ts.type_checkers


def test_rust_ecosystem_detection(rust_repo: Path) -> None:
    """Rust repo: detect rust ecosystem."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(rust_repo)
    picture = result.operating_picture
    ecosystems = picture.detected_ecosystems

    assert len(ecosystems) >= 1
    rust = ecosystems[0]
    assert rust.language == "rust"
    assert rust.confidence == "definite"
    assert "Cargo.toml" in rust.evidence_files
    assert "cargo" in (rust.package_manager or "")


def test_nested_instruction_discovery(nested_instructions_repo: Path) -> None:
    """Nested instructions: discover root and nested AGENTS.md with correct scope."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(nested_instructions_repo)
    picture = result.operating_picture
    instructions = picture.instruction_files

    assert len(instructions) >= 2

    # Find root AGENTS.md
    root = next(i for i in instructions if i.scope.path == "AGENTS.md")
    assert root.scope.scope_depth == 0
    assert root.scope.scope_root == "."

    # Find nested AGENTS.md
    nested = next(i for i in instructions if "subpackage/AGENTS.md" in i.scope.path)
    assert nested.scope.scope_depth > 0
    assert nested.scope.parent_instruction_path is not None


def test_dirty_state_detection(dirty_repo: Path) -> None:
    """Dirty repo: correctly reports modified and untracked counts."""
    service = RepositoryIntakeService()
    result = service.open_local_repository(dirty_repo)
    ds = result.operating_picture.dirty_state

    assert ds.modified >= 1
    assert ds.untracked >= 1
