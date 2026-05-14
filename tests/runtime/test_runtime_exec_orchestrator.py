"""Tests for runtime_exec orchestrator: dispatch to Phase 2 adapters.

Tests prove runtime_exec routes to execute_validate, execute_search_replace,
execute_write_file, and execute_bash, plus unsupported sub-tool handling.
"""

from __future__ import annotations

from pathlib import Path
import warnings

import jsonschema
import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)
from rig_relay.runtime.tool_invocation_receipt import RuntimeToolInvocationReceipt

# ── Constants ─────────────────────────────────────────────────────────

EXECUTION_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_execution_result.v1.schema.json"
)

FORBIDDEN_RAW_FIELDS: frozenset[str] = frozenset({
    "stdout",
    "stderr",
    "content",
    "file_contents",
    "chunk_text",
    "old_text",
    "new_text",
    "diff",
    "patch",
    "prompt",
    "secret",
    "argv",
    "snippet",
})

# ── Helpers ────────────────────────────────────────────────────────────


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


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def execution_schema_dict() -> dict:
    from rig_relay.desktop.projection import _load_json

    raw = _load_json(EXECUTION_SCHEMA_PATH)
    assert raw is not None, f"Schema not found at {EXECUTION_SCHEMA_PATH}"
    return raw


def _check_content_light(result: RuntimeToolExecutionResult) -> None:
    """Assert no forbidden raw field names appear as keys in the dump."""

    def _check(obj: object, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in FORBIDDEN_RAW_FIELDS, f"Forbidden field '{k}' at {path}"
                _check(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _check(item, f"{path}[{i}]")

    _check(result.model_dump(mode="json"), "result")


def _check_schema_valid(result: RuntimeToolExecutionResult, schema: dict) -> None:
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(result.model_dump(mode="json")))
    assert errors == [], f"Schema errors: {[e.message for e in errors]}"


def _check_no_serialization_warning(result: RuntimeToolExecutionResult) -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result.model_dump(mode="json")
    unexpected = [
        x for x in w if "PydanticSerializationUnexpectedValue" in str(x.message)
    ]
    assert not unexpected, f"Got warnings: {[str(x.message) for x in unexpected]}"


def _check_receipt_typed(result: RuntimeToolExecutionResult) -> None:
    if result.receipt is not None:
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        _ = result.receipt.tool_receipt_kind
        _ = result.receipt.tool_receipt_schema_version
        _ = result.receipt.receipt_sha256
        _ = result.receipt.changed_paths
        _ = result.receipt.adapter_status
        _ = result.receipt.duration_ms
        _ = result.receipt.warnings


def _check_linkage_fields(
    result: RuntimeToolExecutionResult,
    *,
    expected_kind: str,
    has_changed_paths: bool = False,
) -> None:
    assert result.tool_receipt_kind == expected_kind, (
        f"Expected tool_receipt_kind={expected_kind}, got {result.tool_receipt_kind}"
    )
    assert result.tool_receipt_schema_version is not None, (
        "tool_receipt_schema_version should not be None"
    )
    if has_changed_paths:
        assert len(result.changed_paths) > 0, (
            "Expected changed_paths to be populated for mutation tool"
        )
    assert result.receipt_envelope_id is None, (
        "receipt_envelope_id should be None in Phase 2"
    )
    assert result.audit_event_id is None, "audit_event_id should be None in Phase 2"


# ── Tests ─────────────────────────────────────────────────────────────


class TestRuntimeExecOrchestrator:
    """Runtime_exec dispatches to all four Phase 2 adapters correctly."""

    # ── Helper: context with a real tmp_path ────────────────────────

    @staticmethod
    def _working_resolution(tmp_path: Path) -> RuntimeContextResolution:
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        return RuntimeContextResolution(status="resolved", context=ctx)

    @staticmethod
    def _runner() -> RuntimeToolExecutionRunner:
        return RuntimeToolExecutionRunner()

    # ── Dispatch: validate ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_dispatches_validate(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """runtime_exec with tool_name=validate dispatches to execute_validate."""
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={"tool_name": "validate", "profile": "quick"},
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "validate"
        _check_receipt_typed(result)
        _check_content_light(result)
        _check_schema_valid(result, execution_schema_dict)
        _check_no_serialization_warning(result)
        _check_linkage_fields(result, expected_kind="validate", has_changed_paths=False)

    # ── Dispatch: search_replace ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_dispatches_search_replace(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """runtime_exec with tool_name=search_replace dispatches to execute_search_replace."""
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "search_replace",
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
            },
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "search_replace"
        _check_receipt_typed(result)
        _check_content_light(result)
        _check_schema_valid(result, execution_schema_dict)
        _check_no_serialization_warning(result)
        _check_linkage_fields(
            result, expected_kind="search_replace", has_changed_paths=True
        )
        assert "test.py" in " ".join(result.changed_paths)

    # ── Dispatch: write_file ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_dispatches_write_file(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """runtime_exec with tool_name=write_file dispatches to execute_write_file."""
        target = tmp_path / "test.txt"
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "write_file",
                "path": str(target),
                "content": "new content\n",
                "overwrite": False,
            },
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "write_file"
        _check_receipt_typed(result)
        _check_content_light(result)
        _check_schema_valid(result, execution_schema_dict)
        _check_no_serialization_warning(result)
        _check_linkage_fields(
            result, expected_kind="write_file", has_changed_paths=True
        )

    # ── Dispatch: bash ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_dispatches_bash(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """runtime_exec with tool_name=bash_legacy dispatches to execute_bash."""
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "bash_legacy",
                "command": "echo hello",
                "legacy_fallback_allowed": True,
            },
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "bash_legacy"
        _check_receipt_typed(result)
        _check_content_light(result)
        _check_schema_valid(result, execution_schema_dict)
        _check_no_serialization_warning(result)
        _check_linkage_fields(result, expected_kind="bash", has_changed_paths=False)

    # ── Dispatch: unsupported tool ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_unsupported_subtool_returns_refused(self) -> None:
        """runtime_exec with unknown sub-tool returns REFUSED/unsupported_tool."""
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC, payload={"tool_name": "nonexistent_tool"}
        )
        result = await self._runner().execute_runtime_exec(intent, _resolved())
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_runtime_exec_missing_tool_name_returns_refused(self) -> None:
        """runtime_exec without tool_name returns REFUSED/invalid_payload."""
        intent = _intent(RuntimeToolName.RUNTIME_EXEC, payload={})
        result = await self._runner().execute_runtime_exec(intent, _resolved())
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "invalid_payload"

    @pytest.mark.asyncio
    async def test_runtime_exec_rejects_non_runtime_exec_intent(self) -> None:
        """runtime_exec refuses intents with tool_name != RUNTIME_EXEC."""
        intent = _intent(RuntimeToolName.VALIDATE, payload={"tool_name": "validate"})
        result = await self._runner().execute_runtime_exec(intent, _resolved())
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_runtime_exec_rejects_circular_dispatch(self) -> None:
        """runtime_exec refuses runtime_exec dispatched to itself."""
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC, payload={"tool_name": "runtime_exec"}
        )
        result = await self._runner().execute_runtime_exec(intent, _resolved())
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    # ── Blocked resolution forwarding ─────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_forward_blocked_resolution(self) -> None:
        """runtime_exec forwards blocked resolution from sub-tool."""
        blocked = _resolved(status="blocked")
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={"tool_name": "validate", "profile": "quick"},
        )
        result = await self._runner().execute_runtime_exec(intent, blocked)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind == "context_unresolved"

    # ── bash requires legacy_fallback_allowed ──────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_bash_refused_without_fallback(
        self, tmp_path: Path
    ) -> None:
        """Bash dispatch without legacy_fallback_allowed returns REFUSED."""
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={"tool_name": "bash_legacy", "command": "echo hello"},
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        _check_content_light(result)

    # ── write_file forwards payload correctly ──────────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_write_file_forwards_changed_path(
        self, tmp_path: Path
    ) -> None:
        """Write_file via runtime_exec has correct changed_paths."""
        target = tmp_path / "test.txt"
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "write_file",
                "path": str(target),
                "content": "data\n",
                "overwrite": False,
            },
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert str(target) in " ".join(result.changed_paths)

    # ── search_replace forwards payload correctly ──────────────────

    @pytest.mark.asyncio
    async def test_runtime_exec_search_replace_subtool_preserves_payload(
        self, tmp_path: Path
    ) -> None:
        """Non-tool_name payload keys are forwarded to sub-tool."""
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "search_replace",
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
            },
        )
        result = await self._runner().execute_runtime_exec(
            intent, self._working_resolution(tmp_path)
        )
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert target.read_text(encoding="utf-8") == "new\n"
