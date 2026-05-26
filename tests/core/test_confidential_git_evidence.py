"""Lane B4 — Git evidence confidentiality, revision admission, and adversarial tests."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from pydantic import BaseModel
import pytest

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)
from rig_relay.core.tools._agent_outcome import (
    derive_agent_outcome,
    format_agent_outcome,
)
from rig_relay.core.tools.base import BaseToolState, ToolError
from rig_relay.core.tools.builtins.git import (
    GitBranch,
    GitBranchArgs,
    GitDiff,
    GitDiffArgs,
    GitLog,
    GitLogArgs,
    GitLsFiles,
    GitLsFilesArgs,
    GitShow,
    GitShowArgs,
    GitStatus,
    GitStatusArgs,
    GitToolConfig,
    _GitEvidenceModel,
)
from tests.mock.utils import collect_result

_SENTINEL_PATH = "client_acme_corp_secrets_config.yaml"
_SENTINEL_BRANCH = "feature/ticket-12345-acme-payment-flow"
_SENTINEL_SUBJECT = "Fix critical auth bypass in admin portal"
_SENTINEL_UPSTREAM = "origin/customer-prod-deploy"
_SENTINEL_LEADING_DASH = "--force"


# ── Helpers ───────────────────────────────────────────────────────────


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def _commit(repo: Path, msg: str = "init") -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "--allow-empty",
            "-m",
            msg,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _runtime(**overrides: Any) -> ToolRuntime:
    from collections.abc import AsyncGenerator

    async def _always_allow(tool_name, args_dict, call_id):
        return True, ""

    async def _invoke_default(args_dict: dict[str, Any]) -> AsyncGenerator[Any, None]:
        class Dummy(BaseModel):
            x: int = 0

        yield Dummy()

    kwargs: dict[str, Any] = dict(
        invoke_tool=_invoke_default,
        cache_check=lambda t, a: (False, None),
        cache_store=lambda t, a, r: None,
        permission_decision=_always_allow,
        approval_request=_always_allow,
        patch_gate_check=lambda tc, ti: None,
        expand_args=lambda a: a,
        receipt_build=lambda tn, rm: None,
        receipt_capture=lambda s, tn, r: None,
        context_observe=lambda *a, **kw: None,
        stats_delta=lambda k, d: None,
    )
    kwargs.update(overrides)
    return ToolRuntime(**kwargs)


def _text_of(outcome) -> str:
    """Extract the model-visible text from a formatted agent outcome."""
    return format_agent_outcome(outcome)


# ── Redacted projection: model-visible text is safe ───────────────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_status_hides_raw_branch(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    subprocess.run(
        ["git", "branch", _SENTINEL_BRANCH], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "checkout", _SENTINEL_BRANCH], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitStatus(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitStatusArgs()
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_BRANCH not in str(projection)
    assert "branch_available" in projection
    assert projection["branch_available"] is True


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_status_hides_raw_paths(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    (repo / _SENTINEL_PATH).write_text("api_key = sk-deadbeef")
    subprocess.run(
        ["git", "add", _SENTINEL_PATH], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitStatus(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitStatusArgs()
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_PATH not in str(projection)
    assert "changed_paths_count" in projection
    assert projection["changed_paths_count"] >= 1
    assert "changed_paths" not in projection
    assert "evidence_digest" in projection


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_diff_hides_paths(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    (repo / _SENTINEL_PATH).write_text("changed")
    subprocess.run(
        ["git", "add", _SENTINEL_PATH], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitDiff(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitDiffArgs(cached=True)
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_PATH not in str(projection)
    assert "files_changed_count" in projection
    assert "evidence_digest" in projection


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_log_hides_subject(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo, _SENTINEL_SUBJECT)
    monkeypatch.chdir(repo)

    result = await collect_result(
        GitLog(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitLogArgs(max_count=1)
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_SUBJECT not in str(projection)
    assert "commits_returned" in projection
    assert projection["commits_returned"] >= 1


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_branch_hides_names(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    subprocess.run(
        ["git", "branch", _SENTINEL_BRANCH], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitBranch(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitBranchArgs(show_current=False)
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_BRANCH not in str(projection)
    assert "branches_count" in projection
    assert projection["branches_count"] >= 2


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_show_hides_subject(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo, _SENTINEL_SUBJECT)
    monkeypatch.chdir(repo)

    result = await collect_result(
        GitShow(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitShowArgs(ref="HEAD")
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_SUBJECT not in str(projection)
    assert "commit_sha" in projection
    assert "subject_available" in projection


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_redacted_ls_files_hides_paths(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    (repo / _SENTINEL_PATH).write_text("tracked")
    subprocess.run(
        ["git", "add", _SENTINEL_PATH], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitLsFiles(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitLsFilesArgs()
        )
    )
    projection = result.redacted_projection()
    assert _SENTINEL_PATH not in str(projection)
    assert "paths_returned" in projection


# ── Model-visible text does not leak through executor ──────────────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_executor_uses_redacted_projection(tmp_path, monkeypatch):

    repo = _repo(tmp_path)
    _commit(repo, _SENTINEL_SUBJECT)
    monkeypatch.chdir(repo)

    tool = GitLog(config_getter=GitToolConfig, state=BaseToolState())
    log_result = await collect_result(tool.run(GitLogArgs(max_count=1)))

    async def _invoke_redact(args_dict):
        yield log_result

    runtime = _runtime(invoke_tool=_invoke_redact)
    result = await runtime.execute_one(
        ToolRuntimeRequest(
            tool_name="git_log",
            tool_args={},
            tool_call_id="call_redact",
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        )
    )
    assert result.provider_tool_response is not None
    projection = result.provider_tool_response.redacted_projection()
    text_block = "\n".join(f"{k}: {v}" for k, v in projection.items())
    assert _SENTINEL_SUBJECT not in text_block
    assert "commits_returned" in text_block


# ── Revision admission ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_git_show_rejects_dash_ref(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    tool = GitShow(config_getter=GitToolConfig, state=BaseToolState())
    with pytest.raises(ToolError, match="Ref cannot start with"):
        await collect_result(tool.run(GitShowArgs(ref="--force")))


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_git_show_rejects_option_ref(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    tool = GitShow(config_getter=GitToolConfig, state=BaseToolState())
    with pytest.raises(ToolError, match="Ref cannot start"):
        await collect_result(tool.run(GitShowArgs(ref="-n")))


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_git_show_rejects_nonexistent_ref(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    tool = GitShow(config_getter=GitToolConfig, state=BaseToolState())
    with pytest.raises(ToolError, match="not a valid commit"):
        await collect_result(tool.run(GitShowArgs(ref="deadbeef1234")))


# ── Pathspec admission ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_rejects_leading_dash_in_path():
    tool = GitDiff(config_getter=GitToolConfig, state=BaseToolState())
    with pytest.raises(ToolError, match="Path spec cannot start with '-'"):
        await collect_result(tool.run(GitDiffArgs(paths=["-o"])))


# ── Sentinel filename adversarial ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_filename_with_spaces_redacted(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    space_path = repo / "src/my secret file with spaces.py"
    space_path.parent.mkdir(parents=True, exist_ok=True)
    space_path.write_text("x")
    subprocess.run(
        ["git", "add", str(space_path)], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitStatus(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitStatusArgs()
        )
    )
    projection = result.redacted_projection()
    assert "my secret" not in str(projection)
    assert "spaces" not in str(projection)


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_filename_with_leading_dash_redacted(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo)
    monkeypatch.chdir(repo)
    dash_path = repo / "--force"
    dash_path.write_text("x")
    subprocess.run(
        ["git", "add", "--", str(dash_path)], cwd=repo, check=True, capture_output=True
    )

    result = await collect_result(
        GitStatus(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitStatusArgs()
        )
    )
    projection = result.redacted_projection()
    assert "--force" not in str(projection)


# ── Evidence digest is deterministic ──────────────────────────────────


def test_evidence_digest_deterministic():
    from rig_relay.core.tools.builtins.git import GitStatusResult

    r1 = GitStatusResult(branch="main", head_sha="abc", staged_count=1)
    r2 = GitStatusResult(branch="main", head_sha="abc", staged_count=1)
    assert r1._evidence_digest() == r2._evidence_digest()


def test_evidence_digest_changes_with_content():
    from rig_relay.core.tools.builtins.git import GitStatusResult

    r1 = GitStatusResult(branch="main", staged_count=1)
    r2 = GitStatusResult(branch="main", staged_count=2)
    assert r1._evidence_digest() != r2._evidence_digest()


# ── Redacted projection does not leak through agent outcome ───────────


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_agent_outcome_hides_redacted_fields(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _commit(repo, _SENTINEL_SUBJECT)
    monkeypatch.chdir(repo)

    log_result_ao = await collect_result(
        GitLog(config_getter=GitToolConfig, state=BaseToolState()).run(
            GitLogArgs(max_count=1)
        )
    )

    async def _invoke_ao(args_dict):
        yield log_result_ao

    runtime = _runtime(invoke_tool=_invoke_ao)
    result = await runtime.execute_one(
        ToolRuntimeRequest(
            tool_name="git_log",
            tool_args={},
            tool_call_id="call_ao",
            execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
        )
    )
    outcome = derive_agent_outcome(result, ToolMutationClass.READ_ONLY)
    formatted = format_agent_outcome(outcome)
    assert _SENTINEL_SUBJECT not in formatted
    assert result.git_summary is not None or result.investigation_outcome is not None


# ── _GitEvidenceModel interface ───────────────────────────────────────


def test_git_evidence_model_raises_not_implemented():
    class Bad(_GitEvidenceModel):
        pass

    b = Bad()
    with pytest.raises(NotImplementedError):
        b.redacted_projection()
