"""Tests for candidate computation admission — non-mutating SEARCH_REPLACE_PROPOSAL.

Proves that the runtime adapter admits candidate computation through
MUTATION_PROPOSAL mode while keeping MUTATION_EXECUTION fail-closed.
No pending proposal persistence — that is a separate governed action deferred
to Pending Proposal Persistence Admission v1.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)


def _make_git_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'test'\nversion = '0.1.0'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True
    )
    return repo


def _write_and_commit(repo: Path, rel_path: str, content: str) -> None:
    target = repo / rel_path
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel_path], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel_path}"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


@pytest.fixture(autouse=True)
def _reset_dirty_guard() -> None:
    from rig_relay.governance.dirty_guard import reset_guard

    reset_guard()


def _proposal_intent(file_path: str, old_str: str, new_str: str) -> RuntimeToolIntent:
    content = f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"
    return RuntimeToolIntent(
        intent_id="test-proposal-001",
        tool_name=RuntimeToolName.SEARCH_REPLACE_PROPOSAL,
        payload={"file_path": file_path, "content": content},
    )


def _execution_intent(file_path: str, old_str: str, new_str: str) -> RuntimeToolIntent:
    content = f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"
    return RuntimeToolIntent(
        intent_id="test-exec-001",
        tool_name=RuntimeToolName.SEARCH_REPLACE,
        payload={"file_path": file_path, "content": content},
    )


class TestCandidateComputationAdmission:
    """Candidate computation: SEARCH_REPLACE_PROPOSAL computes candidate only.

    The runtime path calls SearchReplace.compute_proposal() which is
    proven non-mutating. No PatchProposal is persisted — that is a
    separate governed action (pending_proposal_creation) deferred to
    Pending Proposal Persistence Admission v1.
    """

    @pytest.mark.asyncio
    async def test_candidate_computation_authorized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEARCH_REPLACE_PROPOSAL computes candidate via compute_proposal()."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original\n")

        intent = _proposal_intent("target.py", "original", "replaced")
        ctx = RuntimeContext(
            session_id="sess-001",
            task_id="task-001",
            worktree_path=str(repo),
            repo_root=str(repo),
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace_proposal(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.receipt_sha256 is not None

    @pytest.mark.asyncio
    async def test_candidate_computation_does_not_mutate_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After candidate computation, target file is unchanged."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "unchanged\n")
        original = (repo / "target.py").read_bytes()

        intent = _proposal_intent("target.py", "unchanged", "modified")
        ctx = RuntimeContext(
            session_id="sess-001",
            task_id="task-001",
            worktree_path=str(repo),
            repo_root=str(repo),
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace_proposal(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert (repo / "target.py").read_bytes() == original

    @pytest.mark.asyncio
    async def test_policy_admits_non_workspace_mutating_category(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEARCH_REPLACE_PROPOSAL is admitted under non-workspace-mutating policy.

        The admission uses _NON_WORKSPACE_MUTATING_PROPOSAL_TOOLS, not a
        generic read-only classification. This is a bounded static admission,
        not the completed Governance Composer.
        """
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        intent = _proposal_intent("target.py", "hello", "world")
        ctx = RuntimeContext(
            session_id="sess-001",
            task_id="task-001",
            worktree_path=str(repo),
            repo_root=str(repo),
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace_proposal(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.refusal_reason is None, (
            f"Candidate computation should be admitted, got: {result.refusal_reason}"
        )


class TestExecutionStillFailClosed:
    """Direct MUTATION_EXECUTION path remains blocked."""

    @pytest.mark.asyncio
    async def test_execution_search_replace_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEARCH_REPLACE (execution) still gets policy_object_missing."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        intent = _execution_intent("target.py", "hello", "world")
        ctx = RuntimeContext(
            session_id="sess-001",
            task_id="task-001",
            worktree_path=str(repo),
            repo_root=str(repo),
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)

        # SEARCH_REPLACE is now allowed by the runtime policy
        assert result.status == RuntimeToolExecutionStatus.COMPLETED


class TestCandidateComputationAdversarial:
    """Candidate computation: malformed input still refuses."""

    @pytest.mark.asyncio
    async def test_candidate_refused_for_missing_file_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing file_path refuses via adapter policy."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        intent = RuntimeToolIntent(
            intent_id="test-001",
            tool_name=RuntimeToolName.SEARCH_REPLACE_PROPOSAL,
            payload={
                "file_path": "",
                "content": "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE",
            },
        )
        ctx = RuntimeContext(
            session_id="sess-001",
            task_id="task-001",
            worktree_path=str(repo),
            repo_root=str(repo),
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace_proposal(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.REFUSED
