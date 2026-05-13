from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import validate
import pytest

from vibe.core.telemetry.artifacts import GitStateArtifact, ToolOutputArtifactWriter
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.tools.base import BaseToolState, ToolPermission
from vibe.core.tools.builtins.git import GitResult, GitStatus, GitToolConfig


@pytest.fixture
def status_tool():
    return GitStatus(
        config_getter=lambda: GitToolConfig(permission=ToolPermission.ALWAYS),
        state=BaseToolState(),
    )


def _fake_result(operation: str, stdout: str = "", stderr: str = "") -> GitResult:
    return GitResult(
        operation=operation,
        argv=["git", operation],
        stdout=stdout,
        stderr=stderr,
        returncode=0,
        truncated_stdout=False,
        truncated_stderr=False,
    )


def _mock_run_git(outputs: dict[tuple[str, tuple[str, ...]], GitResult]):
    async def _run_git(operation: str, args: list[str]) -> GitResult:
        key = (operation, tuple(args))
        return outputs[key]

    return _run_git


def _schema_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.artifact.git_state.v1.schema.json"
    )


def _payload_sha256(payload: dict[str, object]) -> str:
    return f"sha256:{hashlib.sha256(dump_canonical_json(payload).encode('utf-8')).hexdigest()}"


@pytest.mark.asyncio
async def test_git_status_emits_clean_state_artifact(tmp_path, monkeypatch, status_tool):
    monkeypatch.chdir(tmp_path)
    outputs = {
        ("branch", ("--show-current",)): _fake_result("branch", stdout="main\n"),
        ("rev-parse", ("HEAD",)): _fake_result("rev-parse", stdout="abc123\n"),
        (
            "rev-parse",
            ("--abbrev-ref", "--symbolic-full-name", "@{u}"),
        ): _fake_result("rev-parse", stdout="origin/main\n"),
        ("rev-list", ("--left-right", "--count", "HEAD...@{u}")): _fake_result(
            "rev-list", stdout="0\t0\n"
        ),
    }
    monkeypatch.setattr(status_tool, "_run_git", _mock_run_git(outputs))

    payload = await status_tool._build_git_state_payload(
        _fake_result("status", stdout="## main...origin/main\n")
    )
    payload["stdout_sha256"] = status_tool._sha256_text("## main...origin/main\n")
    payload["state_sha256"] = _payload_sha256(payload)

    artifact = GitStateArtifact.model_validate(payload)
    written = ToolOutputArtifactWriter("session-1").write_git_state_artifact(
        artifact=artifact,
        tool_call_id="call-1",
    )
    content = json.loads(Path(written.path).read_text(encoding="utf-8"))
    validate(instance=content["payload"], schema=json.loads(_schema_path().read_text()))
    assert content["artifact_kind"] == "git_state"
    assert content["payload"]["is_dirty"] is False
    assert content["payload"]["dirty_file_count"] == 0
    assert content["payload"]["state_sha256"].startswith("sha256:")


@pytest.mark.asyncio
async def test_git_status_emits_dirty_state_with_deterministic_ordering(
    tmp_path, monkeypatch, status_tool
):
    monkeypatch.chdir(tmp_path)
    outputs = {
        ("branch", ("--show-current",)): _fake_result("branch", stdout="feature\n"),
        ("rev-parse", ("HEAD",)): _fake_result("rev-parse", stdout="deadbeef\n"),
        (
            "rev-parse",
            ("--abbrev-ref", "--symbolic-full-name", "@{u}"),
        ): _fake_result("rev-parse", stdout="origin/feature\n"),
        ("rev-list", ("--left-right", "--count", "HEAD...@{u}")): _fake_result(
            "rev-list", stdout="2\t1\n"
        ),
    }
    monkeypatch.setattr(status_tool, "_run_git", _mock_run_git(outputs))

    status_stdout = (
        "## feature...origin/feature [ahead 2, behind 1]\n"
        " M zeta.py\n"
        "?? alpha.txt\n"
        "A  beta.py\n"
        "UU gamma.py\n"
    )
    payload = await status_tool._build_git_state_payload(
        _fake_result("status", stdout=status_stdout)
    )
    payload["stdout_sha256"] = status_tool._sha256_text(status_stdout)
    expected_state_sha256 = _payload_sha256(payload)
    payload["state_sha256"] = expected_state_sha256

    content = GitStateArtifact.model_validate(payload).model_dump(exclude_none=True)
    dirty_files = content["dirty_files"]
    assert [item["relative_path"] for item in dirty_files] == [
        "alpha.txt",
        "beta.py",
        "gamma.py",
        "zeta.py",
    ]
    assert content["dirty_file_count"] == 4
    assert content["staged_file_count"] == 2
    assert content["unstaged_file_count"] == 2
    assert content["untracked_file_count"] == 1
    assert content["conflict_file_count"] == 1
    assert content["upstream_branch"] == "origin/feature"
    assert content["upstream_ahead_count"] == 2
    assert content["upstream_behind_count"] == 1
    assert content["is_dirty"] is True

    assert content["state_sha256"] == expected_state_sha256


def test_git_state_artifact_schema_validates_minimal_example():
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    instance = GitStateArtifact(
        repo_root=".",
        dirty_files=[],
        state_sha256="sha256:" + "a" * 64,
    ).model_dump(exclude_none=True)
    validate(instance=instance, schema=schema)
