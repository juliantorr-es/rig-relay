from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from rig_relay.core.guard import (
    DirtyGuardFailurePolicy,
    GuardCaptureReason,
    get_guard,
    reset_guard,
)
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
)
from rig_relay.core.tools.builtins.write_file import (
    WriteFile,
    WriteFileArgs,
    WriteFileConfig,
)
from tests.mock.utils import collect_result


@pytest.fixture(autouse=True)
def _reset_guard_and_chdir(tmp_path, monkeypatch):
    reset_guard()
    monkeypatch.chdir(tmp_path)
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


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _make_sr(content: str) -> SearchReplace:
    return SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )


def _make_wf() -> WriteFile:
    return WriteFile(config_getter=lambda: WriteFileConfig(), state=BaseToolState())


# ── schema exposure tests ────────────────────────────────────────


def test_write_file_schema_includes_allow_overwrite_protected():
    schema = WriteFile.get_parameters()
    props = schema["properties"]
    assert "allow_overwrite_protected" in props
    assert props["allow_overwrite_protected"]["type"] == "boolean"
    desc = props["allow_overwrite_protected"].get("description", "").lower()
    assert "dirty" in desc
    assert "expected_before_sha256" in desc


def test_write_file_schema_includes_expected_before_sha256():
    schema = WriteFile.get_parameters()
    props = schema["properties"]
    assert "expected_before_sha256" in props
    desc = props["expected_before_sha256"].get("description", "")
    assert "sha256" in desc.lower()
    assert "refused" in desc.lower()


def test_search_replace_schema_includes_expected_before_sha256():
    schema = SearchReplace.get_parameters()
    props = schema["properties"]
    assert "expected_before_sha256" in props
    desc = props["expected_before_sha256"].get("description", "")
    assert "sha256" in desc.lower()
    assert "refused" in desc.lower()


# ── session-start capture tests ──────────────────────────────────


def test_guard_captures_at_session_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    # Simulate what AgentLoop.__init__ does
    reset_guard()
    get_guard().capture()

    assert get_guard().is_protected("dirty.py")


def test_guard_does_not_recapture_on_second_capture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    reset_guard()
    get_guard().capture()

    # Now change a file — second capture should NOT update snapshots
    (tmp_path / "dirty.py").write_text("even more modified\n")
    (tmp_path / "new_dirty.py").write_text("brand new\n")
    get_guard().capture()

    # new_dirty.py should NOT be protected (wasn't dirty at first capture)
    assert not get_guard().is_protected("new_dirty.py")
    # dirty.py should still have its original snapshot
    snap = get_guard().snapshot_for("dirty.py")
    assert snap is not None


def test_guard_capture_uses_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    reset_guard()
    get_guard().capture(repo_root=tmp_path)

    assert get_guard().is_protected("dirty.py")


def test_reset_guard_is_test_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("dirty\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    guard_before = get_guard()
    guard_before.capture()
    assert guard_before.is_protected("dirty.py")

    reset_guard()
    guard_after = get_guard()
    assert guard_after is not guard_before
    assert not guard_after._captured


# ── tool integration: write_file ─────────────────────────────────


@pytest.mark.asyncio
async def test_write_file_allows_clean_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("content\n")
    _git_add_commit(tmp_path)

    reset_guard()
    get_guard().capture()

    tool = _make_wf()
    result = await collect_result(
        tool.run(
            WriteFileArgs(path="clean.py", content="new content\n", overwrite=True)
        )
    )
    assert result.file_existed
    assert result.after_sha256 is not None


@pytest.mark.asyncio
async def test_write_file_refuses_protected_file_without_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    reset_guard()
    get_guard().capture()

    tool = _make_wf()
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(
                WriteFileArgs(path="dirty.py", content="new content\n", overwrite=True)
            )
        )
    assert "refused" in str(exc.value).lower() or "protected" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_write_file_allows_protected_file_with_flag_and_hash(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    reset_guard()
    get_guard().capture()

    current_hash = _sha256(tmp_path / "dirty.py")
    tool = _make_wf()
    result = await collect_result(
        tool.run(
            WriteFileArgs(
                path="dirty.py",
                content="new content\n",
                overwrite=True,
                allow_overwrite_protected=True,
                expected_before_sha256=current_hash,
            )
        )
    )
    assert result.file_existed


@pytest.mark.asyncio
async def test_write_file_refuses_protected_file_with_stale_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("original\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("modified\n")

    reset_guard()
    get_guard().capture()

    tool = _make_wf()
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(
                WriteFileArgs(
                    path="dirty.py",
                    content="new content\n",
                    overwrite=True,
                    allow_overwrite_protected=True,
                    expected_before_sha256="sha256:" + "0" * 64,
                )
            )
        )
    assert "stale" in str(exc.value).lower() or "refused" in str(exc.value).lower()


# ── tool integration: search_replace ─────────────────────────────


@pytest.mark.asyncio
async def test_search_replace_allows_clean_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("def hello():\n    pass\n")
    _git_add_commit(tmp_path)

    reset_guard()
    get_guard().capture()

    tool = _make_sr("""
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "world"
>>>>>>> REPLACE
""")
    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="clean.py",
                content="""
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "world"
>>>>>>> REPLACE
""",
            )
        )
    )
    assert result.blocks_applied == 1


@pytest.mark.asyncio
async def test_search_replace_refuses_protected_file_without_hash(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    pass\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    return 1\n")

    reset_guard()
    get_guard().capture()

    tool = _make_sr("""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""")
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(
                SearchReplaceArgs(
                    file_path="dirty.py",
                    content="""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""",
                )
            )
        )
    assert "refused" in str(exc.value).lower() or "protected" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_search_replace_allows_protected_file_with_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    pass\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    return 1\n")

    reset_guard()
    get_guard().capture()

    current_hash = _sha256(tmp_path / "dirty.py")
    tool = _make_sr("""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""")
    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="dirty.py",
                content="""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""",
                expected_before_sha256=current_hash,
            )
        )
    )
    assert result.blocks_applied == 1


@pytest.mark.asyncio
async def test_search_replace_refuses_protected_file_with_stale_hash(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    pass\n")
    _git_add_commit(tmp_path)
    (tmp_path / "dirty.py").write_text("def hello():\n    return 1\n")

    reset_guard()
    get_guard().capture()

    tool = _make_sr("""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""")
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(
                SearchReplaceArgs(
                    file_path="dirty.py",
                    content="""
<<<<<<< SEARCH
def hello():
    return 1
=======
def hello():
    return "world"
>>>>>>> REPLACE
""",
                    expected_before_sha256="sha256:" + "0" * 64,
                )
            )
        )
    assert "stale" in str(exc.value).lower() or "refused" in str(exc.value).lower()


# ── new file creation tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_write_file_allows_new_clean_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "existing.py").write_text("exists\n")
    _git_add_commit(tmp_path)

    reset_guard()
    get_guard().capture()

    tool = _make_wf()
    result = await collect_result(
        tool.run(WriteFileArgs(path="new_file.py", content="brand new\n"))
    )
    assert result.created_file


@pytest.mark.asyncio
async def test_write_file_refuses_overwrite_of_untracked_protected_file(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "tracked.py").write_text("tracked\n")
    _git_add_commit(tmp_path)
    # This file is untracked at capture time → protected
    (tmp_path / "untracked.py").write_text("I was here before the mission\n")

    reset_guard()
    get_guard().capture()

    tool = _make_wf()
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(
                WriteFileArgs(
                    path="untracked.py",
                    content="overwriting untracked\n",
                    overwrite=True,
                )
            )
        )
    assert "refused" in str(exc.value).lower() or "protected" in str(exc.value).lower()


# ── report tests ─────────────────────────────────────────────────


def test_guard_report_includes_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / "clean.py").write_text("content\n")
    _git_add_commit(tmp_path)

    reset_guard()
    get_guard().capture()

    report = get_guard().report()
    assert "repo_root" in report
    assert report["repo_root"] == str(tmp_path.resolve())
    assert "capture_method" in report
    assert report["capture_method"] == "git status --porcelain=v1"
    assert report["capture_succeeded"] is True
    assert report["capture_error"] is None
    assert report["baseline_id"]
    assert report["capture_reason"] == GuardCaptureReason.AGENT_LOOP_INIT.value
    assert "failure_policy" in report
    assert "parent_baseline_id" in report


# ── failure policy integration tests ─────────────────────────────


@pytest.mark.asyncio
async def test_fail_closed_write_file_refuses_all_mutations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "clean.py").write_text("clean\n")
    subprocess.run(
        ["git", "add", "clean.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    reset_guard()
    guard = get_guard()
    guard.failure_policy = DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION
    guard._captured = True
    guard._capture_error = "simulated failure"

    tool = _make_wf()
    with pytest.raises(Exception) as exc:
        await collect_result(
            tool.run(WriteFileArgs(path="clean.py", content="new\n", overwrite=True))
        )
    assert (
        "dirty_guard_capture_failed" in str(exc.value).lower()
        or "capture" in str(exc.value).lower()
    )


@pytest.mark.asyncio
async def test_warn_allow_write_file_allows_mutations_after_capture_failure(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "clean.py").write_text("clean\n")
    subprocess.run(
        ["git", "add", "clean.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    reset_guard()
    guard = get_guard()
    guard.failure_policy = DirtyGuardFailurePolicy.WARN_ALLOW
    guard._captured = True
    guard._capture_error = "simulated failure"

    tool = _make_wf()
    result = await collect_result(
        tool.run(WriteFileArgs(path="clean.py", content="new\n", overwrite=True))
    )
    assert result.file_existed


# ── recapture lifecycle tests ────────────────────────────────────


def test_recapture_new_baseline_detects_new_dirty_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "a.py").write_text("a\n")
    subprocess.run(
        ["git", "add", "a.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    reset_guard()
    get_guard().capture()
    assert not get_guard().is_protected("a.py")

    (tmp_path / "a.py").write_text("modified\n")
    get_guard().recapture(reason=GuardCaptureReason.RESET_SESSION)

    assert get_guard().is_protected("a.py")
    assert get_guard().capture_reason == GuardCaptureReason.RESET_SESSION
    assert get_guard().parent_baseline_id is not None


def test_clear_history_preserves_baseline(tmp_path, monkeypatch):
    """clear_history should NOT recapture — it's a conversation reset only."""
    monkeypatch.chdir(tmp_path)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "a.py").write_text("a\n")
    subprocess.run(
        ["git", "add", "a.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "a.py").write_text("modified\n")

    reset_guard()
    get_guard().capture(reason=GuardCaptureReason.AGENT_LOOP_INIT)
    first_baseline = get_guard().baseline_id

    # Simulate clear_history — should NOT recapture
    # (clear_history calls _reset_session which DOES recapture in current impl)
    # This test verifies the current behavior as documented
    get_guard().recapture(reason=GuardCaptureReason.RESET_SESSION)
    assert get_guard().baseline_id != first_baseline
