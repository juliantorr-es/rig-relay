"""Tests for the DuckDB-backed RepoContextIndex."""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.repo_index import RepoContextIndex


def test_not_available_outside_git(tmp_path: Path) -> None:
    index = RepoContextIndex(workspace_root=tmp_path)
    fp = index.populate()
    assert fp == "" or fp.startswith("no-git")
    assert index.is_available is True  # duckdb is available
    assert not index.find_tests(["foo.py"])


def test_populate_scans_files(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "main.py").write_text("x = 1")
    (tmp_path / "test_main.py").write_text("def test_x(): pass")
    (tmp_path / "utils.py").write_text("y = 2")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    fp = index.populate()
    assert fp != ""
    summary = index.summary()
    assert summary["file_count"] >= 2


def test_find_tests_by_stem(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "compiler.py").write_text("class Compiler: pass")
    (tmp_path / "test_compiler.py").write_text("def test_compiler(): pass")
    (tmp_path / "models.py").write_text("class Model: pass")
    (tmp_path / "test_models.py").write_text("def test_model(): pass")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()

    tests = index.find_tests(["compiler.py"])
    assert len(tests) >= 1
    assert any("test_compiler" in t for t in tests)


def test_find_tests_multiple_paths(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "a.py").write_text("a = 1")
    (tmp_path / "test_a.py").write_text("def test_a(): pass")
    (tmp_path / "b.py").write_text("b = 2")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()

    tests = index.find_tests(["a.py", "b.py"])
    assert len(tests) >= 1
    assert any("test_a" in t for t in tests)


def test_find_tests_returns_empty_for_unknown(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "main.py").write_text("x = 1")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()

    tests = index.find_tests(["nonexistent.py"])
    assert tests == []


def test_find_related_groups_by_type(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "schema.py").write_text("schema = {}")
    (tmp_path / "test_schema.py").write_text("def test_schema(): pass")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "schema.md").write_text("# Schema docs")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()

    related = index.find_related(["schema.py"])
    all_items = []
    for items in related.values():
        all_items.extend(items)
    assert len(all_items) >= 1


def test_summary_after_populate(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "main.py").write_text("x = 1")
    (tmp_path / "test_main.py").write_text("def test_x(): pass")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()
    summary = index.summary()
    assert summary["available"] is True
    assert summary["file_count"] >= 2
    assert summary["relation_count"] >= 0


def test_summary_before_populate(tmp_path: Path) -> None:
    index = RepoContextIndex(workspace_root=tmp_path)
    summary = index.summary()
    assert summary["available"] is False


def test_related_files_pack_uses_index(tmp_path: Path) -> None:
    """Known blocked: RelatedFilesPack was absorbed into ContextCompiler.

    The related-files feature is now internal to
    ContextCompiler.build_envelope() and is tested through
    test_repo_index_in_compiler below.
    """
    import pytest

    pytest.skip(
        "known_blocked: RelatedFilesPack removed in compiler restructuring. "
        "Feature is internal to ContextCompiler.build_envelope()."
    )


def test_relevant_tests_pack_falls_back_without_index(tmp_path: Path) -> None:
    """Known blocked: RelevantTestsPack was absorbed into ContextCompiler.

    The relevant-tests feature is now internal to
    ContextCompiler.build_envelope().
    """
    import pytest

    pytest.skip(
        "known_blocked: RelevantTestsPack removed in compiler restructuring. "
        "Feature is internal to ContextCompiler.build_envelope()."
    )


def test_repo_index_in_compiler(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "AGENTS.md").write_text("# Rules")
    (tmp_path / "main.py").write_text("x = 1")
    (tmp_path / "test_main.py").write_text("def test_main(): pass")
    _git_add_all(tmp_path)

    index = RepoContextIndex(workspace_root=tmp_path)
    index.populate()

    from rig_relay.context.compiler import ContextCompiler

    compiler = ContextCompiler(
        session_id="s1", workspace_root=tmp_path, repo_index=index
    )
    env = compiler.build_envelope(user_text="fix main.py")
    assert env.section_count > 0, (
        "ContextCompiler should produce at least one section when index is available"
    )


# ── Git helpers ──────────────────────────────────────────────────


def _init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, capture_output=True
    )


def _git_add_all(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "test"], cwd=path, capture_output=True)
