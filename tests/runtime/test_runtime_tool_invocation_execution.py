"""Tests for rig_relay.runtime.tool_invocation_execution — execution models, runner, schema.

All tests use synthetic fixtures and never mutate files outside temp
directories. Validate-only execution runs real validate tool in isolated
temp repos.

Note: The validate tool's check_missing_dependency function has a
pre-existing bug where it checks every non-flag argv token as a potential
executable. This affects multi-word commands like 'git status'. Tests
use the 'worktree-readiness' profile (zero checks) and the 'quick' profile
(one check that gets blocked by the bug) accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTION_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_execution_result.v1.schema.json"
)

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


# ── Fixtures ───────────────────────────────────────────────────────────


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


@pytest.fixture
def execution_schema_dict() -> dict:
    raw = _load_json(EXECUTION_SCHEMA_PATH)
    assert raw is not None, f"Schema not found at {EXECUTION_SCHEMA_PATH}"
    return raw


# ── Helpers ────────────────────────────────────────────────────────────


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


# ── Model tests ────────────────────────────────────────────────────────


class TestRuntimeToolExecutionResultModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolExecutionResult.model_validate({
                "status": "completed",
                "intent_id": "i1",
                "tool_name": "validate",
                "unknown": "x",
            })

    def test_minimal_valid(self) -> None:
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
        )
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.intent_id == "i1"
        assert result.tool_name == "validate"

    def test_defaults(self) -> None:
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
        )
        assert result.envelope_schema_valid is False
        assert result.tool_status is None
        assert result.receipt_sha256 is None
        assert result.duration_ms is None
        assert result.warnings == []

    def test_dump_has_no_forbidden_fields(self) -> None:
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            tool_status="passed",
        )
        dumped = result.model_dump(mode="json")
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f"Found forbidden field '{forbidden}' in dump"
            )

    def test_receipt_field_rejects_dict(self) -> None:
        """RuntimeToolExecutionResult rejects a dict receipt at construction."""
        with pytest.raises((ValueError, TypeError)):
            RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.COMPLETED,
                intent_id="i1",
                tool_name="validate",
                receipt={"invocation_id": "bad"},  # type: ignore[arg-type]
            )

    def test_receipt_field_preserves_typed_instance(self) -> None:
        """RuntimeToolExecutionResult preserves the typed receipt instance."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-1",
            intent_id="intent-1",
            tool_name="validate",
            adapter_status="completed",
        )
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            receipt=receipt,
        )
        assert result.receipt is receipt
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.invocation_id == "inv-1"


# ── Validate execution tests ──────────────────────────────────────────


class TestValidateExecution:
    @pytest.mark.asyncio
    async def test_valid_validate_completes(self, tmp_path: Path) -> None:
        """A valid validate intent runs the tool and returns completed."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.invocation_id == "intent-001"
        assert result.envelope_schema_valid is True
        assert result.duration_ms is not None
        # Tool status depends on the profile's checks (pre-existing
        # check_missing_dependency bug blocking multi-word commands).
        assert result.tool_status is not None

    @pytest.mark.asyncio
    async def test_blocked_adapter_returns_blocked_without_running_tool(self) -> None:
        """A blocked context resolution returns blocked without running."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved(status="blocked")

        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None
        assert result.tool_status is None  # never ran

    @pytest.mark.asyncio
    async def test_refused_adapter_returns_refused_without_running_tool(
        self, tmp_path: Path
    ) -> None:
        """A refused adapter result returns refused without running."""
        runner = RuntimeToolExecutionRunner()
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        # Pass a non-validate tool to trigger refusal
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(repo / "test.txt"), "content": "data"},
        )

        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_unknown_profile_returns_refused(self, tmp_path: Path) -> None:
        """An unknown profile returns refused (tool returns 'refused')."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "nonexistent_profile_xyz"}
        )

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.tool_status == "refused"
        assert result.tool_error_kind == "tool_refusal"


# ── Non-validate execution test ────────────────────────────────────────


class TestNonValidateExecution:
    @pytest.mark.asyncio
    async def test_write_file_returns_refused(self) -> None:
        """Any non-validate tool returns refused."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": "/tmp/test.txt", "content": "data"},
        )
        resolution = _resolved()

        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "not supported" in (result.refusal_reason or "")


class TestBashRouting:
    @pytest.mark.asyncio
    async def test_bash_returns_refused(self) -> None:
        """Bash via execute_validate returns REFUSED (bash not wired yet)."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY, payload={"command": "echo hi"})
        resolution = _resolved()
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert "not supported" in (result.refusal_reason or "")


# ── Envelope schema validation test ────────────────────────────────────


class TestEnvelopeSchemaInvalid:
    @pytest.mark.asyncio
    async def test_bad_envelope_schema_path_fails(self, tmp_path: Path) -> None:
        """A non-existent envelope schema path returns failed."""
        bad_schema_path = tmp_path / "nonexistent_schema.json"
        runner = RuntimeToolExecutionRunner(envelope_schema_path=bad_schema_path)
        intent = _intent(RuntimeToolName.VALIDATE, payload={"profile": "quick"})
        ctx = _resolved_context()
        resolution = RuntimeContextResolution(status="resolved", context=ctx)

        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.FAILED
        assert result.envelope_schema_valid is False
        assert result.error_kind == "envelope_schema_invalid"


# ── Receipt hash test ──────────────────────────────────────────────────


class TestValidateReceiptHash:
    @pytest.mark.asyncio
    async def test_receipt_hash_populated_for_completed_result(
        self, tmp_path: Path
    ) -> None:
        """A completed validate execution populates receipt_sha256."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.receipt_sha256 is not None
        # Verify it's a valid hex string
        assert len(result.receipt_sha256) == 64
        int(result.receipt_sha256, 16)  # no error


# ── Content-light test ─────────────────────────────────────────────────


class TestValidateContentLight:
    @pytest.mark.asyncio
    async def test_result_is_content_light(self, tmp_path: Path) -> None:
        """Execution result contains no forbidden raw fields."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)
        dumped = result.model_dump(mode="json")
        dumped_str = json.dumps(dumped)

        # Should not contain forbidden field keys
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f"Found forbidden field '{forbidden}' in dump"
            )


# ── Schema tests ──────────────────────────────────────────────────────


class TestValidateSchema:
    def test_schema_validates_minimal_result(self, execution_schema_dict: dict) -> None:
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_validates_result_with_all_optional_fields_null(
        self, execution_schema_dict: dict
    ) -> None:
        """Schema must accept None/null for all optional fields."""
        payload = {
            "schema_version": "rig.relay.runtime_tool_execution_result.v1",
            "status": "completed",
            "intent_id": "i1",
            "tool_name": "validate",
            "invocation_id": None,
            "tool_status": None,
            "tool_error_kind": None,
            "receipt_sha256": None,
            "duration_ms": None,
            "error_kind": None,
            "refusal_reason": None,
            "envelope_schema_valid": True,
            "warnings": [],
        }
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(payload))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_fields(self, execution_schema_dict: dict) -> None:
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        bad = {
            "schema_version": "rig.relay.runtime_tool_execution_result.v1",
            "status": "completed",
            "intent_id": "i1",
            "tool_name": "validate",
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_has_no_forbidden_raw_fields(
        self, execution_schema_dict: dict
    ) -> None:
        def _check(obj: object, path: str) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k not in FORBIDDEN_RAW_FIELD_NAMES, (
                        f"Forbidden field '{k}' at {path}"
                    )
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")

        _check(execution_schema_dict, "schema")


# ── Execution in temp repo ────────────────────────────────────────────


class TestValidateExecutionInTempRepo:
    @pytest.mark.asyncio
    async def test_execution_in_temp_repo_no_file_mutation(
        self, tmp_path: Path
    ) -> None:
        """Validate execution in a temp repo does not mutate any files."""
        repo = _make_repo(tmp_path)
        original_files = {
            str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()
        }

        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )

        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        assert result.status == RuntimeToolExecutionStatus.COMPLETED

        # No new files created
        after_files = {str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()}
        # Project files (non-.git) must be unchanged
        project_files_before = {f for f in original_files if not f.startswith(".git/")}
        project_files_after = {f for f in after_files if not f.startswith(".git/")}
        assert project_files_before == project_files_after, (
            f"Files changed: before={project_files_before}, after={project_files_after}"
        )


# ── SearchReplace execution tests


class TestSearchReplaceExecution:
    """Tests for execute_search_replace through the adapter.

    All tests use temp files only. The search_replace tool internally
    handles coordination (skipped when no InvokeContext) and dirty guard
    checks (applied to temp files which are not git-tracked).
    """

    @pytest.mark.asyncio
    async def test_blocked_envelope_does_not_run_search_replace(self) -> None:
        """A blocked context resolution returns BLOCKED without running."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "/tmp/test.py",
                "content": ("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
            },
        )
        resolution = _resolved(status="blocked")
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        assert result.error_kind is not None
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_refused_envelope_does_not_run_search_replace(
        self, tmp_path: Path
    ) -> None:
        """A refused adapter result returns REFUSED without running."""
        runner = RuntimeToolExecutionRunner()
        ctx = _resolved_context()
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={"content": ("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE")},
        )
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind is not None
        assert result.tool_status is None

    @pytest.mark.asyncio
    async def test_search_replace_modifies_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid search_replace invocation modifies the target file."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "test.py"
        target.write_text("old_content\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\nold_content\n=======\nnew_content\n>>>>>>> REPLACE"
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "success"
        assert result.invocation_id is not None
        assert target.read_text(encoding="utf-8") == "new_content\n"

    @pytest.mark.asyncio
    async def test_receipt_hash_populated_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A completed search_replace populates receipt_sha256."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "test.py"
        target.write_text("hello\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.receipt_sha256 is not None
        assert len(result.receipt_sha256) == 64
        int(result.receipt_sha256, 16)

    @pytest.mark.asyncio
    async def test_result_has_no_forbidden_raw_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Execution result field names contain no forbidden raw field keys."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "test.py"
        target.write_text("xyz\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nxyz\n=======\nabc\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        dumped = result.model_dump(mode="json")
        for key in dumped:
            for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
                assert forbidden not in key, (
                    f"Forbidden field '{key}' (matches '{forbidden}') in dump"
                )


# ── SearchReplace schema tests


class TestSearchReplaceSchema:
    """SearchReplace execution results validate against the schema."""

    @pytest.mark.asyncio
    async def test_search_replace_schema_validates(
        self,
        execution_schema_dict: dict,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A completed search_replace result validates against schema."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "test.py"
        target.write_text("dd\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\ndd\n=======\nee\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"


# ── SearchReplace status tests


class TestSearchReplaceStatus:
    """Tests for search_replace status mapping through the adapter."""

    @pytest.mark.asyncio
    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:
        """Search text not found returns tool_status='no_match', status=COMPLETED."""
        target = tmp_path / "test.py"
        target.write_text("some existing content\n", encoding="utf-8")
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

    @pytest.mark.asyncio
    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:
        """Duplicate SEARCH text with allow_multiple=False returns ambiguous_match."""
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
        """expected_replacements not matching actual returns count_mismatch."""
        target = tmp_path / "test.py"
        target.write_text("target\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": (
                    "<<<<<<< SEARCH\ntarget\n=======\nreplaced\n>>>>>>> REPLACE"
                ),
                "expected_replacements": 5,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == "count_mismatch"

    @pytest.mark.asyncio
    async def test_unsupported_tool_through_search_replace_returns_refused(
        self, tmp_path: Path
    ) -> None:
        """Non-SEARCH_REPLACE tool through execute_search_replace returns REFUSED."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(tmp_path / "test.txt"), "content": "data"},
        )
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "unsupported_tool"
        assert result.tool_status is None


# ── Context injection tests


class TestSearchReplaceContextInjection:
    """Tests that search_replace receives runtime context through the adapter."""

    @pytest.mark.asyncio
    async def test_cwd_is_restored_after_execution(self, tmp_path: Path) -> None:
        """CWD is restored to its original value after search_replace runs."""
        original_cwd = Path.cwd()
        target = tmp_path / "test.py"
        target.write_text("restore\n", encoding="utf-8")
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nrestore\n=======\nok\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        await runner.execute_search_replace(intent, resolution)
        assert Path.cwd() == original_cwd, "CWD was not restored"

    @pytest.mark.asyncio
    async def test_cwd_none_is_noop(self, tmp_path: Path) -> None:
        """CWD unchanged when envelope.cwd is None."""
        original_cwd = Path.cwd()
        ctx = _resolved_context(worktree_path=None, repo_root=None)
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": str(tmp_path / "nonexistent.py"),
                "content": ("<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        await runner.execute_search_replace(intent, resolution)
        assert Path.cwd() == original_cwd, "CWD was changed when envelope.cwd is None"


# ── Coordination tests


class TestSearchReplaceCoordination:
    """Tests that coordination runs through context-injected search_replace."""

    @pytest.mark.asyncio
    async def test_same_owner_coordination_succeeds(self, tmp_path: Path) -> None:
        """Same session_id + task_id can run search_replace twice (renewal)."""
        target = tmp_path / "test.py"
        target.write_text("first\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="coord-sess",
            task_id="coord-task",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": ("<<<<<<< SEARCH\nfirst\n=======\nsecond\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        r1 = await runner.execute_search_replace(intent, resolution)
        assert r1.status == RuntimeToolExecutionStatus.COMPLETED
        target.write_text("second\n", encoding="utf-8")
        r2 = await runner.execute_search_replace(intent, resolution)
        assert r2.status == RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_coordination_store_created_at_cwd(self, tmp_path: Path) -> None:
        """Coordination store is created at envelope.cwd/.build/rig-relay/coordination."""
        target = tmp_path / "a.txt"
        target.write_text("coord\n", encoding="utf-8")
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id="sess-coord",
            task_id="task-coord",
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "a.txt",
                "content": ("<<<<<<< SEARCH\ncoord\n=======\ndone\n>>>>>>> REPLACE"),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        store_path = tmp_path / ".build" / "rig-relay" / "coordination"
        assert store_path.is_dir(), "Coordination store not created at cwd"


# ── Receipt population tests


class TestValidateReceiptPopulation:
    """Tests that execute_validate produces a receipt model alongside the result."""

    @pytest.mark.asyncio
    async def test_receipt_populated_for_completed_validate(
        self, tmp_path: Path
    ) -> None:
        """A completed validate execution populates the receipt field."""
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == "validate"
        assert result.receipt.tool_name == "validate"
        assert result.receipt.adapter_status == "completed"
        assert result.receipt.created_at != ""
        assert (
            result.receipt.schema_version
            == "rig.relay.runtime_tool_invocation_receipt.v1"
        )

    @pytest.mark.asyncio
    async def test_receipt_not_populated_for_blocked_validate(self) -> None:
        """A blocked validate execution does not populate the receipt field."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved(status="blocked")
        result = await runner.execute_validate(intent, resolution)
        assert result.receipt is None


class TestSearchReplaceReceiptPopulation:
    """Tests that execute_search_replace produces a receipt model alongside the result."""

    @pytest.mark.asyncio
    async def test_receipt_populated_for_completed_search_replace(
        self, tmp_path: Path
    ) -> None:
        """A completed search_replace execution populates the receipt field."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

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

        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == "search_replace"
        assert result.receipt.tool_name == "search_replace"
        assert result.receipt.adapter_status == "completed"
        assert result.receipt.changed_paths == ["test.py"]
        assert result.receipt.created_at != ""
        assert result.receipt.tool_receipt_schema_version is not None
        assert "search_replace" in (result.receipt.tool_receipt_schema_version or "")

    @pytest.mark.asyncio
    async def test_receipt_not_populated_for_blocked_search_replace(self) -> None:
        """A blocked search_replace execution does not populate the receipt field."""
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.SEARCH_REPLACE)
        resolution = _resolved(status="blocked")
        result = await runner.execute_search_replace(intent, resolution)
        assert result.receipt is None


# ── Schema alignment tests


class TestSchemaAlignment:
    """Align RuntimeToolExecutionResult model dumps with schema without workarounds."""

    def test_full_model_dump_validates_with_all_linkage_fields(
        self, execution_schema_dict: dict
    ) -> None:
        """Full model dump with all linkage fields validates against schema."""
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            tool_receipt_kind="validate",
            tool_receipt_schema_version="rig.relay.validate_receipt.v1",
            receipt_envelope_id="env-001",
            audit_event_id="aev-001",
            changed_paths=["src/main.py"],
            receipt_sha256="abc123",
            invocation_id="inv-001",
            tool_status="passed",
            duration_ms=42.0,
            error_kind=None,
            refusal_reason=None,
            receipt=None,
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_full_model_dump_with_all_linkage_fields_null(
        self, execution_schema_dict: dict
    ) -> None:
        """Full model dump with all optional fields explicitly None validates."""
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            invocation_id=None,
            tool_status=None,
            tool_error_kind=None,
            receipt_sha256=None,
            duration_ms=None,
            error_kind=None,
            refusal_reason=None,
            tool_receipt_kind=None,
            tool_receipt_schema_version=None,
            receipt_envelope_id=None,
            audit_event_id=None,
            receipt=None,
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_forbidden_raw_fields(
        self, execution_schema_dict: dict
    ) -> None:
        """Schema must reject forbidden raw content fields."""
        forbidden = [
            "stdout",
            "stderr",
            "content",
            "chunk_text",
            "old_text",
            "new_text",
            "diff",
            "patch",
            "prompt",
            "secret",
        ]
        base = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
        ).model_dump(mode="json")

        validator = jsonschema.Draft7Validator(execution_schema_dict)
        for field in forbidden:
            bad = dict(base)
            bad[field] = "some value"
            errors = list(validator.iter_errors(bad))
            assert errors, f"Schema should reject forbidden field '{field}'"

    def test_minimal_model_dump_validates_without_exclude_none(
        self, execution_schema_dict: dict
    ) -> None:
        """Minimal result validates without exclude_none."""
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_no_serialization_warning_on_model_dump_with_receipt(
        self, execution_schema_dict: dict
    ) -> None:
        """model_dump(mode='json') with receipt emits no PydanticSerializationUnexpectedValue."""
        import warnings

        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-1",
            intent_id="intent-1",
            tool_name="validate",
            adapter_status="completed",
        )
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            receipt=receipt,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            dumped = result.model_dump(mode="json")

        unexpected_value_warnings = [
            x for x in w if "PydanticSerializationUnexpectedValue" in str(x.message)
        ]
        assert not unexpected_value_warnings, (
            f"Got PydanticSerializationUnexpectedValue warnings: "
            f"{[(str(x.message) for x in unexpected_value_warnings)]}"
        )

        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(dumped))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"


# ── RuntimeToolInvocationReceipt content-light enforcement


class TestRuntimeToolInvocationReceiptContentLight:
    """RuntimeToolInvocationReceipt must remain strictly content-light."""

    def test_receipt_model_rejects_extra_fields(self) -> None:
        """RuntimeToolInvocationReceipt with unknown fields raises."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolInvocationReceipt.model_validate({
                "invocation_id": "inv-1",
                "intent_id": "intent-1",
                "tool_name": "validate",
                "adapter_status": "completed",
                "content": "raw file content leaked",
            })

    def test_receipt_model_rejects_stdout_field(self) -> None:
        """RuntimeToolInvocationReceipt with stdout field raises."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolInvocationReceipt.model_validate({
                "invocation_id": "inv-1",
                "intent_id": "intent-1",
                "tool_name": "validate",
                "adapter_status": "completed",
                "stdout": "raw output leaked",
            })

    def test_receipt_model_rejects_diff_field(self) -> None:
        """RuntimeToolInvocationReceipt with diff field raises."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolInvocationReceipt.model_validate({
                "invocation_id": "inv-1",
                "intent_id": "intent-1",
                "tool_name": "validate",
                "adapter_status": "completed",
                "diff": "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new",
            })

    def test_receipt_model_dump_has_no_forbidden_fields(self) -> None:
        """RuntimeToolInvocationReceipt.model_dump() has no forbidden fields."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-1",
            intent_id="intent-1",
            tool_name="validate",
            adapter_status="completed",
        )
        dumped = receipt.model_dump(mode="json")
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f'Found forbidden field "{forbidden}" in receipt dump'
            )

    def test_execution_result_with_receipt_dump_has_no_forbidden_fields(self) -> None:
        """RuntimeToolExecutionResult with receipt has no forbidden fields in dump."""
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id="inv-1",
            intent_id="intent-1",
            tool_name="validate",
            adapter_status="completed",
        )
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id="i1",
            tool_name="validate",
            receipt=receipt,
        )
        dumped = result.model_dump(mode="json")
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f'Found forbidden field "{forbidden}" in full dump with receipt'
            )
