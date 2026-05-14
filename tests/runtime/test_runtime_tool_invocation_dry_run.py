"""Tests for rig_relay.runtime.tool_invocation_dry_run — dry-run models, runner, schema.

All tests use synthetic fixtures and never execute tools, acquire leases,
or mutate files. Dry-run results are content-light.
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.projection import _load_json
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_dry_run import (
    RuntimeToolDryRunResult,
    RuntimeToolDryRunRunner,
    RuntimeToolDryRunStatus,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DRY_RUN_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_invocation_dry_run.v1.schema.json"
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
def schema_dict() -> dict:
    raw = _load_json(DRY_RUN_SCHEMA_PATH)
    assert raw is not None
    return raw


# ── Model tests ────────────────────────────────────────────────────────


class TestRuntimeToolDryRunResultModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeToolDryRunResult.model_validate({
                "status": "would_prepare",
                "intent_id": "i1",
                "tool_name": "validate",
                "unknown": "x",
            })

    def test_minimal_valid(self) -> None:
        result = RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            intent_id="i1",
            tool_name="validate",
        )
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE
        assert not result.would_execute
        assert not result.would_acquire_lease

    def test_defaults(self) -> None:
        result = RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            intent_id="i1",
            tool_name="write_file",
        )
        assert result.envelope_schema_valid is False
        assert result.tool_schema_valid is None
        assert result.would_execute is False
        assert result.would_mutate is False
        assert result.would_acquire_lease is False
        assert result.requested_paths == []
        assert result.warnings == []

    def test_dump_has_no_forbidden_fields(self) -> None:
        result = RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            intent_id="i1",
            tool_name="validate",
            requested_paths=["/tmp/test"],
        )
        dumped = result.model_dump(mode="json")
        dumped_str = str(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f"Found forbidden field '{forbidden}' in dump"
            )


# ── Runner tests — validate ──────────────────────────────────────────


class TestValidateDryRun:
    def test_successful_validate_dry_run_returns_would_prepare_and_schema_valid(
        self,
    ) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(
            RuntimeToolName.VALIDATE,
            payload={"profile": "python", "paths": ["/tmp/repo/src"]},
        )
        resolution = _resolved()

        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE
        assert result.envelope_schema_valid is True
        assert result.tool_schema_valid is True
        assert result.would_execute is False
        assert result.would_mutate is False
        assert result.would_acquire_lease is False

    def test_unresolved_context_returns_blocked(self) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved(status="blocked")

        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.BLOCKED
        assert result.error_kind is not None


# ── Runner tests — write_file ─────────────────────────────────────────


class TestWriteFileDryRun:
    def test_write_file_classifies_would_mutate_but_does_not_create_file(
        self, tmp_path: Path
    ) -> None:
        runner = RuntimeToolDryRunRunner()
        target = tmp_path / "should_not_exist.txt"
        assert not target.exists()

        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "new content"},
        )
        resolution = _resolved()

        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE
        assert result.would_mutate is True
        assert result.would_execute is False
        # File must NOT exist after dry run
        assert not target.exists(), "Dry run created a file!"

    def test_write_file_without_content_returns_refused(self) -> None:
        """Adapter refuses write_file without content before dry-run validates."""
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.WRITE_FILE, payload={"path": "/tmp/test.txt"})
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        # Adapter catches this before dry-run tool validation
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.error_kind == "invalid_payload"


# ── Runner tests — search_replace ─────────────────────────────────────


class TestSearchReplaceDryRun:
    def test_search_replace_classifies_would_mutate_but_does_not_modify_file(
        self, tmp_path: Path
    ) -> None:
        runner = RuntimeToolDryRunRunner()
        target = tmp_path / "test.txt"
        target.write_text("original")

        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": str(target),
                "content": "<<<<<<< SEARCH\noriginal\n=======\nmodified\n>>>>>>> REPLACE",
            },
        )
        resolution = _resolved()

        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE
        assert result.would_mutate is True
        assert result.would_execute is False
        # File must be unchanged after dry run
        assert target.read_text() == "original", "Dry run modified a file!"

    def test_search_replace_without_file_path_returns_refused(self) -> None:
        """Adapter refuses search_replace without file_path before dry-run validates."""
        runner = RuntimeToolDryRunRunner()
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE, payload={"content": "SEARCH/REPLACE block"}
        )
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.error_kind == "invalid_payload"


# ── Runner tests — runtime_exec ───────────────────────────────────────


class TestRuntimeExecDryRun:
    def test_runtime_exec_validates_execution_request_shape_and_does_not_execute(
        self,
    ) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "argv": ["python3", "-c", "print('hi')"],
                "timeout_ms": 5000,
                "purpose": "test dry run",
            },
        )
        resolution = _resolved()

        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE
        assert result.would_execute is False
        assert result.would_acquire_lease is False
        assert result.envelope_schema_valid is True

    def test_runtime_exec_without_argv_returns_refused(self) -> None:
        """Adapter refuses runtime_exec without argv before dry-run validates."""
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.RUNTIME_EXEC, payload={"timeout_ms": 5000})
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.error_kind == "invalid_payload"

    def test_runtime_exec_empty_argv_returns_refused(self) -> None:
        """Adapter refuses runtime_exec with empty argv before dry-run validates."""
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.RUNTIME_EXEC, payload={"argv": []})
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.error_kind == "invalid_payload"


# ── Runner tests — bash_legacy ────────────────────────────────────────


class TestBashLegacyDryRun:
    def test_bash_legacy_remains_refused(self) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.BASH_LEGACY, payload={"command": "rm -rf /"})
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.would_execute is False
        assert result.would_acquire_lease is False


# ── Runner tests — edge cases ─────────────────────────────────────────


class TestDryRunEdgeCases:
    def test_unresolved_context_returns_blocked(self) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved(status="blocked")
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.BLOCKED

    def test_unsafe_path_returns_refused(self) -> None:
        runner = RuntimeToolDryRunRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": "/etc/passwd", "content": "hack"},
            requested_paths=["/etc/passwd"],
        )
        # Build a context with explicit worktree/repo so adapter can detect unsafe
        ctx = _resolved_context(
            worktree_path="/tmp/worktrees/ws-001", repo_root="/tmp/repo"
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = runner.dry_run(intent, resolution)
        assert result.status == RuntimeToolDryRunStatus.REFUSED
        assert result.would_mutate is True
        assert result.would_execute is False

    def test_missing_profile_defaults_to_quick(self) -> None:
        """Adapter defaults to 'quick' profile when none provided."""
        runner = RuntimeToolDryRunRunner()
        intent = _intent(RuntimeToolName.VALIDATE, payload={"not_profile": "quick"})
        resolution = _resolved()
        result = runner.dry_run(intent, resolution)
        # Adapter normalizes missing profile to 'quick'
        assert result.status == RuntimeToolDryRunStatus.WOULD_PREPARE


# ── Schema tests ──────────────────────────────────────────────────────


class TestDryRunSchema:
    def test_schema_validates_minimal_result(self, schema_dict: dict) -> None:
        result = RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            intent_id="i1",
            tool_name="validate",
        )
        validator = jsonschema.Draft7Validator(schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_unknown_fields(self, schema_dict: dict) -> None:
        validator = jsonschema.Draft7Validator(schema_dict)
        bad = {
            "schema_version": "rig.relay.runtime_tool_invocation_dry_run.v1",
            "status": "would_prepare",
            "intent_id": "i1",
            "tool_name": "validate",
            "unknown_field": "x",
        }
        errors = list(validator.iter_errors(bad))
        assert any("unknown_field" in str(e.message) for e in errors)

    def test_schema_has_no_forbidden_raw_fields(self, schema_dict: dict) -> None:
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

        _check(schema_dict, "schema")
