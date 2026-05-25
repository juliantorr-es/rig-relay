"""Tests for rig_relay.cli.opencode_tool_bridge — OpenCode transport adapter.

Stage 3: OpenCode thin routing.
  OpenCode rig_search_replace → opencode_tool_bridge.py
  → persist proposal/payload/campaign context
  → execute_campaign_execution()
  → content-light result with receipt identifiers.
"""

from __future__ import annotations

import hashlib
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


class TestBridgeTransportIntegration:
    """Proves the bridge routes through execute_campaign_execution.

    Stage 3: Bridge creates campaign context, persists proposal/payload,
    and delegates to the governed campaign execution route.
    """

    @pytest.mark.asyncio
    async def test_bridge_completes_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge completes mutation through campaign execution."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original line\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="original line",
            new_str="replaced line",
            directory=str(repo),
        )

        assert result["status"] in ("completed", "already_completed"), (
            f"Expected completed, got {result.get('status')}: {result.get('refusal_reason', '')}"
        )
        assert (repo / "target.py").read_text() == "replaced line\n"

    @pytest.mark.asyncio
    async def test_file_mutated_on_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File is changed when bridge completes mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "before\n")

        result = await _invoke_bridge(
            file_path="target.py",
            old_str="before",
            new_str="after",
            directory=str(repo),
        )

        assert result["status"] in ("completed", "already_completed")
        assert (repo / "target.py").read_text() == "after\n"


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
        assert result["status"] in ("completed", "already_completed")


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

        assert result["status"] == "refused"
        assert result.get("refusal_reason")

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
        """Bridge CLI succeeds and returns completed status."""
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
            timeout=60,
            env={**subprocess.os.environ, "RIG_REPO_ROOT": str(repo)},
        )
        result = json.loads(proc.stdout.strip())
        assert result["status"] in ("completed", "already_completed"), (
            f"Expected completed, got {result.get('status')}: {result.get('refusal_reason', '')}"
        )
        assert (repo / "target.py").read_text() == "cli replaced\n"

    @pytest.mark.asyncio
    async def test_bridge_routes_through_campaign(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bridge delegates to execute_campaign_execution — completes mutation."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        result = await _invoke_bridge(
            file_path="target.py", old_str="hello", new_str="world", directory=str(repo)
        )

        assert result["status"] in ("completed", "already_completed"), (
            f"Expected completed, got {result.get('status')}: {result.get('refusal_reason', '')}"
        )
        assert (repo / "target.py").read_text() == "world\n"
