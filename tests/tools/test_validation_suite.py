from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from rig_relay.core.tools.base import BaseToolState, InvokeContext, ToolError
from rig_relay.core.tools.builtins.validation_suite import (
    ValidationStepRequest,
    ValidationSuite,
    ValidationSuiteArgs,
    ValidationSuiteConfig,
)
from tests.mock.utils import collect_result


class _FakeProcess:
    def __init__(
        self, returncode: int, stdout: bytes = b"", stderr: bytes = b""
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(0)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def validation_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ValidationSuite:
    monkeypatch.chdir(tmp_path)
    config = ValidationSuiteConfig(
        validation_root=tmp_path / ".build" / "rig-relay" / "validation"
    )
    return ValidationSuite(config_getter=lambda: config, state=BaseToolState())


@pytest.mark.asyncio
async def test_default_safe_suite_runs_allowlisted_steps(
    monkeypatch, validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    seen: list[list[str]] = []

    async def fake_create(*cmd: str, **kwargs: object) -> _FakeProcess:
        seen.append(list(cmd))
        return _FakeProcess(0, stdout=b"ok\n", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    result = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(
                steps=[
                    ValidationStepRequest(
                        kind="ruff_check",
                        paths=["tests/tools/test_validation_suite.py"],
                    ),
                    ValidationStepRequest(
                        kind="pytest", paths=["tests/tools/test_validation_suite.py"]
                    ),
                    ValidationStepRequest(kind="schema_validation"),
                ]
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert result.status == "passed"
    assert result.executed_steps == ["ruff_check", "pytest", "schema_validation"]
    assert seen[0][:4] == ["uv", "run", "ruff", "check"]
    assert seen[1][:4] == ["uv", "run", "pytest", "-n0"]
    assert seen[2] == ["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"]
    assert result.stdout_sha256.startswith("sha256:")
    assert result.stderr_sha256.startswith("sha256:")
    assert result.stdout_preview == "ok\nok\nok\n"
    assert result.stderr_preview == ""


@pytest.mark.asyncio
async def test_unknown_step_is_refused(
    monkeypatch, validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    monkeypatch.setattr(asyncio, "create_subprocess_exec", pytest.fail)

    result = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(steps=[ValidationStepRequest(kind="not_a_step")]),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert result.status == "refused"
    assert result.steps[0].status == "refused"
    assert "Unknown validation step" in result.steps[0].stderr_preview


@pytest.mark.asyncio
async def test_ruff_format_fix_refused_without_allow_mutation(
    validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    result = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(
                steps=[
                    ValidationStepRequest(
                        kind="ruff_format_fix",
                        paths=["vibe/core/tools/builtins/validation_suite.py"],
                    )
                ]
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert result.status == "refused"
    assert result.steps[0].status == "refused"


@pytest.mark.asyncio
async def test_docs_schemas_path_rejected_for_ruff(
    validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    result = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(
                steps=[
                    ValidationStepRequest(
                        kind="ruff_check",
                        paths=["docs/schemas/rig.relay.current_state.v1.schema.json"],
                    )
                ]
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert result.status == "refused"
    assert result.steps[0].status == "refused"


@pytest.mark.asyncio
async def test_subprocess_uses_argv_and_shell_false(
    monkeypatch, validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    async def fake_create(*cmd: str, **kwargs: object) -> _FakeProcess:
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return _FakeProcess(0, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    result = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(steps=[ValidationStepRequest(kind="storage_audit")]),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert result.steps[0].command == [
        "uv",
        "run",
        "python",
        "scripts/rig_relay_storage_audit.py",
        "--root",
        ".build/rig-relay",
    ]
    kwargs = cast(dict[str, Any], seen["kwargs"])
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == Path(tmp_path).resolve()
    assert result.steps[0].stdout_preview == "out"
    assert result.steps[0].stderr_preview == "err"


@pytest.mark.asyncio
async def test_timeout_raises_tool_error(
    monkeypatch, validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    async def fake_create(*cmd: str, **kwargs: object) -> _FakeProcess:
        class _NeverDone(_FakeProcess):
            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.sleep(0.1)
                return b"", b""

        return _NeverDone(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    async def fake_wait_for(*args: object, **kwargs: object) -> None:
        awaitable = args[0] if args else None
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    with pytest.raises(ToolError, match="timed out"):
        await collect_result(
            validation_suite.run(
                ValidationSuiteArgs(
                    steps=[
                        ValidationStepRequest(
                            kind="pytest",
                            paths=["tests/tools/test_validation_suite.py"],
                            timeout_seconds=1,
                        )
                    ]
                ),
                InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
            )
        )


@pytest.mark.asyncio
async def test_validation_suite_sha256_is_deterministic(
    monkeypatch, validation_suite: ValidationSuite, tmp_path: Path
) -> None:
    async def fake_create(*cmd: str, **kwargs: object) -> _FakeProcess:
        return _FakeProcess(0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    first = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(
                steps=[ValidationStepRequest(kind="schema_validation")]
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )
    second = await collect_result(
        validation_suite.run(
            ValidationSuiteArgs(
                steps=[ValidationStepRequest(kind="schema_validation")]
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )
    assert first.validation_suite_sha256 == second.validation_suite_sha256


@pytest.mark.asyncio
async def test_coordination_artifact_is_published_when_session_provided(
    monkeypatch, tmp_path: Path
) -> None:
    published: list[dict[str, object]] = []

    async def fake_create(*cmd: str, **kwargs: object) -> _FakeProcess:
        return _FakeProcess(0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    from rig_relay.coordination.store import CoordinationStore

    original_publish = CoordinationStore.publish_artifact

    def spy_publish(self: CoordinationStore, **kwargs: Any) -> object:
        published.append(kwargs)
        return original_publish(self, **kwargs)

    monkeypatch.setattr(CoordinationStore, "publish_artifact", spy_publish)

    config = ValidationSuiteConfig(
        validation_root=tmp_path / ".build" / "rig-relay" / "validation"
    )
    tool = ValidationSuite(config_getter=lambda: config, state=BaseToolState())

    await collect_result(
        tool.run(
            ValidationSuiteArgs(
                steps=[ValidationStepRequest(kind="storage_audit")],
                session_id="session-a",
                task_id="task-a",
            ),
            InvokeContext(tool_call_id="tool-call", session_dir=tmp_path),
        )
    )

    assert published
    assert published[0]["artifact_kind"] == "validation_suite_summary"
