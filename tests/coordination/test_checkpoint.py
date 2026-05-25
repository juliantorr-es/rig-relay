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
    import json

    from rig_relay.core.tools.builtins.checkpoint import CheckpointArgs
    from rig_relay.governance.auth_receipts import generate_dev_receipt

    if "authorization_receipt" not in kwargs:
        kwargs["authorization_receipt"] = json.dumps(
            generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        )
    return CheckpointArgs(**kwargs)


def test_checkpoint_commits_only_include_paths(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
    (repo / "a.py").write_text("a")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "a"], cwd=repo, check=True, capture_output=True
    )
    (repo / "a.py").write_text("a modified")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True, capture_output=True)
    (repo / "b.py").write_text("b")
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
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
    assert "unstaged_file_refused" == result.refusal_reason


def test_checkpoint_refuses_path_reserved_by_another_session(tmp_path: Path) -> None:
    from tests.mock.utils import collect_result

    repo = _init_git_repo(tmp_path)
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
    (repo / "mod.py").write_text("modified")
    subprocess.run(["git", "add", "mod.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "mod base"], cwd=repo, check=True, capture_output=True
    )
    (repo / "mod.py").write_text("modified again")
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
    (repo / "artifact_test.py").write_text("artifact")
    subprocess.run(
        ["git", "add", "artifact_test.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "artifact base"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "artifact_test.py").write_text("artifact modified")
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
    (repo / "no_push.py").write_text("no push")
    subprocess.run(
        ["git", "add", "no_push.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "no push base"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "no_push.py").write_text("no push modified")
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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
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
    assert "unstaged_file_refused" == result.refusal_reason


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
    import os

    original_cwd = os.getcwd()
    os.chdir(repo)
    get_guard().capture()
    os.chdir(original_cwd)
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


def test_checkpoint_commit_receipt_digest_trailer_present(tmp_path, monkeypatch):
    """Receipt digest trailer appears in commit when auth receipt provided."""
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True
    )
    (tmp_path / "mod.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "mod.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    monkeypatch.chdir(tmp_path)
    get_guard().capture()
    (tmp_path / "mod.py").write_text("x=2")
    get_guard().mark_touched(tmp_path / "mod.py")

    import hashlib
    import json

    receipt = {
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "action": "checkpoint.commit",
        "action_scope": {
            "campaign_id": "cid",
            "manifest_digest": "m",
            "branch": "b",
            "mission_identity": "mid",
            "include_paths": ["mod.py"],
            "checkpoint_sequence": 1,
        },
        "user_verified": True,
        "method": "test",
        "issued_at": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "receipt_id": "test-receipt-id",
    }
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    expected_digest = "sha256:" + hashlib.sha256(receipt_json.encode()).hexdigest()

    from rig_relay.core.tools.base import BaseToolState
    from rig_relay.core.tools.builtins.checkpoint import (
        Checkpoint,
        CheckpointArgs,
        CheckpointResult,
        CheckpointToolConfig,
    )

    tool = Checkpoint(
        config_getter=lambda: CheckpointToolConfig(), state=BaseToolState()
    )
    args = CheckpointArgs(
        message="test", include_paths=["mod.py"], authorization_receipt=receipt_json
    )
    (tmp_path / "mod.py").write_text("x=2")
    subprocess.run(["git", "-C", str(tmp_path), "add", "mod.py"], capture_output=True)
    results = []

    async def _run():
        async for ev in tool.run(args, ctx=None):
            if isinstance(ev, CheckpointResult):
                results.append(ev)

    asyncio.run(_run())
    assert results
    result = results[-1]
    assert result.authorization_receipt_sha256 == expected_digest

    output = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--format=%B", "-1"],
        capture_output=True,
        text=True,
    ).stdout
    assert f"Rig-Authorization-Receipt-SHA256: {expected_digest}" in output


def test_checkpoint_omits_trailer_when_no_auth_receipt(tmp_path, monkeypatch):
    """No trailer when no authorization_receipt provided."""
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True
    )
    (tmp_path / "mod.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "mod.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "mod.py").write_text("x=2")
    monkeypatch.chdir(tmp_path)
    get_guard().capture()

    from rig_relay.core.tools.base import BaseToolState
    from rig_relay.core.tools.builtins.checkpoint import (
        Checkpoint,
        CheckpointArgs,
        CheckpointResult,
        CheckpointToolConfig,
    )

    tool = Checkpoint(
        config_getter=lambda: CheckpointToolConfig(), state=BaseToolState()
    )
    args = CheckpointArgs(message="test", include_paths=["mod.py"])
    results = []

    async def _run():
        async for ev in tool.run(args, ctx=None):
            if isinstance(ev, CheckpointResult):
                results.append(ev)

    asyncio.run(_run())
    assert results
    result = results[-1]
    assert result.authorization_receipt_sha256 is None

    output = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--format=%B", "-1"],
        capture_output=True,
        text=True,
    ).stdout
    assert "Rig-Authorization-Receipt-SHA256" not in output
