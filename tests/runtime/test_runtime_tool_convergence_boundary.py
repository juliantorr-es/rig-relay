"""Boundary tests for runtime intent convergence through ToolRuntime."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)


def _resolved_context(**overrides: object) -> RuntimeContext:
    kwargs: dict[str, object] = {
        "session_id": "sess-001",
        "task_id": "task-001",
        "lane_id": "lane-001",
        "workspace_id": "ws-001",
        "worktree_path": "/tmp/worktrees/ws-001",
        "repo_root": "/tmp/repo",
        "dirty_policy": "preserve_existing",
    }
    kwargs.update(overrides)
    return RuntimeContext(**kwargs)  # type: ignore[arg-type]


def _resolved(
    status: str = "resolved", **overrides: object
) -> RuntimeContextResolution:
    kwargs: dict[str, object] = {
        "status": status,
        "context": _resolved_context() if status == "resolved" else None,
    }
    if status == "blocked":
        kwargs["error_kind"] = "session_required"
        kwargs["refusal_reason"] = "session_id is required"
    kwargs.update(overrides)
    return RuntimeContextResolution(**kwargs)  # type: ignore[arg-type]


def _intent(
    tool_name: RuntimeToolName = RuntimeToolName.VALIDATE, **overrides: object
) -> RuntimeToolIntent:
    kwargs: dict[str, object] = {
        "intent_id": "intent-001",
        "tool_name": tool_name,
        "payload": {},
    }
    kwargs.update(overrides)
    return RuntimeToolIntent(**kwargs)  # type: ignore[arg-type]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _method_source(name: str) -> str:
    source = inspect.getsource(RuntimeToolExecutionRunner)
    tree = ast.parse(source)
    class_def = tree.body[0]
    assert isinstance(class_def, ast.ClassDef)
    for node in class_def.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"method {name} not found")


class TestArchitectureBoundaries:
    def test_runner_uses_tool_runtime(self) -> None:
        source = inspect.getsource(RuntimeToolExecutionRunner)
        assert "ToolRuntime(" in source
        assert "execute_one(" in source

    def test_tool_runtime_does_not_import_runner(self) -> None:
        source = (_repo_root() / "rig_relay" / "core" / "tool_runtime.py").read_text(
            encoding="utf-8"
        )
        assert "runtime.tool_invocation_execution" not in source

    def test_normal_path_does_not_directly_instantiate_concrete_tools(self) -> None:
        for method_name in (
            "execute_validate",
            "execute_search_replace",
            "execute_write_file",
            "execute_bash",
        ):
            source = _method_source(method_name)
            for token in ("Validate(", "SearchReplace(", "WriteFile(", "Bash("):
                assert token not in source
        for helper in (
            "_run_validate_tool",
            "_run_search_replace_tool",
            "_run_write_file_tool",
            "_run_bash_tool",
        ):
            assert helper in inspect.getsource(RuntimeToolExecutionRunner)


class TestRuntimeDispatch:
    @pytest.mark.asyncio
    async def test_validate_routes_through_tool_runtime(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1.0'\n")
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        calls: list[object] = []

        async def fake_execute_one(request):
            calls.append(request)
            return SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                provider_tool_response=SimpleNamespace(
                    status=SimpleNamespace(value="passed"),
                    error_kind=None,
                    refusal_reason=None,
                ),
                refusal=None,
                error_kind=None,
            )

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        result = await runner.execute_validate(intent, resolution)
        assert len(calls) == 1
        assert result.status == RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_search_replace_routes_through_tool_runtime_and_leases(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        calls: list[object] = []
        releases: list[object] = []

        async def fake_execute_one(request):
            calls.append(request)
            return SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                provider_tool_response=SimpleNamespace(
                    status=SimpleNamespace(value="success"),
                    error_kind=None,
                    refusal_reason=None,
                ),
                refusal=None,
                error_kind=None,
            )

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        from rig_relay.runtime import _execution_template, _lease_gate
        monkeypatch.setattr(
            _execution_template, "release_mutation_lease", lambda *args, **kwargs: releases.append(args)
        )
        monkeypatch.setattr(
            _lease_gate, "release_mutation_lease", lambda *args, **kwargs: releases.append(args)
        )
        result = await runner.execute_search_replace(intent, resolution)
        assert len(calls) == 1
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.changed_paths == ["test.py"]
        assert releases

    @pytest.mark.asyncio
    async def test_write_file_routes_through_tool_runtime_and_leases(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "hello\n"},
        )
        calls: list[object] = []
        releases: list[object] = []

        async def fake_execute_one(request):
            calls.append(request)
            return SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                provider_tool_response=SimpleNamespace(
                    status=SimpleNamespace(value="success"),
                    error_kind=None,
                    refusal_reason=None,
                ),
                refusal=None,
                error_kind=None,
            )

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        from rig_relay.runtime import _execution_template, _lease_gate
        monkeypatch.setattr(
            _execution_template, "release_mutation_lease", lambda *args, **kwargs: releases.append(args)
        )
        monkeypatch.setattr(
            _lease_gate, "release_mutation_lease", lambda *args, **kwargs: releases.append(args)
        )
        result = await runner.execute_write_file(intent, resolution)
        assert len(calls) == 1
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.changed_paths == [str(target)]
        assert releases

    @pytest.mark.asyncio
    async def test_bash_routes_through_tool_runtime(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={"command": "echo hello", "legacy_fallback_allowed": True},
        )
        calls: list[object] = []

        async def fake_execute_one(request):
            calls.append(request)
            return SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                provider_tool_response=SimpleNamespace(
                    status=SimpleNamespace(value="success"),
                    error_kind=None,
                    refusal_reason=None,
                ),
                refusal=None,
                error_kind=None,
            )

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        result = await runner.execute_bash(intent, resolution)
        assert len(calls) == 1
        assert result.status == RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_malformed_intent_refuses_before_tool_runtime(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE, payload={"content": "missing path"}
        )
        called = {"count": 0}

        async def fake_execute_one(request):
            called["count"] += 1
            return SimpleNamespace(status=SimpleNamespace(value="completed"))

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert called["count"] == 0

    @pytest.mark.asyncio
    async def test_lease_failure_refuses_before_tool_runtime(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        runner = RuntimeToolExecutionRunner()
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        called = {"count": 0}

        async def fake_execute_one(request):
            called["count"] += 1
            return SimpleNamespace(status=SimpleNamespace(value="completed"))

        monkeypatch.setattr(runner._tool_runtime, "execute_one", fake_execute_one)
        from rig_relay.runtime import _execution_template, _lease_gate
        lease_block_mock = SimpleNamespace(
            blocked=True,
            error_kind="lease_conflict",
            refusal_reason="lease conflict",
            lease_info=None,
            intent_id="intent-001",
            tool_name="search_replace",
            granted=False,
        )
        monkeypatch.setattr(
            _execution_template, "claim_mutation_lease",
            lambda envelope, file_path, coordination_root=None: lease_block_mock,
        )
        monkeypatch.setattr(
            _lease_gate, "claim_mutation_lease",
            lambda envelope, file_path, coordination_root=None: lease_block_mock,
        )
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert called["count"] == 0
