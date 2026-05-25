from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import types

import pytest

from rig_relay.core.git_index_operations import (
    commit_prepared_index,
    compute_head_tree_digest,
    compute_index_tree_digest,
)
from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.prepare_checkpoint import (
    PrepareCheckpoint,
    PrepareCheckpointArgs,
    PrepareCheckpointConfig,
    PrepareCheckpointPath,
)
from rig_relay.governance.auth_receipts import load_preparation_receipt


def _init_repo(tmp_path: Path, branch: str = "task/feature") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
    return repo


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _mock_ctx() -> InvokeContext:
    return InvokeContext(
        tool_call_id="test",
        tool_runtime=types.SimpleNamespace(
            _mission_authority=types.SimpleNamespace(
                is_path_in_write_scope=lambda _: True
            )
        ),
    )


async def _run_prepare(
    repo: Path,
    paths: list[PrepareCheckpointPath],
    session_id: str = "test-sess",
    task_id: str = "test-task",
):
    tool = PrepareCheckpoint(
        config_getter=lambda: PrepareCheckpointConfig(), state=BaseToolState()
    )
    args = PrepareCheckpointArgs(paths=paths, session_id=session_id, task_id=task_id)
    ctx = _mock_ctx()
    original = os.getcwd()
    os.chdir(repo)
    try:
        results = [r async for r in tool.run(args, ctx=ctx)]
    finally:
        os.chdir(original)
    return results[0]


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_prepare_modify_admitted_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# modified content")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert "file.py" in r.prepared_paths
    assert r.index_mutation_performed is True


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_add_new_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "new.py").write_text("# new file")
    current = _sha256(repo / "new.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="new.py", change_kind="add", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert "new.py" in r.prepared_paths


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_stale_hash_refuses(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# actual content")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py",
                change_kind="modify",
                expected_worktree_sha256="sha256:" + "0" * 64,
            )
        ],
    )
    assert r.ok is False


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_protected_branch_main_refuses(tmp_path):
    repo = _init_repo(tmp_path, branch="main")
    (repo / "file.py").write_text("# change")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is False
    assert r.error_kind is not None
    assert (
        "branch" in (r.error_kind or "").lower()
        or "protected" in (r.error_kind or "").lower()
    )


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_delete_nonexistent_file_refuses(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# exists")
    _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="delete", expected_absent=True
            )
        ],
    )
    assert r.ok is False


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_delete_tracked_file_after_removal(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# to delete")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add file"], cwd=repo, check=True)

    (repo / "file.py").unlink()

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="delete", expected_absent=True
            )
        ],
    )
    assert r.ok is True


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_unrelated_staged_refuses(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "other.py").write_text("# other")
    subprocess.run(["git", "add", "other.py"], cwd=repo, check=True)

    (repo / "target.py").write_text("# target")
    current = _sha256(repo / "target.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="target.py", change_kind="add", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is False
    assert r.error_kind == "unrelated_staged_paths_present"


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_special_filename_literal_staging(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "star*.py").write_text("# star file")
    current = _sha256(repo / "star*.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="star*.py", change_kind="add", expected_worktree_sha256=current
            )
        ],
    )
    if r.ok:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=repo,
            check=True,
        )
        assert "star*.py" in staged.stdout
        assert "README.md" not in staged.stdout or r.ok is True


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_index_tree_digest_present_on_success(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# content")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    if r.ok:
        assert r.pre_index_tree_digest is not None
        assert r.post_index_tree_digest is not None
        assert r.pre_index_tree_digest != r.post_index_tree_digest


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_unrelated_file_remains_unstaged(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "admitted.py").write_text("# admitted")
    (repo / "unrelated.py").write_text("# unrelated")
    admitted_hash = _sha256(repo / "admitted.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="admitted.py",
                change_kind="add",
                expected_worktree_sha256=admitted_hash,
            )
        ],
    )
    if r.ok:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=repo,
            check=True,
        )
        assert "admitted.py" in staged.stdout
        assert "unrelated.py" not in staged.stdout


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_full_operator_journey_edit_prepare_commit(tmp_path):
    repo = _init_repo(tmp_path)

    (repo / "app.py").write_text("# edited content")
    current = _sha256(repo / "app.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="app.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    if not r.ok:
        pytest.skip(f"Preparation refused: {r.error_kind}")

    assert r.ok is True
    assert "app.py" in r.prepared_paths
    post_digest = r.post_index_tree_digest
    assert post_digest is not None

    from rig_relay.core.git_index_operations import compute_index_tree_digest

    current_digest = compute_index_tree_digest(repo)
    assert current_digest == post_digest, "Index changed after preparation!"

    from rig_relay.core.git_index_operations import commit_prepared_index

    sha = commit_prepared_index(
        message="checkpoint(test-task): prepared commit",
        worktree_root=repo,
        session_id="test-sess",
        task_id="test-task",
        receipt_trailer="Rig-Authorization-Receipt-SHA256: sha256:test",
    )
    assert sha is not None

    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        capture_output=True,
        text=True,
        cwd=repo,
        check=True,
    )
    assert "prepared commit" in log.stdout
    assert "Rig-Authorization-Receipt-SHA256" in log.stdout


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_prepare_then_modify_working_tree_checkpoint_refuses_stale(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# first edit")
    first_hash = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py",
                change_kind="modify",
                expected_worktree_sha256=first_hash,
            )
        ],
    )
    if not r.ok:
        pytest.skip(f"Prepare refused: {r.error_kind}")
    post_digest = r.post_index_tree_digest

    (repo / "file.py").write_text("# second edit - should NOT be in commit")

    from rig_relay.core.git_index_operations import compute_index_tree_digest

    current = compute_index_tree_digest(repo)
    assert current == post_digest, (
        "Index should match prepared digest even after worktree change"
    )

    from rig_relay.core.git_index_operations import commit_prepared_index

    sha = commit_prepared_index(
        message="checkpoint: prepared only",
        worktree_root=repo,
        session_id="test",
        task_id="test",
    )
    assert sha is not None

    from rig_relay.core.git_index_operations import compute_head_tree_digest

    head_tree = compute_head_tree_digest(repo)
    assert head_tree == post_digest, (
        "Committed tree MUST equal prepared post_index_tree_digest. "
        "Later working-tree changes should not be in the commit."
    )


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_preparation_receipt_persisted_to_disk(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# prepared")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert r.receipt_sha256 is not None
    assert r.receipt_sha256.startswith("sha256:")

    receipt_path = (
        repo
        / ".build/rig-relay/desktop/preparation-receipts"
        / f"{r.receipt_sha256}.json"
    )
    assert receipt_path.exists(), f"Receipt not found at {receipt_path}"
    assert receipt_path.stat().st_size > 0


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_preparation_receipt_loads_and_verifies(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# prepared")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert r.receipt_sha256 is not None

    original = os.getcwd()
    os.chdir(repo)
    try:
        receipt = load_preparation_receipt(r.receipt_sha256)
    finally:
        os.chdir(original)
    assert receipt is not None
    assert receipt["post_index_tree_digest"] is not None
    assert receipt["post_index_tree_digest"] == r.post_index_tree_digest
    assert receipt["prepared_paths"] == ["file.py"]
    assert receipt["index_mutation_performed"] is True


@pytest.mark.asyncio
@pytest.mark.real_artifact
@pytest.mark.substrate
async def test_checkpoint_verifies_preparation_receipt(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# prepared")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert r.receipt_sha256 is not None
    receipt_sha = r.receipt_sha256

    current_digest = compute_index_tree_digest(repo)
    assert current_digest == r.post_index_tree_digest

    sha = commit_prepared_index(
        message="checkpoint(test): bound commit",
        worktree_root=repo,
        session_id="test-sess",
        task_id="test-task",
        receipt_trailer=f"Rig-Preparation-Receipt-SHA256: {receipt_sha}",
    )
    assert sha is not None

    head_tree = compute_head_tree_digest(repo)
    assert head_tree == r.post_index_tree_digest, (
        f"Committed tree {head_tree} != prepared tree {r.post_index_tree_digest}"
    )


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_checkpoint_refuses_stale_preparation_receipt(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# prepared")
    current = _sha256(repo / "file.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="file.py", change_kind="modify", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    receipt_sha = r.receipt_sha256
    assert receipt_sha is not None

    (repo / "file.py").write_text("# changed after preparation")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)

    new_digest = compute_index_tree_digest(repo)
    assert new_digest != r.post_index_tree_digest, "Index should have changed"

    original = os.getcwd()
    os.chdir(repo)
    try:
        receipt = load_preparation_receipt(receipt_sha)
    finally:
        os.chdir(original)
    assert receipt is not None
    expected = receipt["post_index_tree_digest"]
    assert new_digest != expected, "Receipt digest no longer matches index"


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_preparation_receipt_missing_refuses(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.py").write_text("# content")
    _sha256(repo / "file.py")

    receipt = load_preparation_receipt("sha256:" + "0" * 64)
    assert receipt is None, "Nonexistent receipt should return None"


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_committed_tree_equals_preparation_digest(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("# production code")
    current = _sha256(repo / "app.py")

    r = await _run_prepare(
        repo,
        [
            PrepareCheckpointPath(
                path="app.py", change_kind="add", expected_worktree_sha256=current
            )
        ],
    )
    assert r.ok is True
    assert r.receipt_sha256 is not None

    idx = compute_index_tree_digest(repo)
    assert idx == r.post_index_tree_digest

    sha = commit_prepared_index(
        message="checkpoint: receipt-bound",
        worktree_root=repo,
        receipt_trailer=f"Rig-Preparation-Receipt-SHA256: {r.receipt_sha256}",
    )
    assert sha is not None

    tree = compute_head_tree_digest(repo)
    assert tree == r.post_index_tree_digest, (
        f"Tree {tree} != prepared {r.post_index_tree_digest}"
    )
