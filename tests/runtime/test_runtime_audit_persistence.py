"""Tests for RuntimeAuditEvent model, builder, persistence store, and content-light enforcement.

All tests use temp directories — never write to real user paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.runtime_audit_event import (
    RuntimeAuditEvent,
    RuntimeAuditPersistenceStore,
    build_runtime_audit_event,
)
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)

# ── Constants ──────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.runtime_audit_event.v1.schema.json"
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
    "prompt",
    "secret",
    "argv",
})


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def audit_schema_dict() -> dict:
    raw = json.loads(AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert raw is not None, f"Schema not found at {AUDIT_SCHEMA_PATH}"
    return raw


def _make_result(
    status: RuntimeToolExecutionStatus = RuntimeToolExecutionStatus.COMPLETED,
    **overrides: object,
) -> RuntimeToolExecutionResult:
    kwargs: dict[str, object] = {
        "status": status,
        "intent_id": "intent-001",
        "tool_name": "validate",
    }
    kwargs.update(overrides)
    return RuntimeToolExecutionResult(**kwargs)  # type: ignore[arg-type]


def _make_store(tmp_path: Path) -> RuntimeAuditPersistenceStore:
    return RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")


import subprocess


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
        '[project]\nname = "test"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    return repo


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


# ── Model tests ────────────────────────────────────────────────────────


class TestRuntimeAuditEventModel:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            RuntimeAuditEvent.model_validate({
                "schema_version": "rig.relay.runtime_audit_event.v1",
                "audit_event_id": "aev-001",
                "invocation_id": "inv-001",
                "tool_name": "validate",
                "status": "completed",
                "unknown_field": "x",
            })

    def test_minimal_valid(self) -> None:
        event = RuntimeAuditEvent(
            audit_event_id="aev-001",
            invocation_id="inv-001",
            tool_name="validate",
            status="completed",
        )
        assert event.schema_version == "rig.relay.runtime_audit_event.v1"
        assert event.audit_event_id == "aev-001"
        assert event.invocation_id == "inv-001"
        assert event.tool_name == "validate"
        assert event.status == "completed"

    def test_context_propagation_fields(self) -> None:
        event = RuntimeAuditEvent(
            audit_event_id="aev-002",
            invocation_id="inv-002",
            tool_name="search_replace",
            status="completed",
            mission_id="mission-001",
            agent_id="agent-001",
            lease_id="lease-001",
            parent_event_id="aev-001",
        )
        assert event.mission_id == "mission-001"
        assert event.agent_id == "agent-001"
        assert event.lease_id == "lease-001"
        assert event.parent_event_id == "aev-001"


# ── Builder tests ──────────────────────────────────────────────────────


class TestBuildRuntimeAuditEvent:
    def test_build_from_completed_result(self) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="passed",
            invocation_id="inv-001",
            receipt_sha256="sha256:abc",
            duration_ms=42.0,
            changed_paths=[],
            tool_receipt_kind="validate",
            tool_receipt_schema_version="rig.relay.validate_receipt.v1",
        )
        event = build_runtime_audit_event(result)
        assert event.tool_name == "validate"
        assert event.status == "completed"
        assert event.tool_status == "passed"
        assert event.invocation_id == "inv-001"
        assert event.receipt_sha256 == "sha256:abc"
        assert event.duration_ms == 42.0
        assert event.tool_receipt_kind == "validate"
        assert event.runtime_result_sha256 is not None
        assert event.runtime_result_sha256.startswith("sha256:")

    def test_runtime_result_sha256_changes_when_result_changes(self) -> None:
        result_a = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="passed",
        )
        result_b = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="failed",
        )
        event_a = build_runtime_audit_event(result_a)
        event_b = build_runtime_audit_event(result_b)
        assert event_a.runtime_result_sha256 != event_b.runtime_result_sha256

    def test_build_from_blocked_result(self) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.BLOCKED,
            tool_name="search_replace",
            error_kind="session_required",
            refusal_reason="session_id is required",
        )
        event = build_runtime_audit_event(result)
        assert event.status == "blocked"
        assert event.error_kind == "session_required"
        assert event.refusal_reason is not None

    def test_build_from_refused_result(self) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.REFUSED,
            tool_name="write_file",
            error_kind="unsupported_tool",
            refusal_reason="write_file not supported",
        )
        event = build_runtime_audit_event(result)
        assert event.status == "refused"
        assert event.error_kind == "unsupported_tool"


# ── Persistence store tests ────────────────────────────────────────────


class TestRuntimeAuditPersistenceStore:
    def test_append_and_read(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        event = RuntimeAuditEvent(
            audit_event_id="aev-001",
            invocation_id="inv-001",
            tool_name="validate",
            status="completed",
        )
        returned = store.append(event)
        assert returned is event
        events = store.read_events()
        assert len(events) == 1
        assert events[0].audit_event_id == "aev-001"

    def test_append_multiple_events(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for i in range(5):
            store.append(
                RuntimeAuditEvent(
                    audit_event_id=f"aev-{i:03d}",
                    invocation_id=f"inv-{i:03d}",
                    tool_name="validate",
                    status="completed",
                )
            )
        events = store.read_events()
        assert len(events) == 5

    def test_empty_store_returns_empty_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        events = store.read_events()
        assert events == []

    def test_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.count() == 0
        store.append(
            RuntimeAuditEvent(
                audit_event_id="aev-001",
                invocation_id="inv-001",
                tool_name="validate",
                status="completed",
            )
        )
        assert store.count() == 1

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "audit.jsonl"
        store = RuntimeAuditPersistenceStore(nested)
        store.append(
            RuntimeAuditEvent(
                audit_event_id="aev-001",
                invocation_id="inv-001",
                tool_name="validate",
                status="completed",
            )
        )
        assert nested.is_file()

    def test_persisted_event_is_valid_json(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.append(
            RuntimeAuditEvent(
                audit_event_id="aev-001",
                invocation_id="inv-001",
                tool_name="validate",
                status="completed",
            )
        )
        line = store.path.read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        assert parsed["audit_event_id"] == "aev-001"
        assert parsed["invocation_id"] == "inv-001"


# ── Content-light enforcement tests ────────────────────────────────────


class TestRuntimeAuditEventContentLight:
    def test_event_model_rejects_raw_fields(self) -> None:
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            with pytest.raises(ValueError, match="Extra inputs are not permitted"):
                RuntimeAuditEvent.model_validate({
                    "schema_version": "rig.relay.runtime_audit_event.v1",
                    "audit_event_id": "aev-001",
                    "invocation_id": "inv-001",
                    "tool_name": "validate",
                    "status": "completed",
                    forbidden: "some raw value",
                })

    def test_event_dump_has_no_forbidden_fields(self) -> None:
        event = RuntimeAuditEvent(
            audit_event_id="aev-001",
            invocation_id="inv-001",
            tool_name="validate",
            status="completed",
        )
        dumped = json.dumps(event.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in audit event dump"
            )

    def test_built_event_has_no_forbidden_fields(self) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="passed",
        )
        event = build_runtime_audit_event(result)
        dumped = json.dumps(event.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in built audit event dump"
            )

    def test_persisted_content_has_no_forbidden_fields(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="passed",
        )
        event = build_runtime_audit_event(result)
        store.append(event)
        persisted = store.path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in persisted, (
                f"Found forbidden field '{forbidden}' in persisted audit data"
            )


# ── Schema validation tests ────────────────────────────────────────────


class TestRuntimeAuditEventSchema:
    def test_minimal_event_validates(self, audit_schema_dict: dict) -> None:
        event = RuntimeAuditEvent(
            audit_event_id="aev-001",
            invocation_id="inv-001",
            tool_name="validate",
            status="completed",
        )
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_full_event_validates(self, audit_schema_dict: dict) -> None:
        event = RuntimeAuditEvent(
            audit_event_id="aev-002",
            invocation_id="inv-002",
            tool_name="search_replace",
            status="completed",
            tool_status="success",
            receipt_sha256="sha256:abc123",
            runtime_result_sha256="sha256:def456",
            changed_paths=["src/main.py"],
            duration_ms=42.0,
            error_kind=None,
            refusal_reason=None,
            tool_receipt_kind="search_replace",
            tool_receipt_schema_version="rig.relay.search_replace_receipt.v1",
            mission_id="mission-001",
            agent_id="agent-001",
            lease_id="lease-001",
            parent_event_id="aev-001",
            created_at="2026-05-14T00:00:00",
        )
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_built_event_validates(self, audit_schema_dict: dict) -> None:
        result = _make_result(
            status=RuntimeToolExecutionStatus.COMPLETED,
            tool_name="validate",
            tool_status="passed",
            invocation_id="inv-003",
        )
        event = build_runtime_audit_event(result)
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(event.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_forbidden_fields(self, audit_schema_dict: dict) -> None:
        base = RuntimeAuditEvent(
            audit_event_id="aev-001",
            invocation_id="inv-001",
            tool_name="validate",
            status="completed",
        ).model_dump(mode="json")
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            bad = dict(base)
            bad[forbidden] = "some raw value"
            errors = list(validator.iter_errors(bad))
            assert errors, f"Schema should reject forbidden field '{forbidden}'"


class TestAuditPersistenceFromValidateExecution:
    """Integration: execute_validate persists exactly one content-light audit event."""

    @pytest.mark.asyncio
    async def test_validate_persists_one_event(self, tmp_path: Path) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-int-001",
            task_id="task-int-001",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        events = store.read_events()
        assert len(events) == 1
        event = events[0]
        assert event.tool_name == "validate"
        assert event.status == "completed"
        assert event.runtime_result_sha256 is not None
        assert event.runtime_result_sha256.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_validate_persisted_event_is_content_light(
        self, tmp_path: Path
    ) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-int-002",
            task_id="task-int-002",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_validate(intent, resolution)
        persisted = store.path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in persisted, (
                f"Found forbidden field '{forbidden}' in persisted audit data"
            )

    @pytest.mark.asyncio
    async def test_validate_persisted_event_meets_schema(
        self, tmp_path: Path, audit_schema_dict: dict
    ) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-int-003",
            task_id="task-int-003",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_validate(intent, resolution)
        events = store.read_events()
        assert len(events) == 1
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(events[0].model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    @pytest.mark.asyncio
    async def test_validate_persists_rejected_blocked_event(
        self, tmp_path: Path
    ) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(RuntimeToolName.VALIDATE)
        blocked_ctx = RuntimeContext(
            session_id="sess-int-004",
            task_id="task-int-004",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        blocked_res = RuntimeContextResolution(
            status="blocked",
            context=blocked_ctx,
            error_kind="session_required",
            refusal_reason="session_id is required",
        )
        result = await runner.execute_validate(intent, blocked_res)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        events = store.read_events()
        assert len(events) == 1
        assert events[0].status == "blocked"

    @pytest.mark.asyncio
    async def test_validate_no_store_does_not_persist(self, tmp_path: Path) -> None:
        runner = RuntimeToolExecutionRunner(audit_store=None)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-int-005",
            task_id="task-int-005",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED


class TestAuditPersistenceFromSearchReplaceExecution:
    """Integration: execute_search_replace persists exactly one content-light event."""

    @pytest.mark.asyncio
    async def test_search_replace_persists_one_event(self, tmp_path: Path) -> None:
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        ctx = RuntimeContext(
            session_id="sess-sr-001",
            task_id="task-sr-001",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        events = store.read_events()
        assert len(events) == 1
        assert events[0].tool_name == "search_replace"
        assert events[0].status == "completed"
        assert events[0].changed_paths == ["test.py"]

    @pytest.mark.asyncio
    async def test_search_replace_persisted_event_is_content_light(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        ctx = RuntimeContext(
            session_id="sess-sr-002",
            task_id="task-sr-002",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_search_replace(intent, resolution)
        persisted = store.path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in persisted, (
                f"Found forbidden field '{forbidden}' in persisted audit data"
            )

    @pytest.mark.asyncio
    async def test_search_replace_persisted_event_meets_schema(
        self, tmp_path: Path, audit_schema_dict: dict
    ) -> None:
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        ctx = RuntimeContext(
            session_id="sess-sr-003",
            task_id="task-sr-003",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_search_replace(intent, resolution)
        events = store.read_events()
        assert len(events) == 1
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(events[0].model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    @pytest.mark.asyncio
    async def test_search_replace_persists_blocked_event(self, tmp_path: Path) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(RuntimeToolName.SEARCH_REPLACE)
        ctx = RuntimeContext(
            session_id="sess-sr-004",
            task_id="task-sr-004",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        blocked_res = RuntimeContextResolution(
            status="blocked",
            context=ctx,
            error_kind="session_required",
            refusal_reason="session_id is required",
        )
        result = await runner.execute_search_replace(intent, blocked_res)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        events = store.read_events()
        assert len(events) == 1
        assert events[0].status == "blocked"


class TestAuditPersistenceFromWriteFileExecution:
    """Integration: execute_write_file persists exactly one content-light event."""

    @pytest.mark.asyncio
    async def test_write_file_persists_one_event(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "data\n", "overwrite": False},
        )
        ctx = RuntimeContext(
            session_id="sess-wf-001",
            task_id="task-wf-001",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_write_file(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert target.read_text(encoding="utf-8") == "data\n"
        events = store.read_events()
        assert len(events) == 1
        assert events[0].tool_name == "write_file"
        assert events[0].status == "completed"

    @pytest.mark.asyncio
    async def test_write_file_persisted_event_is_content_light(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "test.txt"
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "data\n", "overwrite": False},
        )
        ctx = RuntimeContext(
            session_id="sess-wf-002",
            task_id="task-wf-002",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_write_file(intent, resolution)
        persisted = store.path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in persisted, (
                f"Found forbidden field '{forbidden}' in persisted audit data"
            )

    @pytest.mark.asyncio
    async def test_write_file_persisted_event_meets_schema(
        self, tmp_path: Path, audit_schema_dict: dict
    ) -> None:
        target = tmp_path / "test.txt"
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={"path": str(target), "content": "data\n", "overwrite": False},
        )
        ctx = RuntimeContext(
            session_id="sess-wf-003",
            task_id="task-wf-003",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_write_file(intent, resolution)
        events = store.read_events()
        assert len(events) == 1
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(events[0].model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    @pytest.mark.asyncio
    async def test_write_file_persists_blocked_event(self, tmp_path: Path) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(RuntimeToolName.WRITE_FILE)
        ctx = RuntimeContext(
            session_id="sess-wf-004",
            task_id="task-wf-004",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        blocked_res = RuntimeContextResolution(
            status="blocked",
            context=ctx,
            error_kind="session_required",
            refusal_reason="session_id is required",
        )
        result = await runner.execute_write_file(intent, blocked_res)
        assert result.status == RuntimeToolExecutionStatus.BLOCKED
        events = store.read_events()
        assert len(events) == 1
        assert events[0].status == "blocked"


class TestBashAuditPersistence:
    """Integration: execute_bash persists exactly one content-light audit event."""

    @pytest.mark.asyncio
    async def test_bash_refused_persists_one_event(self, tmp_path: Path) -> None:
        """Bash is wired but deferred: calls with shell=True are refused."""
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY, payload={"command": "echo ok", "shell": True}
        )
        ctx = RuntimeContext(
            session_id="sess-bash-001",
            task_id="task-bash-001",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_bash(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        events = store.read_events()
        assert len(events) == 1
        assert events[0].tool_name == "bash_legacy"
        assert events[0].status == "refused"

    @pytest.mark.asyncio
    async def test_bash_persisted_event_is_content_light(self, tmp_path: Path) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY, payload={"command": "echo ok", "shell": True}
        )
        ctx = RuntimeContext(
            session_id="sess-bash-002",
            task_id="task-bash-002",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_bash(intent, resolution)
        persisted = store.path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in persisted, (
                f"Found forbidden field '{forbidden}' in persisted audit data"
            )

    @pytest.mark.asyncio
    async def test_bash_persisted_event_meets_schema(
        self, tmp_path: Path, audit_schema_dict: dict
    ) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.BASH_LEGACY, payload={"command": "echo ok", "shell": True}
        )
        ctx = RuntimeContext(
            session_id="sess-bash-003",
            task_id="task-bash-003",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        await runner.execute_bash(intent, resolution)
        events = store.read_events()
        assert len(events) == 1
        validator = jsonschema.Draft7Validator(audit_schema_dict)
        errors = list(validator.iter_errors(events[0].model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"


class TestRuntimeExecNoDoublePersist:
    """runtime_exec dispatches to sub-tools which persist -- no double-persist."""

    @pytest.mark.asyncio
    async def test_runtime_exec_to_validate_produces_one_event(
        self, tmp_path: Path
    ) -> None:
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={"tool_name": "validate", "profile": "worktree-readiness"},
        )
        ctx = RuntimeContext(
            session_id="sess-re-001",
            task_id="task-re-001",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_runtime_exec(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        events = store.read_events()
        assert len(events) == 1, (
            f"Expected exactly 1 audit event, got {len(events)} -- "
            "runtime_exec must not double-persist"
        )

    @pytest.mark.asyncio
    async def test_runtime_exec_to_write_file_produces_one_event(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "test.txt"
        store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.RUNTIME_EXEC,
            payload={
                "tool_name": "write_file",
                "path": str(target),
                "content": "data\n",
                "overwrite": False,
            },
        )
        ctx = RuntimeContext(
            session_id="sess-re-002",
            task_id="task-re-002",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_runtime_exec(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        events = store.read_events()
        assert len(events) == 1, (
            f"Expected exactly 1 audit event, got {len(events)} -- "
            "runtime_exec must not double-persist"
        )


class TestBestEffortAuditPersistence:
    """Store failure must not break execution (best-effort)."""

    @pytest.mark.asyncio
    async def test_broken_store_does_not_fail_execute_validate(
        self, tmp_path: Path
    ) -> None:
        """A store that raises on append should not fail the tool execution."""

        class _BrokenStore(RuntimeAuditPersistenceStore):
            def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
                msg = "Simulated store failure"
                raise RuntimeError(msg)

        store = _BrokenStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-bf-001",
            task_id="task-bf-001",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_broken_store_does_not_fail_search_replace(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "test.py"
        target.write_text("old\n", encoding="utf-8")

        class _BrokenStore(RuntimeAuditPersistenceStore):
            def append(self, event: RuntimeAuditEvent) -> RuntimeAuditEvent:
                msg = "Simulated store failure"
                raise RuntimeError(msg)

        store = _BrokenStore(tmp_path / "audit.jsonl")
        runner = RuntimeToolExecutionRunner(audit_store=store)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "test.py",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        ctx = RuntimeContext(
            session_id="sess-bf-002",
            task_id="task-bf-002",
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert target.read_text(encoding="utf-8") == "new\n"

    @pytest.mark.asyncio
    async def test_no_store_does_not_fail(self, tmp_path: Path) -> None:
        """Runner with audit_store=None should execute normally."""
        runner = RuntimeToolExecutionRunner(audit_store=None)
        repo = _make_repo(tmp_path)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={"profile": "worktree-readiness"}
        )
        ctx = RuntimeContext(
            session_id="sess-bf-003",
            task_id="task-bf-003",
            worktree_path=str(repo),
            repo_root=str(repo),
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        result = await runner.execute_validate(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
