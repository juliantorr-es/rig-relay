from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from rig_relay.coordination import CoordinationStore
from rig_relay.core.guard import get_guard, reset_guard

pytestmark = [pytest.mark.integration]

@pytest.fixture(autouse=True)
def _reset_guard() -> None:
    reset_guard()


def _run(coro):
    return asyncio.run(coro)


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True
    )
    return repo


def _touch(repo: Path, *paths: str) -> None:
    import os as _os

    guard = get_guard()
    original_cwd = _os.getcwd()
    _os.chdir(repo)
    guard.capture()
    for p in paths:
        guard.mark_touched(p)
    _os.chdir(original_cwd)


def _make_tool(store_path: Path):
    from rig_relay.core.tools.base import BaseToolState
    from rig_relay.core.tools.builtins.checkpoint import (
        Checkpoint,
        CheckpointToolConfig,
    )

    return Checkpoint(
        config_getter=lambda: CheckpointToolConfig(store_root=store_path),
        state=BaseToolState(),
    )


def _make_args(**kwargs):
    from rig_relay.core.tools.builtins.checkpoint import CheckpointArgs

    return CheckpointArgs(**kwargs)


def test_checkpoint_commits_only_include_paths(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "a.py").write_text("a")
    (repo / "b.py").write_text("b")
    # Only stage a.py — b.py is dirty but unstaged, should not be committed
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True, capture_output=True)
    _touch(repo, "a.py")

    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="checkpoint(task-a): add a.py",
                        include_paths=["a.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is True
    assert result.commit_sha is not None
    assert result.files_committed == ["a.py"]
    log = subprocess.run(
        ["git", "log", "--oneline", "--name-only", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "a.py" in log.stdout
    assert "b.py" not in log.stdout


def test_checkpoint_refuses_empty_include_paths(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="empty checkpoint",
                        include_paths=[],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert result.refusal_reason is not None
    assert "empty" in result.refusal_reason.lower()


def test_checkpoint_refuses_path_outside_repo(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="outside path",
                        include_paths=["/etc/passwd"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert result.refusal_reason is not None
    assert "outside" in result.refusal_reason.lower()


def test_checkpoint_refuses_path_reserved_by_another_session(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "shared.py").write_text("shared")
    subprocess.run(
        ["git", "add", "shared.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add shared"], cwd=repo, check=True, capture_output=True
    )

    store = CoordinationStore(tmp_path / "coordination")
    store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="write",
        paths=["shared.py"],
        ttl_seconds=120,
    )

    (repo / "shared.py").write_text("modified by session-a")
    subprocess.run(
        ["git", "add", "shared.py"], cwd=repo, check=True, capture_output=True
    )
    _touch(repo, "shared.py")

    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="try to commit reserved path",
                        include_paths=["shared.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert result.refusal_reason is not None
    assert "reserved" in result.refusal_reason.lower()


def test_checkpoint_commit_message_includes_metadata(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "mod.py").write_text("modified")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True, capture_output=True)
    _touch(repo, "mod.py")

    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-test-123",
                        task_id="task-test-456",
                        message="checkpoint(task-test-456): test metadata",
                        include_paths=["mod.py"],
                        validation_summary=["uv run pytest"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is True
    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "checkpoint(task-test-456): test metadata" in log.stdout
    assert "Session: session-test-123" in log.stdout
    assert "Task: task-test-456" in log.stdout
    assert "mod.py" in log.stdout
    assert "uv run pytest" in log.stdout


def test_checkpoint_emits_artifact(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "artifact_test.py").write_text("artifact")
    subprocess.run(
        ["git", "add", "artifact_test.py"], cwd=repo, check=True, capture_output=True
    )
    _touch(repo, "artifact_test.py")

    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="checkpoint(task-a): artifact test",
                        include_paths=["artifact_test.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is True
    assert result.artifact_sha256 is not None
    assert result.artifact_sha256.startswith("sha256:")


def test_checkpoint_does_not_push(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "no_push.py").write_text("no push")
    subprocess.run(
        ["git", "add", "no_push.py"], cwd=repo, check=True, capture_output=True
    )
    _touch(repo, "no_push.py")

    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="checkpoint(task-a): no push test",
                        include_paths=["no_push.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is True
    remote = subprocess.run(
        ["git", "remote"], cwd=repo, check=True, capture_output=True, text=True
    )
    assert remote.stdout.strip() == ""


def test_checkpoint_refuses_non_existent_path(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    tool = _make_tool(tmp_path / "coordination")

    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="no file",
                        include_paths=["nonexistent.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert result.refusal_reason is not None
    assert "not exist" in result.refusal_reason.lower()


def test_checkpoint_refuses_dirty_protected_file_not_touched(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "protected.py").write_text("original")
    subprocess.run(
        ["git", "add", "protected.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add protected"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    (repo / "protected.py").write_text("modified by someone else")

    guard = get_guard()
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard.capture()
    finally:
        os.chdir(original_cwd)

    subprocess.run(
        ["git", "add", "protected.py"], cwd=repo, check=True, capture_output=True
    )

    tool = _make_tool(tmp_path / "coordination")

    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="try protected",
                        include_paths=["protected.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is False
    assert result.refusal_reason is not None
    assert (
        "dirty" in result.refusal_reason.lower()
        or "not safely patched" in result.refusal_reason.lower()
    )


def test_checkpoint_allows_protected_file_after_safe_patch(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    (repo / "safe.py").write_text("original")
    subprocess.run(["git", "add", "safe.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add safe"], cwd=repo, check=True, capture_output=True
    )

    (repo / "safe.py").write_text("modified before mission")

    guard = get_guard()
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        guard.capture()
        guard.mark_touched("safe.py")
    finally:
        os.chdir(original_cwd)

    subprocess.run(["git", "add", "safe.py"], cwd=repo, check=True, capture_output=True)

    tool = _make_tool(tmp_path / "coordination")

    os.chdir(repo)
    try:
        result = _run(
            collect_result(
                tool.run(
                    _make_args(
                        session_id="session-a",
                        task_id="task-a",
                        message="checkpoint(task-a): safe patch",
                        include_paths=["safe.py"],
                    ),
                    ctx=None,
                )
            )
        )
    finally:
        os.chdir(original_cwd)

    assert result.ok is True


def test_bash_denies_git_commit_and_add() -> None:
    from rig_relay.core.tools.builtins.bash import BashToolConfig

    config = BashToolConfig()
    denylist = config.denylist
    assert any("git commit" in item or item == "git commit" for item in denylist), (
        f"git commit not in {denylist}"
    )
    assert any("git add" in item or item == "git add" for item in denylist), (
        f"git add not in {denylist}"
    )
