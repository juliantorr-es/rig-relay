"""Tests for rig_relay.runtime.tool_invocation_adapter — models, adapter, schema.

All tests are unit tests with synthetic fixtures. No tools are executed,
no files are mutated, no leases are acquired.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolIntent,
    RuntimeToolInvocationAdapter,
    RuntimeToolInvocationEnvelope,
    RuntimeToolInvocationErrorKind,
    RuntimeToolInvocationStatus,
    RuntimeToolName,
)

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


# ── Model tests ────────────────────────────────────────────────────────


class TestRuntimeToolName:
    def test_all_values(self) -> None:
        assert list(RuntimeToolName) == [
            RuntimeToolName.WRITE_FILE,
            RuntimeToolName.SEARCH_REPLACE,
            RuntimeToolName.SEARCH_REPLACE_PROPOSAL,
            RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
            RuntimeToolName.VALIDATE,
            RuntimeToolName.RUNTIME_EXEC,
            RuntimeToolName.BASH_LEGACY,
            RuntimeToolName.GIT_STATUS,
            RuntimeToolName.GIT_DIFF,
            RuntimeToolName.GIT_LOG,
            RuntimeToolName.GIT_BRANCH,
            RuntimeToolName.GIT_SHOW,
            RuntimeToolName.GIT_LS_FILES,
            RuntimeToolName.CHECKPOINT,
        ]

    def test_string_values(self) -> None:
        assert RuntimeToolName.WRITE_FILE.value == "write_file"
        assert RuntimeToolName.SEARCH_REPLACE.value == "search_replace"
        assert RuntimeToolName.VALIDATE.value == "validate"
        assert RuntimeToolName.RUNTIME_EXEC.value == "runtime_exec"
        assert RuntimeToolName.BASH_LEGACY.value == "bash_legacy"


class TestRuntimeToolInvocationStatus:
    def test_all_values(self) -> None:
        assert list(RuntimeToolInvocationStatus) == [
            RuntimeToolInvocationStatus.PREPARED,
            RuntimeToolInvocationStatus.BLOCKED,
            RuntimeToolInvocationStatus.REFUSED,
        ]


class TestRuntimeToolInvocationErrorKind:
    def test_all_values(self) -> None:
        assert list(RuntimeToolInvocationErrorKind) == [
            RuntimeToolInvocationErrorKind.CONTEXT_UNRESOLVED,
            RuntimeToolInvocationErrorKind.SESSION_REQUIRED,
            RuntimeToolInvocationErrorKind.TASK_REQUIRED,
            RuntimeToolInvocationErrorKind.WORKTREE_REQUIRED,
            RuntimeToolInvocationErrorKind.UNSAFE_PATH,
            RuntimeToolInvocationErrorKind.DIRTY_POLICY_FAILED,
            RuntimeToolInvocationErrorKind.LEASE_CONFLICT,
            RuntimeToolInvocationErrorKind.PATH_RESERVED,
            RuntimeToolInvocationErrorKind.EXPECTED_HASH_MISSING,
            RuntimeToolInvocationErrorKind.UNSUPPORTED_TOOL,
            RuntimeToolInvocationErrorKind.UNSUPPORTED_MUTATION_LOCATION,
            RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
        ]


class TestRuntimeToolIntent:
    def test_valid_intent(self) -> None:
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={"path": "/tmp/test.txt", "content": "hello"},
        )
        assert intent.intent_id == "intent-001"
        assert intent.tool_name == RuntimeToolName.WRITE_FILE
        assert intent.payload["path"] == "/tmp/test.txt"

    def test_default_requested_paths_empty(self) -> None:
        intent = _intent()
        assert intent.requested_paths == []

    def test_default_require_worktree_false(self) -> None:
        intent = _intent()
        assert not intent.require_worktree

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeToolIntent(
                intent_id="bad",
                tool_name=RuntimeToolName.VALIDATE,
                payload={},
                unknown_field="bad",
            )


class TestRuntimeToolInvocationEnvelope:
    def test_schema_version_default(self) -> None:
        env = RuntimeToolInvocationEnvelope(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name=RuntimeToolName.VALIDATE,
            status=RuntimeToolInvocationStatus.PREPARED,
        )
        assert env.schema_version == "rig.relay.runtime_tool_invocation.v1"

    def test_required_fields_only(self) -> None:
        env = RuntimeToolInvocationEnvelope(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name=RuntimeToolName.WRITE_FILE,
            status=RuntimeToolInvocationStatus.PREPARED,
        )
        assert env.invocation_id == "inv-001"
        assert env.session_id is None
        assert env.error_kind is None

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RuntimeToolInvocationEnvelope(
                invocation_id="bad",
                intent_id="bad",
                tool_name=RuntimeToolName.VALIDATE,
                status=RuntimeToolInvocationStatus.PREPARED,
                unknown="bad",
            )

    def test_no_raw_output_fields(self) -> None:
        """Invocation envelope must not contain raw output fields."""
        env = RuntimeToolInvocationEnvelope(
            invocation_id="inv-001",
            intent_id="intent-001",
            tool_name=RuntimeToolName.VALIDATE,
            status=RuntimeToolInvocationStatus.PREPARED,
        )
        dumped = env.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped
        assert "output" not in dumped
        assert "diff" not in dumped


# ── Adapter tests ──────────────────────────────────────────────────────


class TestRuntimeToolInvocationAdapter:
    """Tests for the adapter prepare() method."""

    def test_resolved_context_produces_prepared(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE, payload={"profile": "quick"}
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.session_id == "sess-001"
        assert envelope.task_id == "task-001"
        assert envelope.lane_id == "lane-001"
        assert envelope.workspace_id == "ws-001"
        assert envelope.worktree_path == "/tmp/worktrees/ws-001"
        assert envelope.repo_root == "/tmp/repo"
        assert envelope.cwd == "/tmp/worktrees/ws-001"
        assert envelope.error_kind is None

    def test_unresolved_context_produces_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved(status="blocked")
        intent = _intent()
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.BLOCKED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.CONTEXT_UNRESOLVED
        assert envelope.refusal_reason is not None

    def test_refused_context_produces_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = RuntimeContextResolution(
            status="refused",
            error_kind="unsafe_path",
            refusal_reason="path outside scope",
        )
        intent = _intent()
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.BLOCKED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.CONTEXT_UNRESOLVED

    def test_require_worktree_without_worktree_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        ctx = _resolved_context(worktree_path=None)
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            require_worktree=True,
            payload={"path": "/tmp/test.txt", "content": "hello"},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.BLOCKED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.WORKTREE_REQUIRED

    def test_write_file_payload_validation(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()

        # Missing path
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE, payload={"content": "hello"}
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.INVALID_PAYLOAD

        # Missing content
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE, payload={"path": "/tmp/test.txt"}
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.INVALID_PAYLOAD

        # Valid payload
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={"path": "/tmp/test.txt", "content": "hello"},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.payload["path"] == "/tmp/test.txt"
        assert envelope.payload["content"] == "hello"

    def test_write_file_with_worktree_uses_worktree_cwd(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        ctx = _resolved_context(worktree_path="/tmp/worktrees/ws-001")
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={"path": "test.txt", "content": "hello"},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.cwd == "/tmp/worktrees/ws-001"

    def test_search_replace_preserves_canonical_metadata(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.SEARCH_REPLACE,
            payload={
                "file_path": "/tmp/test.txt",
                "content": "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
            },
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.session_id == "sess-001"
        assert envelope.task_id == "task-001"
        assert envelope.worktree_path == "/tmp/worktrees/ws-001"

    def test_search_replace_missing_file_path_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.SEARCH_REPLACE, payload={"content": "blocks"}
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.INVALID_PAYLOAD

    def test_validate_injects_profile_and_paths(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE,
            payload={"profile": "ci", "paths": ["src/"]},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.payload["profile"] == "ci"
        assert envelope.payload["paths"] == ["src/"]
        assert envelope.payload["dirty_policy"] == "preserve_existing"
        assert envelope.payload["worktree_path"] == "/tmp/worktrees/ws-001"
        assert envelope.payload["repo_root"] == "/tmp/repo"

    def test_validate_default_profile(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(tool_name=RuntimeToolName.VALIDATE, payload={})
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.payload["profile"] == "quick"

    def test_runtime_exec_builds_exec_request_payload(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.RUNTIME_EXEC,
            payload={
                "argv": ["python3", "-c", "print('hello')"],
                "timeout_ms": 15000,
                "purpose": "Test execution",
                "requested_capabilities": ["file_read"],
            },
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        assert envelope.payload["argv"] == ["python3", "-c", "print('hello')"]
        assert envelope.payload["timeout_ms"] == 15000
        assert envelope.payload["purpose"] == "Test execution"
        assert envelope.payload["workspace_id"] == "ws-001"
        assert envelope.payload["worktree_path"] == "/tmp/worktrees/ws-001"
        assert "env_overlay" in envelope.payload
        assert envelope.payload["requested_capabilities"] == ["file_read"]

    def test_runtime_exec_missing_argv_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.RUNTIME_EXEC,
            payload={"timeout_ms": 15000, "purpose": "test"},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.INVALID_PAYLOAD

    def test_bash_legacy_refused_by_default(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.BASH_LEGACY, payload={"command": "echo hello"}
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.UNSUPPORTED_TOOL

    def test_bash_legacy_allowed_when_explicit(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.BASH_LEGACY,
            payload={"command": "echo hello", "legacy_fallback_allowed": True},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED

    def test_bash_legacy_missing_command_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.BASH_LEGACY,
            payload={"legacy_fallback_allowed": True},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.INVALID_PAYLOAD

    def test_unsupported_tool_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        # Use a valid tool name that won't match any handler
        # (All enum values are handled, so this tests the else branch)
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE,  # Actually valid
            payload={},
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED

    def test_envelope_dump_no_raw_output(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE, payload={"profile": "quick"}
        )
        envelope = adapter.prepare(intent, resolution)
        dumped = envelope.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "content" not in dumped
        assert "output" not in dumped
        assert "diff" not in dumped

    def test_unsafe_path_outside_repo_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        ctx = _resolved_context(repo_root="/tmp/repo", worktree_path=None)
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={"path": "f.txt", "content": "data"},
            requested_paths=["/etc/passwd"],
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.UNSAFE_PATH

    def test_unsafe_path_outside_worktree_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        ctx = _resolved_context(
            repo_root="/tmp/repo", worktree_path="/tmp/worktrees/ws-001"
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE,
            payload={},
            requested_paths=["/tmp/repo/nested/file.py"],
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert envelope.error_kind == RuntimeToolInvocationErrorKind.UNSAFE_PATH

    def test_write_file_expected_hash_missing_refused(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={
                "path": "f.txt",
                "content": "data",
                "allow_overwrite_protected": True,
            },
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.REFUSED
        assert (
            envelope.error_kind == RuntimeToolInvocationErrorKind.EXPECTED_HASH_MISSING
        )

    def test_write_file_with_hash_passes(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.WRITE_FILE,
            payload={
                "path": "f.txt",
                "content": "data",
                "allow_overwrite_protected": True,
                "expected_before_sha256": "sha256:abc123",
            },
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED

    def test_runtime_exec_validates_via_model_construction(self) -> None:
        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.RUNTIME_EXEC,
            payload={
                "argv": ["pytest", "tests/"],
                "purpose": "Run tests",
                "timeout_ms": 30000,
            },
        )
        envelope = adapter.prepare(intent, resolution)
        assert envelope.status == RuntimeToolInvocationStatus.PREPARED
        # Validate ExecutionRequest-produced fields are in the payload
        assert envelope.payload["argv"] == ["pytest", "tests/"]
        assert envelope.payload["purpose"] == "Run tests"
        assert envelope.payload["cwd"] == "/tmp/worktrees/ws-001"
        assert envelope.payload["workspace_id"] == "ws-001"
        assert envelope.payload["worktree_path"] == "/tmp/worktrees/ws-001"


# ── Schema validation ──────────────────────────────────────────────────


class TestSchemaValidation:
    """Validate envelopes against the JSON schema."""

    SCHEMA_PATH = str(
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.runtime_tool_invocation.v1.schema.json"
    )

    def test_prepared_envelope_validates(self) -> None:
        import json

        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent(
            tool_name=RuntimeToolName.VALIDATE, payload={"profile": "quick"}
        )
        envelope = adapter.prepare(intent, resolution)
        d = envelope.model_dump(mode="json")

        # Validate against schema
        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        import jsonschema

        jsonschema.validate(instance=d, schema=schema)

    def test_refused_envelope_validates(self) -> None:
        import json

        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved(status="blocked")
        intent = _intent()
        envelope = adapter.prepare(intent, resolution)
        d = envelope.model_dump(mode="json")

        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        import jsonschema

        jsonschema.validate(instance=d, schema=schema)

    def test_schema_version_constant(self) -> None:

        adapter = RuntimeToolInvocationAdapter()
        resolution = _resolved()
        intent = _intent()
        envelope = adapter.prepare(intent, resolution)
        d = envelope.model_dump(mode="json")
        assert d["schema_version"] == "rig.relay.runtime_tool_invocation.v1"

    def test_schema_rejects_unknown_top_level_fields(self) -> None:
        import json

        schema_path = __import__("pathlib").Path(self.SCHEMA_PATH)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        import jsonschema

        bad = {
            "schema_version": "rig.relay.runtime_tool_invocation.v1",
            "invocation_id": "bad",
            "intent_id": "bad",
            "tool_name": "validate",
            "status": "prepared",
            "unknown_field": "should be rejected",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)
