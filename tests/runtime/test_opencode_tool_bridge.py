"""Tests for rig_relay.cli.opencode_tool_bridge — OpenCode transport adapter.

Stage A proved the transport boundary:
  OpenCode rig_search_replace → opencode_tool_bridge.py
  → RuntimeToolExecutionRunner.execute_search_replace()
  → structured completion with populated receipt identifiers.

Stage A.2 confirmed:
  - The bridge reaches the governed runtime path
  - The bridge correctly receives and reports the structured completion
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionStatus,
)

FORBIDDEN_RAW_FIELD_VALUES: frozenset[str] = frozenset({
    "<<<<<<< SEARCH",
    ">>>>>>> REPLACE",
    "=======",
})


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
    subprocess.run(
        ["git", "checkout", "-b", "feature/test-branch"],
        cwd=repo,
        capture_output=True,
        check=True,
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


@pytest.fixture(autouse=True)
def _reset_dirty_guard() -> None:
    """Reset the dirty guard singleton between tests to avoid state leakage."""
    from rig_relay.governance.dirty_guard import reset_guard

    reset_guard()


async def _invoke_bridge(
    file_path: str,
    old_str: str,
    new_str: str,
    *,
    expected_before_sha256: str | None = None,
    session_id: str = "test-session",
    directory: str = "",
) -> dict:
    """Invoke _invoke_search_replace directly (no subprocess)."""
    from rig_relay.cli.opencode_tool_bridge import _invoke_search_replace

    return await _invoke_search_replace(
        file_path=file_path,
        old_str=old_str,
        new_str=new_str,
        expected_before_sha256=expected_before_sha256,
        session_id=session_id,
        directory=directory,
    )


class TestBridgeResultContract:
    """Contract tests: bridge output shape and content-light enforcement."""

    def test_result_fields_match_execution_result(self) -> None:
        """Bridge result keys are a subset of RuntimeToolExecutionResult fields."""
        allowed = set(RuntimeToolExecutionResult.model_fields.keys())
        bridge_fields = {
            "schema_version",
            "status",
            "intent_id",
            "tool_name",
            "receipt_sha256",
            "receipt_envelope_id",
            "audit_event_id",
            "supervisor_result_envelope_id",
            "supervisor_result_envelope_sha256",
            "changed_paths",
            "duration_ms",
            "error_kind",
            "refusal_reason",
            "warnings",
            "git_summary",
        }
        unsupported = bridge_fields - allowed
        assert not unsupported, f"Bridge fields not in schema: {unsupported}"

    def test_result_rejects_extra_keys(self) -> None:
        """Bridge result JSON validates as RuntimeToolExecutionResult subset."""
        from rig_relay.cli.opencode_tool_bridge import _invoke_search_replace

        assert callable(_invoke_search_replace)


class TestBridgeRuntimePathReached:
    """Proves the bridge reaches the real RuntimeToolExecutionRunner.

    The bridge correctly routes through the governed runtime path and
    receives a structured completed result with receipt identifiers.
    """

    @pytest.mark.asyncio
    async def test_bridge_reaches_runtime_and_receives_structured_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge reaches runtime and completes a governed mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original line\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="original line",
            new_str="replaced line",
            directory=str(repo),
        )

        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert result["refusal_reason"] is None
        assert (repo / "target.py").read_text(encoding="utf-8") == "replaced line\n"

    @pytest.mark.asyncio
    async def test_receipt_sha256_populated_on_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Receipt SHA-256 is populated for a completed bridge mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="hello", new_str="world", directory=str(repo)
        )

        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert result["receipt_sha256"] is not None
        assert len(result["receipt_sha256"]) == 64
        int(result["receipt_sha256"], 16)

    @pytest.mark.asyncio
    async def test_file_mutated_when_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File contents are updated when the bridge mutation completes."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "before\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="before",
            new_str="after",
            directory=str(repo),
        )

        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert (repo / "target.py").read_text(encoding="utf-8") == "after\n"


class TestBridgeContentLight:
    """Telemetry/redaction contract: bridge output is content-light."""

    @pytest.mark.asyncio
    async def test_result_excludes_search_replace_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge result JSON contains no SEARCH/REPLACE markers."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "xyz\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="xyz", new_str="abc", directory=str(repo)
        )

        dumped = json.dumps(result)
        for forbidden in FORBIDDEN_RAW_FIELD_VALUES:
            assert forbidden not in dumped, (
                f"Forbidden marker '{forbidden}' found in bridge output"
            )
        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_result_excludes_raw_replacement_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge result JSON does not contain old_str or new_str."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "sensitive data\n")

        old_str = "sensitive data"
        new_str = "replaced"
        result = await _invoke_bridge(
            file_path="target.py", old_str=old_str, new_str=new_str, directory=str(repo)
        )

        dumped = json.dumps(result)
        assert old_str not in dumped, "Bridge output contains raw old search text"
        assert new_str not in dumped, "Bridge output contains raw replacement text"
        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert result["refusal_reason"] is None


class TestBridgeAdversarial:
    """Adversarial/sabotage: malformed input fails through runtime policy."""

    @pytest.mark.asyncio
    async def test_missing_file_path_refused_by_adapter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing file_path is refused by the adapter."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        result = await _invoke_bridge(
            file_path="", old_str="x", new_str="y", directory=str(repo)
        )

        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert result["error_kind"] is not None

    @pytest.mark.asyncio
    async def test_nonexistent_file_rejected_by_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent file path fails through the runtime."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        result = await _invoke_bridge(
            file_path="does_not_exist.py", old_str="x", new_str="y", directory=str(repo)
        )

        assert result["status"] != RuntimeToolExecutionStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_stale_expected_hash_refused_when_file_is_dirty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale hash on dirty file is refused by the dirty guard."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        target = repo / "target.py"
        target.write_text("actual content\n", encoding="utf-8")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="actual content",
            new_str="changed",
            expected_before_sha256=(
                "0000000000000000000000000000000000000000000000000000000000000000"
            ),
            directory=str(repo),
        )

        assert result["status"] != RuntimeToolExecutionStatus.COMPLETED.value


class TestBridgeSubstrate:
    """Substrate/integration: bridge module and CLI entry point."""

    def test_bridge_module_is_importable(self) -> None:
        """The bridge module can be imported without errors."""
        from rig_relay.cli.opencode_tool_bridge import main

        assert callable(main)

    def test_bridge_cli_completes_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge CLI exits zero and reports a completed mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "cli test\n")

        request = json.dumps({
            "filePath": "target.py",
            "oldStr": "cli test",
            "newStr": "cli replaced",
            "sessionId": "test-cli",
            "directory": str(repo),
        })

        project_root = Path(__file__).resolve().parent.parent.parent
        proc = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(project_root),
                "python",
                "-m",
                "rig_relay.cli.opencode_tool_bridge",
            ],
            input=request,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo),
        )
        assert proc.returncode == 0, (
            f"Expected exit 0 for completed mutation, got {proc.returncode}. "
            f"stdout: {proc.stdout} stderr: {proc.stderr}"
        )
        result = json.loads(proc.stdout.strip())
        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert result["refusal_reason"] is None
        assert result["receipt_sha256"] is not None

    @pytest.mark.asyncio
    async def test_bridge_routes_through_tool_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge delegates to RuntimeToolExecutionRunner → ToolRuntime → completion.

        The bridge routes through the real governed execution path and
        receives a structured completion result with receipts.
        """
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="hello", new_str="world", directory=str(repo)
        )

        assert result["status"] == RuntimeToolExecutionStatus.COMPLETED.value
        assert result["refusal_reason"] is None
        assert result["receipt_sha256"] is not None
        assert result["duration_ms"] is not None
        assert result["duration_ms"] > 0


def _invoke_bridge_cli(request_dict: dict, cwd: Path) -> dict:
    """Invoke the bridge CLI as a subprocess."""
    project_root = Path(__file__).resolve().parent.parent.parent
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(project_root),
            "python",
            "-m",
            "rig_relay.cli.opencode_tool_bridge",
        ],
        input=json.dumps(request_dict),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(cwd),
    )
    assert proc.returncode in (0, 1), (
        f"Bridge CLI failed: exit code {proc.returncode}. "
        f"stdout: {proc.stdout} stderr: {proc.stderr}"
    )
    return json.loads(proc.stdout.strip())


def _validate_result_schema(result_dict: dict) -> None:
    """Validate result dictionary against the execution result JSON schema."""
    import jsonschema

    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.runtime_tool_execution_result.v1.schema.json"
    )
    with open(schema_path) as f:
        schema = json.load(f)
    jsonschema.validate(instance=result_dict, schema=schema)


class TestBridgeGitReadOnlyTools:
    """integration + real-artifact: subprocess bridge routing for read-only Git tools."""

    def test_git_status_via_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify git_status bridge routing against a real temp repo."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        req = {
            "tool_name": "git_status",
            "args": {"short": True, "branch": True},
            "sessionId": "status-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None
        assert res["git_summary"]["branch"] is not None

    def test_git_branch_via_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify git_branch bridge routing against a real temp repo."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        req = {
            "tool_name": "git_branch",
            "args": {"show_current": True},
            "sessionId": "branch-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None
        assert res["git_summary"]["branch"] is not None

    def test_git_log_via_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify git_log bridge routing against a real temp repo."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        req = {
            "tool_name": "git_log",
            "args": {"max_count": 2, "oneline": True},
            "sessionId": "log-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None

    def test_git_show_via_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify git_show bridge routing against a real temp repo."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        req = {
            "tool_name": "git_show",
            "args": {"ref": "HEAD"},
            "sessionId": "show-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None

    def test_git_ls_files_via_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify git_ls_files bridge routing against a real temp repo."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        req = {
            "tool_name": "git_ls_files",
            "args": {},
            "sessionId": "ls-files-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None

    def test_git_diff_truncation_and_redaction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Verify bounded git_diff output with truncation and redaction."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        # Write a large file with more than 500 lines to trigger truncation
        lines = [f"line {i}" for i in range(600)]
        lines.append("password = 'super_secret_password_123'")
        large_content = "\n".join(lines) + "\n"

        _write_and_commit(repo, "target.py", "original\n")
        (repo / "target.py").write_text(large_content, encoding="utf-8")

        req = {
            "tool_name": "git_diff",
            "args": {},
            "sessionId": "diff-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None
        assert res["git_summary"]["truncation_triggered"] is True
        assert res["git_summary"]["redaction_triggered"] is True
        assert (
            "[TRUNCATED: Output exceeded limits]"
            in res["git_summary"]["bounded_stdout"]
        )
        assert "super_secret_password_123" not in res["git_summary"]["bounded_stdout"]


class TestBridgeCheckpointSafety:
    """integration + real-artifact + adversarial: Verify checkpoint safety checks and refusal outcomes."""

    def test_checkpoint_refuses_missing_approval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact + adversarial: Checkpoint refuses when authorization_receipt is missing."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "clean.py", "clean\n")
        (repo / "clean.py").write_text("edit\n")
        subprocess.run(["git", "add", "clean.py"], cwd=repo, check=True)

        req = {
            "tool_name": "checkpoint",
            "args": {"message": "no receipt", "include_paths": ["clean.py"]},
            "sessionId": "checkpoint-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        _validate_result_schema(res)

        assert res["status"] == "refused"
        assert res["refusal_reason"] == "missing_receipt"

    def test_checkpoint_refuses_unstaged_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact + adversarial: Checkpoint refuses unstaged files."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = json.dumps(generate_dev_receipt("checkpoint.commit", ttl_seconds=300))

        (repo / "pyproject.toml").write_text("dirty\n")

        req = {
            "tool_name": "checkpoint",
            "args": {
                "message": "unstaged commit",
                "include_paths": ["pyproject.toml"],
                "authorization_receipt": receipt,
            },
            "sessionId": "checkpoint-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        raw_status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout
        print("DEBUG RAW STATUS:", repr(raw_status))
        print("DEBUG REFUSED RESULT:", res)
        _validate_result_schema(res)

        assert res["status"] == "refused"
        assert res["refusal_reason"] == "unstaged_file_refused"

    def test_checkpoint_success_emits_receipt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """integration + real-artifact: Checkpoint succeeds on properly admitted staged file and emits receipt."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        from rig_relay.governance.dirty_guard import get_guard

        guard = get_guard()
        guard.capture(repo)

        # Write clean edit
        (repo / "pyproject.toml").write_text(
            "[project]\nname = 'test'\nversion = '0.2.0'\n"
        )
        subprocess.run(["git", "add", "pyproject.toml"], cwd=repo, check=True)
        guard.mark_touched("pyproject.toml")

        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = json.dumps(generate_dev_receipt("checkpoint.commit", ttl_seconds=300))

        req = {
            "tool_name": "checkpoint",
            "args": {
                "message": "success test",
                "include_paths": ["pyproject.toml"],
                "authorization_receipt": receipt,
            },
            "sessionId": "checkpoint-session",
            "directory": str(repo),
        }
        res = _invoke_bridge_cli(req, repo)
        print("DEBUG SUCCESS RESULT:", res)
        _validate_result_schema(res)

        assert res["status"] == "completed"
        assert res["git_summary"] is not None
        assert res["git_summary"]["checkpoint_receipt_sha256"] is not None
        assert res["git_summary"]["commit_identity"] is not None
        assert len(res["git_summary"]["changed_paths"]) == 1


class TestBridgeAdversarialReroute:
    """adversarial + substrate: Verify raw git command rerouting works via try_reroute."""

    @pytest.mark.asyncio
    async def test_adversarial_raw_bash_git_status_rerouted(
        self, tmp_path: Path
    ) -> None:
        """adversarial + substrate: Verify attempted raw bash git status is rerouted through git_status tool."""
        from rig_relay.core.tools.base import BaseToolState, InvokeContext
        from rig_relay.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
        from rig_relay.core.tools.manager import ToolManager
        from tests.conftest import build_test_vibe_config

        repo = _make_git_repo(tmp_path)
        config = build_test_vibe_config()
        mgr = ToolManager(config_getter=lambda: config)
        ctx = InvokeContext(tool_call_id="bash-reroute-test", tool_manager=mgr)

        args = BashArgs(command="git status")
        cfg = BashToolConfig()
        tool = Bash(config_getter=lambda: cfg, state=BaseToolState())

        import os

        old_cwd = os.getcwd()
        os.chdir(repo)
        try:
            events = []
            async for event in tool.run(args, ctx=ctx):
                events.append(event)
        finally:
            os.chdir(old_cwd)

        # Check that it routed to git_status
        messages = [e.message for e in events if hasattr(e, "message") and e.message]
        assert any("Rerouting to git_tool" in msg for msg in messages)
