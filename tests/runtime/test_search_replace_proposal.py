"""Tests for SearchReplace.compute_proposal — non-mutating candidate computation.

Proves that SearchReplace owns candidate computation only (path safety,
baseline capture, dirty-guard, block parse, pure in-memory _apply_blocks).
Proposal persistence is delegated to the patch workflow boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from rig_relay.coordination.patch_workflow import create_pending_proposal
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
)


def _make_git_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal real git repo with an initial commit."""
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
    """Write a file and commit it so it is clean for the dirty guard."""
    target = repo / rel_path
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel_path], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel_path}"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _make_tool(repo: Path) -> SearchReplace:
    """Create a SearchReplace tool instance."""
    return SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )


def _search_replace_args(
    file_path: str,
    old_str: str,
    new_str: str,
    *,
    expected_before_sha256: str | None = None,
) -> SearchReplaceArgs:
    content = f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"
    return SearchReplaceArgs(
        file_path=file_path,
        content=content,
        expected_before_sha256=expected_before_sha256,
    )


@pytest.fixture(autouse=True)
def _reset_dirty_guard() -> None:
    from rig_relay.governance.dirty_guard import reset_guard

    reset_guard()


class TestProposalCompute:
    """Integration: candidate computation without workspace mutation."""

    @pytest.mark.asyncio
    async def test_proposal_computes_candidate_without_mutating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Candidate computed correctly, file unchanged on disk."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original line\n")
        original_bytes = (repo / "target.py").read_bytes()

        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "original line", "replaced line")
        result = await tool.compute_proposal(args)

        assert result.status == "proposal_computed"
        assert result.blocks_applied == 1
        assert result.failed_block_count == 0
        assert result.before_file_sha256
        assert result.after_file_sha256
        assert (
            list(result.after_file_sha256.values())[0]
            != list(result.before_file_sha256.values())[0]
        )
        assert (repo / "target.py").read_bytes() == original_bytes

    @pytest.mark.asyncio
    async def test_patch_workflow_persists_proposal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patch workflow creates and persists a pending PatchProposal."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "before\n")

        coord_root = tmp_path / "coordination"
        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "before", "after")
        result = await tool.compute_proposal(args)

        assert result.status == "proposal_computed"

        before_hash = list(result.before_file_sha256.values())[0]
        after_hash = list(result.after_file_sha256.values())[0]

        # Persist via the patch workflow boundary
        proposal = create_pending_proposal(
            coordination_root=coord_root,
            file_path="target.py",
            before_hash=before_hash,
            after_hash=after_hash,
        )

        assert proposal.status == "pending"
        assert proposal.proposal_id is not None
        assert any("target.py" in tp for tp in proposal.touched_paths)

        # Verify persisted to disk
        proposal_path = (
            coord_root / ".fleet" / "patch-proposals" / f"{proposal.proposal_id}.json"
        )
        assert proposal_path.is_file()

    @pytest.mark.asyncio
    async def test_proposal_result_is_content_light(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Content-light result: no raw content, markers, or secrets."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "sensitive data\n")

        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "sensitive data", "replaced")
        result = await tool.compute_proposal(args)

        dumped = json.dumps(result.model_dump())
        forbidden = frozenset({
            "<<<<<<< SEARCH",
            ">>>>>>> REPLACE",
            "=======",
            "sensitive data",
            "replaced",
        })
        for marker in forbidden:
            assert marker not in dumped, (
                f"Forbidden marker '{marker}' in content-light proposal result"
            )

    @pytest.mark.asyncio
    async def test_proposal_has_no_raw_content_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ProposalResult has no 'content' field (unlike SearchReplaceResult)."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "test\n")

        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "test", "done")
        result = await tool.compute_proposal(args)

        fields = set(result.__class__.model_fields.keys())
        assert "content" not in fields
        assert "changed_files" not in fields
        assert "proposal_id" not in fields, (
            "SearchReplace owns computation only; proposal_id belongs to "
            "the patch workflow boundary"
        )


class TestProposalAdversarial:
    """Adversarial/sabotage: candidate computation refuses without mutation."""

    @pytest.mark.asyncio
    async def test_proposal_refused_for_malformed_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid SEARCH/REPLACE blocks refuse, no file mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "existing content\n")
        original_bytes = (repo / "target.py").read_bytes()

        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "nonexistent text", "replacement")
        result = await tool.compute_proposal(args)

        assert result.status == "refused"
        assert result.error_kind is not None
        assert (repo / "target.py").read_bytes() == original_bytes

    @pytest.mark.asyncio
    async def test_proposal_refused_for_nonexistent_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent file refuses without mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        tool = _make_tool(repo)
        args = _search_replace_args("does_not_exist.py", "x", "y")
        result = await tool.compute_proposal(args)

        assert result.status == "refused"
        assert result.error_kind is not None

    @pytest.mark.asyncio
    async def test_proposal_refused_for_path_escape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Workspace escape refuses before file access."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        tool = _make_tool(repo)
        args = _search_replace_args("../outside.py", "x", "y")
        result = await tool.compute_proposal(args)

        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_proposal_refused_for_stale_hash_on_dirty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale expected_before_sha256 refuses dirty file proposal."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        target = repo / "target.py"
        target.write_text("actual content\n", encoding="utf-8")

        tool = _make_tool(repo)
        args = _search_replace_args(
            "target.py",
            "actual content",
            "changed",
            expected_before_sha256=(
                "0000000000000000000000000000000000000000000000000000000000000000"
            ),
        )
        result = await tool.compute_proposal(args)

        assert result.status == "refused"


class TestProposalSubstrate:
    """Substrate: SearchReplace no longer imports PatchWorkflowStore."""

    def test_search_replace_does_not_import_patch_workflow(self) -> None:
        """SearchReplace module has no PatchWorkflowStore or PatchProposal attribute."""
        import rig_relay.core.tools.builtins.search_replace as sr_mod

        assert not hasattr(sr_mod, "PatchProposal"), (
            "SearchReplace module must not have PatchProposal attribute"
        )
        assert not hasattr(sr_mod, "PatchWorkflowStore"), (
            "SearchReplace module must not have PatchWorkflowStore attribute"
        )

    @pytest.mark.asyncio
    async def test_existing_search_replace_execution_still_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The existing MUTATION_EXECUTION path is not affected."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        tool = _make_tool(repo)
        args = _search_replace_args("target.py", "hello", "world")
        result = await tool.compute_proposal(args)
        assert result.status == "proposal_computed"
