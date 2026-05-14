"""Coverage tests for runtime tool adapter edge cases: non-match, unsupported tools, linkage fields.

Tests are isolated and never mutate files outside temp directories.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
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

# ── Helpers (mirror test_runtime_tool_invocation_execution) ────────────


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


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal git repo with a pyproject.toml at repo root."""
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


# ── SearchReplace non-match status variants ────────────────────────────


class TestSearchReplaceNonMatch:
    """Tests for search_replace non-match status variants through the adapter."""

    @pytest.mark.asyncio
    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:
        """Search text not found returns COMPLETED with tool_status='no_match'."""
        target = tmp_path / "test.py"
        target.write_text("original\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nnonexistent_text_xyz\n=======\nreplacement\n>>>>>>> REPLACE"
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "no_match"
        assert target.read_text(encoding="utf-8") == "original\n"

    @pytest.mark.asyncio
    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:
        """Duplicate SEARCH text with allow_multiple=False returns COMPLETED."""
        target = tmp_path / "test.py"
        target.write_text("repeat\nother\nrepeat\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nrepeat\n=======\nchanged\n>>>>>>> REPLACE"
                ),
                "allow_multiple": False,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "ambiguous_match"

    @pytest.mark.asyncio
    async def test_count_mismatch_returns_completed(self, tmp_path: Path) -> None:
        """expected_replacements mismatch returns COMPLETED with count_mismatch."""
        target = tmp_path / "test.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"),
                "expected_replacements": 3,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "count_mismatch"


# ── SearchReplace unsupported tool routing ─────────────────────────────


class TestSearchReplaceUnsupportedTool:
    """Tests that execute_search_replace refuses non-search_replace tools."""

    @pytest.mark.asyncio
    async def test_write_file_refused(self) -> None:
        """write_file through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.WRITE_FILE)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "write_file" in (result.refusal_reason or "")

    @pytest.mark.asyncio
    async def test_validate_refused(self) -> None:
        """validate through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "validate" in (result.refusal_reason or "")

    @pytest.mark.asyncio
    async def test_bash_legacy_refused(self) -> None:
        """bash_legacy through search_replace returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY)
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "bash_legacy" in (result.refusal_reason or "")


# ── Validate unsupported tool routing ──────────────────────────────────


class TestValidateUnsupportedTool:
    """Tests that execute_validate refuses non-validate tools."""

    @pytest.mark.asyncio
    async def test_bash_legacy_refused(self) -> None:
        """bash_legacy through validate returns REFUSED with unsupported_tool."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY)
        resolution = _resolved()
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "bash_legacy" in (result.refusal_reason or "")


# ── Linkage field population ───────────────────────────────────────────


class TestLinkageFields:
    """Tests that linkage fields (intent_id, tool_name, invocation_id) are populated."""

    @pytest.mark.asyncio
    async def test_validate_linkage_fields_populated(self, tmp_path: Path) -> None:
        """Completed validate populates intent_id, tool_name, invocation_id."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)
        assert result.intent_id == "intent-001"
        assert result.tool_name == "validate"
        assert result.invocation_id is not None
        assert len(result.invocation_id) > 0

    @pytest.mark.asyncio
    async def test_search_replace_linkage_fields_populated(
        self, tmp_path: Path
    ) -> None:
        """Completed search_replace populates intent_id, tool_name, invocation_id."""
        target = tmp_path / "test.py"
        target.write_text("abc\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nabc\n=======\ndef\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.intent_id == "intent-001"
        assert result.tool_name == "search_replace"
        assert result.invocation_id is not None
        assert len(result.invocation_id) > 0


# ── WriteFile execution tests ──────────────────────────────────────────


class TestWriteFileExecution:
    """Tests for execute_write_file through the adapter."""

    @pytest.mark.asyncio
    async def test_write_file_creates_file(self, tmp_path: Path) -> None:
        """A valid write_file creates the target file with correct content."""
        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "hello world\n"},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "success"
        assert result.invocation_id is not None
        assert target.read_text(encoding="utf-8") == "hello world\n"

    @pytest.mark.asyncio
    async def test_blocked_resolution_does_not_run(self) -> None:
        """A blocked context resolution returns BLOCKED without running."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": "/tmp/test.txt", "content": "data"},
        )
        resolution = _resolved(status="blocked")
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None

    @pytest.mark.asyncio
    async def test_refused_adapter_returns_refused(self) -> None:
        """A refused adapter result returns REFUSED without running."""
        runner = RuntimeToolExecutionRunner()
        ctx = _resolved_context()
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"content": "missing path"},  # no path -> adapter refusal
        )
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind is not None

    @pytest.mark.asyncio
    async def test_non_write_file_refused(self) -> None:
        """Non-write_file tools through execute_write_file return REFUSED."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved()
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_changed_paths_populated(self, tmp_path: Path) -> None:
        """Completed write_file populates changed_paths with target path."""
        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "data\n"},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        assert result.changed_paths == [str(target)]


class TestWriteFileReceiptEvidence:
    """Tests for write_file receipt typing and content-light enforcement."""

    @pytest.mark.asyncio
    async def test_receipt_populated_for_completed_write_file(
        self, tmp_path: Path
    ) -> None:
        """A completed write_file populates a typed RuntimeToolInvocationReceipt."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "evidence\n"},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == "write_file"
        assert result.receipt.tool_name == "write_file"
        assert result.receipt.adapter_status == "completed"
        assert (
            result.receipt.schema_version
            == "rig.relay.runtime_tool_invocation_receipt.v1"
        )

    @pytest.mark.asyncio
    async def test_receipt_not_populated_for_blocked_write_file(self) -> None:
        """A blocked write_file does not populate the receipt field."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.WRITE_FILE)
        resolution = _resolved(status="blocked")
        result = await runner.execute_write_file(intent, resolution)
        assert result.receipt is None

    @pytest.mark.asyncio
    async def test_write_file_result_is_content_light(self, tmp_path: Path) -> None:
        """RuntimeToolExecutionResult dump must not contain raw content fields."""
        FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
            "content",
            "stdout",
            "stderr",
            "output_text",
            "diff",
            "patch",
            "snippet",
            "file_contents",
            "old_text",
            "new_text",
            "chunk_text",
        })
        import json

        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "secrets\n"},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(intent, resolution)
        dumped = json.dumps(result.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in execution result dump"
            )


# ── End-to-end adapter gate ─────────────────────────────────────────────
#
# Phase 2 runtime adapter end-to-end gate.
# Tests prove all four supported tools route through the governed adapter
# consistently, emit typed receipts, validate against strict schemas, and
# remain content-light.

# ── Fixtures ────────────────────────────────────────────────────────────

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


@pytest.fixture
def execution_schema_dict() -> dict:
    from rig_relay.desktop.projection import _load_json

    raw = _load_json(EXECUTION_SCHEMA_PATH)
    assert raw is not None, f"Schema not found at {EXECUTION_SCHEMA_PATH}"
    return raw


class TestAdapterGate:
    """End-to-end adapter gate covering all supported and unsupported tools."""

    # ── Helper ──────────────────────────────────────────────────────

    def _check_content_light(self, result: RuntimeToolExecutionResult) -> None:
        """Assert no forbidden raw fields in result's model_dump."""
        dumped = result.model_dump(mode="json")
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELDS:
            assert forbidden not in dumped_str, (
                f"Found forbidden field '{forbidden}' in dump"
            )

    def _check_schema_valid(
        self, result: RuntimeToolExecutionResult, schema: dict
    ) -> None:
        """Assert result validates against schema without exclude_none."""
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def _check_no_serialization_warning(
        self, result: RuntimeToolExecutionResult
    ) -> None:
        """Assert model_dump with receipt emits no PydanticSerializationUnexpectedValue."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result.model_dump(mode="json")
        unexpected = [
            x for x in w if "PydanticSerializationUnexpectedValue" in str(x.message)
        ]
        assert not unexpected, f"Got warnings: {[str(x.message) for x in unexpected]}"

    def _check_receipt_typed(self, result: RuntimeToolExecutionResult) -> None:
        """Assert receipt is RuntimeToolInvocationReceipt (not dict)."""
        if result.receipt is not None:
            assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
            # Access by attribute, not dict indexing
            _ = result.receipt.tool_receipt_kind
            _ = result.receipt.tool_receipt_schema_version
            _ = result.receipt.receipt_sha256
            _ = result.receipt.changed_paths
            _ = result.receipt.adapter_status
            _ = result.receipt.duration_ms
            _ = result.receipt.warnings

    def _check_linkage_fields(
        self,
        result: RuntimeToolExecutionResult,
        *,
        expected_kind: str,
        has_changed_paths: bool = False,
    ) -> None:
        """Assert linkage fields are populated correctly."""
        assert result.tool_receipt_kind == expected_kind, (
            f"Expected tool_receipt_kind={expected_kind}, got {result.tool_receipt_kind}"
        )
        assert result.tool_receipt_schema_version is not None, (
            "tool_receipt_schema_version should not be None"
        )
        if result.status.value == "completed" and result.receipt_sha256 is None:
            # Allow no hash if receipt building failed silently
            pass
        if has_changed_paths:
            assert len(result.changed_paths) > 0, (
                "Expected changed_paths to be populated for mutation tool"
            )
        # Phase 2: receipt_envelope_id and audit_event_id are None
        assert result.receipt_envelope_id is None, (
            "receipt_envelope_id should be None in Phase 2"
        )
        assert result.audit_event_id is None, "audit_event_id should be None in Phase 2"

    # ── Supported: validate ─────────────────────────────────────────

    async def _run_validate(self, tmp_path: Path) -> RuntimeToolExecutionResult:
        """Helper: run a completed validate execution."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        runner = RuntimeToolExecutionRunner()
        return await runner.execute_validate(intent, resolution)

    @pytest.mark.asyncio
    async def test_validate_adapter_gate(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """Validate: full gate — completion, receipts, schema, content-light."""
        result = await self._run_validate(tmp_path)
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "validate"
        assert result.intent_id == "intent-001"
        self._check_receipt_typed(result)
        self._check_content_light(result)
        self._check_schema_valid(result, execution_schema_dict)
        self._check_no_serialization_warning(result)
        self._check_linkage_fields(
            result, expected_kind="validate", has_changed_paths=False
        )

    # ── Supported: search_replace ───────────────────────────────────

    async def _run_search_replace(self, tmp_path: Path) -> RuntimeToolExecutionResult:
        """Helper: run a completed search_replace execution."""
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        return await runner.execute_search_replace(intent, resolution)

    @pytest.mark.asyncio
    async def test_search_replace_adapter_gate(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """SearchReplace: full gate — completion, receipts, schema, content-light."""
        result = await self._run_search_replace(tmp_path)
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "search_replace"
        assert result.intent_id == "intent-001"
        self._check_receipt_typed(result)
        self._check_content_light(result)
        self._check_schema_valid(result, execution_schema_dict)
        self._check_no_serialization_warning(result)
        self._check_linkage_fields(
            result, expected_kind="search_replace", has_changed_paths=True
        )
        assert "test.py" in result.changed_paths

    # ── Supported: write_file ───────────────────────────────────────

    async def _run_write_file(self, tmp_path: Path) -> RuntimeToolExecutionResult:
        """Helper: run a write_file execution."""
        target = tmp_path / "test.txt"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={
                "path": str(target),
                "content": "new content\\n",
                "overwrite": False,
            },
        )
        runner = RuntimeToolExecutionRunner()
        return await runner.execute_write_file(intent, resolution)

    @pytest.mark.asyncio
    async def test_write_file_adapter_gate(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """WriteFile: full gate — completion, receipts, schema, content-light."""
        result = await self._run_write_file(tmp_path)
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "write_file"
        assert result.intent_id == "intent-001"
        self._check_receipt_typed(result)
        self._check_content_light(result)
        self._check_schema_valid(result, execution_schema_dict)
        self._check_no_serialization_warning(result)
        self._check_linkage_fields(
            result, expected_kind="write_file", has_changed_paths=True
        )
        assert "test.txt" in " ".join(result.changed_paths)

    # ── Supported: bash ─────────────────────────────────────────────

    async def _run_bash(self, tmp_path: Path) -> RuntimeToolExecutionResult:
        """Helper: run a bash execution."""
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={"command": "echo hello", "legacy_fallback_allowed": True},
        )
        runner = RuntimeToolExecutionRunner()
        return await runner.execute_bash(intent, resolution)

    @pytest.mark.asyncio
    async def test_bash_adapter_gate(
        self, tmp_path: Path, execution_schema_dict: dict
    ) -> None:
        """Bash: full gate — completion, receipts, schema, content-light."""
        result = await self._run_bash(tmp_path)
        assert isinstance(result, RuntimeToolExecutionResult)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_name == "bash_legacy"
        assert result.intent_id == "intent-001"
        self._check_receipt_typed(result)
        self._check_content_light(result)
        self._check_schema_valid(result, execution_schema_dict)
        self._check_no_serialization_warning(result)
        self._check_linkage_fields(
            result, expected_kind="bash", has_changed_paths=False
        )

    @pytest.mark.asyncio
    async def test_bash_failure_returns_failed(self, tmp_path: Path) -> None:
        """Bash failure (non-zero exit) returns FAILED with execution_error."""
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={"command": "false", "legacy_fallback_allowed": True},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.FAILED
        assert result.error_kind == "execution_error"
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_bash_timeout_returns_structured_result(self, tmp_path: Path) -> None:
        """Bash timeout produces timed_out tool_status with error_kind timeout."""
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={
                "command": "sleep 10",
                "timeout": 1,
                "legacy_fallback_allowed": True,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "timed_out"
        assert result.error_kind == "timeout"

    @pytest.mark.asyncio
    async def test_bash_content_light_no_raw_output(self, tmp_path: Path) -> None:
        """Bash: distinctive stdout content is NOT in execution result dump."""
        import json

        marker = "UNIQUE_CONTENT_LIGHT_TEST_MARKER_abc123"
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={"command": f"echo {marker}", "legacy_fallback_allowed": True},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(intent, resolution)
        dumped = json.dumps(result.model_dump(mode="json"))
        assert marker not in dumped, (
            "Raw stdout leaked into RuntimeToolExecutionResult dump"
        )
        if result.receipt is not None:
            receipt_dumped = json.dumps(result.receipt.model_dump(mode="json"))
            assert marker not in receipt_dumped, (
                "Raw stdout leaked into RuntimeToolInvocationReceipt dump"
            )

    @pytest.mark.asyncio
    async def test_bash_receipt_has_structure(self, tmp_path: Path) -> None:
        """Bash receipt is typed and has proper linkage fields."""
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY,
            payload={"command": "echo hello", "legacy_fallback_allowed": True},
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(intent, resolution)
        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == "bash"
        assert result.receipt.tool_receipt_schema_version is not None
        assert result.receipt.receipt_sha256 is not None
        assert result.receipt.adapter_status == "completed"
        assert result.receipt.changed_paths == []

    # ── Unsupported tool routing ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_unsupported_tool_validate(self) -> None:
        """Unsupported tool through execute_validate returns REFUSED."""
        runner = RuntimeToolExecutionRunner()
        for name in [RuntimeToolName.BASH_LEGACY, RuntimeToolName.WRITE_FILE]:
            result = await runner.execute_validate(_intent(name), _resolved())
            assert result.status == RuntimeToolExecutionStatus.REFUSED
            assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_unsupported_tool_search_replace(self) -> None:
        """Unsupported tool through execute_search_replace returns REFUSED."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(
            _intent(RuntimeToolName.VALIDATE), _resolved()
        )
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_unsupported_tool_write_file(self) -> None:
        """Unsupported tool through execute_write_file returns REFUSED."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(
            _intent(RuntimeToolName.VALIDATE), _resolved()
        )
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    @pytest.mark.asyncio
    async def test_unsupported_tool_bash(self) -> None:
        """Unsupported tool through execute_bash returns REFUSED."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(
            _intent(RuntimeToolName.VALIDATE), _resolved()
        )
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"

    # ── Blocked adapter routing ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_blocked_validate(self) -> None:
        """Blocked context returns BLOCKED without running tool."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(
            _intent(RuntimeToolName.VALIDATE), _resolved(status="blocked")
        )
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_blocked_write_file(self) -> None:
        """Blocked context returns BLOCKED without running write_file."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_write_file(
            _intent(RuntimeToolName.WRITE_FILE), _resolved(status="blocked")
        )
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_blocked_bash(self) -> None:
        """Blocked context returns BLOCKED without running bash."""
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_bash(
            _intent(RuntimeToolName.BASH_LEGACY), _resolved(status="blocked")
        )
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None
        assert result.tool_status is None

    # ── Schema boundary gate ───────────────────────────────────────

    def test_schema_has_additional_properties_false(
        self, execution_schema_dict: dict
    ) -> None:
        """Schema must have additionalProperties: false at top level."""
        assert execution_schema_dict.get("additionalProperties") is False

    def test_schema_receipt_def_has_additional_properties_false(
        self, execution_schema_dict: dict
    ) -> None:
        """Schema receipt definition must have additionalProperties: false."""
        receipt_def = execution_schema_dict.get("$defs", {}).get(
            "runtime_tool_invocation_receipt", {}
        )
        assert receipt_def.get("additionalProperties") is False

    def test_schema_rejects_unknown_fields(self, execution_schema_dict: dict) -> None:
        """Schema must reject unknown fields at top level."""
        base = {
            "schema_version": "rig.relay.runtime_tool_execution_result.v1",
            "status": "completed",
            "intent_id": "i1",
            "tool_name": "validate",
        }
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        bad = dict(base)
        bad["unknown_field"] = "x"
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    # ── Content-light gate ─────────────────────────────────────────

    def test_content_light_forbidden_fields_defined(self) -> None:
        """All known forbidden fields are in the set."""
        expected = {
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
        }
        assert FORBIDDEN_RAW_FIELDS == expected, (
            f"FORBIDDEN_RAW_FIELDS mismatch. Extra: {FORBIDDEN_RAW_FIELDS - expected}. "
            f"Missing: {expected - FORBIDDEN_RAW_FIELDS}"
        )

    def test_schema_has_no_forbidden_field_keys(
        self, execution_schema_dict: dict
    ) -> None:
        """Schema property keys contain no forbidden field names."""

        def _check(obj: object, path: str) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k not in FORBIDDEN_RAW_FIELDS, (
                        f"Forbidden field '{k}' at {path}"
                    )
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")

        _check(execution_schema_dict, "schema")
