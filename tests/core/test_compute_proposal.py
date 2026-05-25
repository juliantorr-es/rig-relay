"""Tests for compute_proposal — non-mutating search-replace proposal generation.

Tests prove: candidate computed in memory, PatchProposal persisted via
PatchWorkflowStore, workspace unchanged, content-light proposal results.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import PatchWorkflowStore
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
    SearchReplaceProposalResult,
)


def _init_repo(tmp_path: Path) -> Path:
    import subprocess

    (tmp_path / "src").mkdir()
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True
    )
    return tmp_path


def _make_tool() -> SearchReplace:
    return SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )


def _write_file(repo: Path, path: str, content: str) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _compute_result(
    tool: SearchReplace, file_path: str, search: str, replace: str
) -> SearchReplaceProposalResult:
    import asyncio

    args = SearchReplaceArgs(
        file_path=file_path,
        content=f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE",
    )
    return asyncio.run(tool.compute_proposal(args))


def _persist_proposal(
    result: SearchReplaceProposalResult, coordination_root: Path
) -> PatchProposal:
    """Persist proposal from compute result via canonical PatchWorkflowStore."""
    import uuid

    store = PatchWorkflowStore(coordination_root)
    pid = f"prop-{uuid.uuid4().hex[:12]}"

    file_path = result.file
    before_hash = (
        list(result.before_file_sha256.values())[0]
        if result.before_file_sha256
        else "sha256:0000"
    )
    after_hash = (
        list(result.after_file_sha256.values())[0]
        if result.after_file_sha256
        else "sha256:0000"
    )

    proposal = PatchProposal(
        proposal_id=pid,
        mission_id="test-mission",
        agent_id="test-agent",
        title="test proposal",
        summary="test summary",
        status="pending",
        touched_paths=[file_path],
        touched_path_hashes=[before_hash],
        expected_before_sha256={file_path: before_hash},
        candidate_after_sha256={file_path: after_hash},
    )
    store.save_proposal(proposal)
    return proposal


# ---- Core proposal tests ----------------------------------------------


def test_integration_proposal_computes_without_workspace_mutation(
    tmp_path, monkeypatch
):
    """Classification: integration/real-artifact
    A valid search/replace proposal computes the intended candidate and
    does NOT mutate the active workspace file.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    _write_file(repo, "src/app.py", "hello world\ngoodbye moon\n")
    original_bytes = (repo / "src/app.py").read_bytes()
    tool = _make_tool()
    result = _compute_result(tool, "src/app.py", "goodbye moon", "hello sun")
    assert result.status == "proposal_computed"
    assert result.blocks_applied == 1
    assert (repo / "src/app.py").read_bytes() == original_bytes
    first_before = list(result.before_file_sha256.values())[0]
    first_after = list(result.after_file_sha256.values())[0]
    assert first_before != first_after


def test_real_artifact_proposal_persists_pending_patch_proposal(tmp_path, monkeypatch):
    """Classification: integration/real-artifact
    A computed proposal persists a pending PatchProposal through
    PatchWorkflowStore, and the persisted proposal can be read back.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    _write_file(repo, "src/app.py", "x = 1\ny = 2\n")
    coordination_root = tmp_path / "coordination"
    tool = _make_tool()
    result = _compute_result(tool, "src/app.py", "y = 2", "y = 3")
    assert result.status == "proposal_computed"

    proposal = _persist_proposal(result, coordination_root)
    store = PatchWorkflowStore(coordination_root)
    loaded = store.load_proposal(proposal.proposal_id)
    assert loaded.status == "pending"
    assert len(loaded.candidate_after_sha256) > 0


def test_adversarial_malformed_blocks_refuse_without_mutation(tmp_path, monkeypatch):
    """Classification: contract/sabotage
    Malformed SEARCH/REPLACE blocks refuse proposal generation without
    mutating the workspace.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    _write_file(repo, "src/app.py", "hello\n")
    original_bytes = (repo / "src/app.py").read_bytes()
    tool = _make_tool()
    result = _compute_result(tool, "src/app.py", "nonexistent", "replacement")
    assert result.status == "refused"
    assert result.blocks_applied == 0
    assert (repo / "src/app.py").read_bytes() == original_bytes


def test_adversarial_nonexistent_file_refuses_without_mutation(tmp_path, monkeypatch):
    """Classification: contract/sabotage
    A nonexistent target file refuses proposal generation without
    mutating the workspace.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    tool = _make_tool()
    result = _compute_result(tool, "src/nope.py", "a", "b")
    assert result.status == "refused"
    assert "baseline_capture_failed" in (result.error_kind or "")


def test_contract_proposal_content_light_no_raw_content(tmp_path, monkeypatch):
    """Classification: contract/adversarial
    Content-light proposal evidence does NOT contain raw source,
    replacement content, SEARCH/REPLACE blocks, raw diff/patch body,
    prompts, or secrets.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    _write_file(repo, "src/app.py", "x = 1\n")
    tool = _make_tool()
    result = _compute_result(tool, "src/app.py", "x = 1", "x = 2")
    raw = json.dumps(result.model_dump())
    assert "x = 1" not in raw
    assert "x = 2" not in raw
    assert "SEARCH" not in raw
    assert "REPLACE" not in raw
    assert "secret" not in raw.lower()


def test_contract_proposal_workspace_unchanged_byte_for_byte(tmp_path, monkeypatch):
    """Classification: contract/integration
    After a valid proposal computation, the workspace file is byte-for-
    byte unchanged.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    content = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    _write_file(repo, "src/lib.py", content)
    original = hashlib.sha256(content.encode()).hexdigest()
    tool = _make_tool()
    _compute_result(tool, "src/lib.py", "return 1", "return 42")
    final_hash = hashlib.sha256((repo / "src/lib.py").read_text().encode()).hexdigest()
    assert final_hash == original


def test_integration_patch_workflow_reads_back_pending_proposal(tmp_path, monkeypatch):
    """Classification: contract/integration
    A persisted pending proposal can be read back from PatchWorkflowStore
    and validates against the PatchProposal schema.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    _write_file(repo, "src/main.py", "print('hello')\n")
    coordination_root = tmp_path / "wf"
    tool = _make_tool()
    result = _compute_result(tool, "src/main.py", "hello", "world")
    proposal = _persist_proposal(result, coordination_root)
    store = PatchWorkflowStore(coordination_root)
    loaded = store.load_proposal(proposal.proposal_id)
    PatchProposal.model_validate(loaded.model_dump())
    assert loaded.status == "pending"
    assert loaded.proposal_id == proposal.proposal_id
    assert loaded.title == proposal.title
