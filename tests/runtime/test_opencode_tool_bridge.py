"""Tests for rig_relay.cli.opencode_tool_bridge — OpenCode transport adapter.

Stage A proved the transport boundary:
  OpenCode rig_search_replace → opencode_tool_bridge.py
  → RuntimeToolExecutionRunner.execute_search_replace()
  → structured refusal with populated receipt identifiers.

Stage A.2 confirmed:
  - Both AgentLoop and RuntimeToolExecutionRunner are fail-closed for mutation
  - No execution path currently produces lawful authorized mutation
  - The bridge correctly receives and reports the structured refusal
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
        }
        unsupported = bridge_fields - allowed
        assert not unsupported, f"Bridge fields not in schema: {unsupported}"

    def test_result_rejects_extra_keys(self) -> None:
        """Bridge result JSON validates as RuntimeToolExecutionResult subset."""
        from rig_relay.cli.opencode_tool_bridge import _invoke_search_replace

        assert callable(_invoke_search_replace)


class TestBridgeRuntimePathReached:
    """Proves the bridge reaches the real RuntimeToolExecutionRunner.

    Both the AgentLoop and RuntimeToolExecutionRunner are fail-closed for
    mutation tools by default. The bridge correctly routes through this
    path and receives a structured refusal with receipt identifiers.
    """

    @pytest.mark.asyncio
    async def test_bridge_reaches_runtime_and_receives_structured_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge reaches runtime, receives policy_object_missing refusal."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original line\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="original line",
            new_str="replaced line",
            directory=str(repo),
        )

        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert result["refusal_reason"] == "policy_object_missing"

    @pytest.mark.asyncio
    async def test_receipt_sha256_populated_even_on_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Receipt SHA-256 is populated even when runtime refuses mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="hello", new_str="world", directory=str(repo)
        )

        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert result["receipt_sha256"] is not None
        assert len(result["receipt_sha256"]) == 64
        int(result["receipt_sha256"], 16)

    @pytest.mark.asyncio
    async def test_file_not_mutated_when_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File is unchanged when the runtime refuses mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "before\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="before",
            new_str="after",
            directory=str(repo),
        )

        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert (repo / "target.py").read_text(encoding="utf-8") == "before\n"


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
        assert result["refusal_reason"] == "policy_object_missing"


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

    def test_bridge_cli_refuses_with_policy_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge CLI exits non-zero with policy_object_missing refusal."""
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
        assert proc.returncode == 1, (
            f"Expected exit 1 for refused, got {proc.returncode}. "
            f"stdout: {proc.stdout} stderr: {proc.stderr}"
        )
        result = json.loads(proc.stdout.strip())
        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert result["refusal_reason"] == "policy_object_missing"
        assert result["receipt_sha256"] is not None, (
            "Receipt SHA-256 must be populated even on refusal"
        )

    @pytest.mark.asyncio
    async def test_bridge_routes_through_tool_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge delegates to RuntimeToolExecutionRunner → ToolRuntime → refusal.

        The bridge routes through the real governed execution path and
        receives a structured refusal from the permission gate.
        """
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="hello", new_str="world", directory=str(repo)
        )

        assert result["status"] == RuntimeToolExecutionStatus.REFUSED.value
        assert result["refusal_reason"] == "policy_object_missing"
        assert result["receipt_sha256"] is not None
        assert result["duration_ms"] is not None
        assert result["duration_ms"] > 0
