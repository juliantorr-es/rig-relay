"""RuntimeToolExecutionRunner — executes tools through the adapter.

Provides validate, search_replace, write_file, bash, and runtime_exec
execution paths. Shared gating logic (envelope preparation, schema
validation, lease acquisition, result construction, receipt persistence)
is extracted into _execution_template.py, _lease_gate.py, and
_result_builder.py. This module is the facade that composes those
modules into the RuntimeToolExecutionRunner class.

Context injection:
- validate: no InvokeContext (read-only, no coordination needed).
- search_replace, write_file, bash: InvokeContext built from envelope
  (session_id, task_id) and passed to the tool. CWD is set to
  envelope.cwd during execution for path validation and coordination
  store resolution.

Constraints:
- RuntimeSupervisor integration is deferred.
- Lease acquisition: wired for search_replace and write_file
  (via _lease_gate.py).
- Audit persistence: wired for all execute_* methods via
  RuntimeAuditPersistenceStore.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import contextmanager
from enum import StrEnum
import json
import os
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.runtime.context import RuntimeContextResolution
from rig_relay.runtime.runtime_audit_event import (
    RuntimeAuditPersistenceStore,
    build_runtime_audit_event,
)
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolIntent,
    RuntimeToolInvocationAdapter,
    RuntimeToolInvocationEnvelope,
    RuntimeToolInvocationStatus,
    RuntimeToolName,
)
from rig_relay.runtime.tool_runtime_adapter import RuntimeToolRuntimeAdapter

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.runtime_tool_execution_result.v1"

_DEFAULT_ENVELOPE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_invocation.v1.schema.json"
)

# ── Enums ──────────────────────────────────────────────────────────────


class RuntimeToolExecutionStatus(StrEnum):
    """Status of a tool execution attempt."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    REFUSED = "refused"
    FAILED = "failed"


# ── Execution result model ────────────────────────────────────────────


class RuntimeToolExecutionResult(BaseModel):
    """Result of a tool execution through the adapter.

    Content-light: no raw file contents, stdout, stderr, diffs, snippets,
    or secrets. Only status indicators, hashes, timing, and structured
    error/refusal information.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    invocation_id: str | None = None
    intent_id: str
    tool_name: str
    source_kind: str | None = None
    source_id: str | None = None
    runtime_envelope_sha256: str | None = None
    status: RuntimeToolExecutionStatus
    envelope_schema_valid: bool = False
    tool_status: str | None = None
    tool_error_kind: str | None = None
    receipt_sha256: str | None = None
    duration_ms: float | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    tool_receipt_kind: str | None = None
    tool_receipt_schema_version: str | None = None
    receipt_envelope_id: str | None = None
    audit_event_id: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    supervisor_result_envelope_id: str | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None
    receipt: RuntimeToolInvocationReceipt | None = None


# ── Import shared modules after model definitions ──────────────────────
# (placed here to avoid circular imports; RuntimeToolExecutionResult
# is defined above and available to the imported modules)

from rig_relay.runtime._execution_template import _ExecutionTemplateMixin

# ── Execution runner ──────────────────────────────────────────────────


class RuntimeToolExecutionRunner(_ExecutionTemplateMixin):
    """Executes tools through the adapter.

    Delegates shared gating logic (envelope preparation, schema
    validation, lease acquisition, result construction, receipt
    persistence) to _ExecutionTemplateMixin. Individual tool execution
    is handled by _run_*_tool methods dispatched through the ToolRuntime.

    - validate: read-only, runs the Validate tool.
    - search_replace: mutation, runs the SearchReplace tool with lease.
    - write_file: mutation, runs the WriteFile tool with lease.
    - bash: runs the Bash tool with an optional subprocess runner.
    - runtime_exec: dispatches to the appropriate execute_* method.
    """

    def __init__(
        self,
        adapter: RuntimeToolInvocationAdapter | None = None,
        envelope_schema_path: Path | None = None,
        audit_store: RuntimeAuditPersistenceStore | None = None,
    ) -> None:
        self._adapter = adapter or RuntimeToolInvocationAdapter()
        self._envelope_schema_path = (
            envelope_schema_path or _DEFAULT_ENVELOPE_SCHEMA_PATH
        )
        self._audit_store = audit_store
        self._runtime_adapter = RuntimeToolRuntimeAdapter()
        self._tool_runtime = ToolRuntime(
            invoke_tool=self._invoke_tool_runtime,
            receipt_build=self._build_runtime_receipt,
            receipt_capture=self._capture_runtime_receipt,
            subprocess_runner=self._build_subprocess_runner(),
            source_label="runtime_intent",
            policy_object=self._runtime_adapter.build_policy(),
        )

    def _build_subprocess_runner(self) -> Any:
        try:
            from rig_relay.runtime.supervisor_invoker import (
                RuntimeSupervisorToolSubprocessRunner,
            )

            return RuntimeSupervisorToolSubprocessRunner()
        except Exception:
            return None

    # ── Public API (thin wrappers) ─────────────────────────────────

    async def execute_validate(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a validate tool invocation through the adapter."""
        return await self._execute_with_gating(
            intent=intent,
            resolution=resolution,
            expected_tool=RuntimeToolName.VALIDATE,
            unsupported_reason=(
                f"Tool '{intent.tool_name.value}' is not supported for "
                "validate-only execution"
            ),
        )

    async def execute_search_replace(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a search_replace tool invocation through the adapter."""
        return await self._execute_with_gating(
            intent=intent,
            resolution=resolution,
            expected_tool=RuntimeToolName.SEARCH_REPLACE,
            unsupported_reason=(
                f"Tool '{intent.tool_name.value}' is not supported for "
                "search_replace execution"
            ),
            needs_lease=True,
            lease_file_path_attr="file_path",
            tool_receipt_kind="search_replace",
        )

    async def execute_write_file(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a write_file tool invocation through the adapter."""
        return await self._execute_with_gating(
            intent=intent,
            resolution=resolution,
            expected_tool=RuntimeToolName.WRITE_FILE,
            unsupported_reason=(
                f"Tool '{intent.tool_name.value}' is not supported for "
                "write_file execution"
            ),
            needs_lease=True,
            lease_file_path_attr="path",
            tool_receipt_kind="write_file",
        )

    async def execute_bash(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a bash tool invocation through the adapter."""
        return await self._execute_with_gating(
            intent=intent,
            resolution=resolution,
            expected_tool=RuntimeToolName.BASH_LEGACY,
            unsupported_reason=(
                f"Tool '{intent.tool_name.value}' is not supported for bash execution"
            ),
            tool_receipt_kind="bash",
        )

    async def execute_runtime_exec(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Dispatch runtime_exec to the correct Phase 2 adapter.

        Reads payload["tool_name"] to determine the sub-tool, builds a
        sub-intent with the remaining payload, and dispatches to the
        appropriate execute_* method.

        Returns REFUSED/unsupported_tool for:
        - Non-runtime_exec tool_name
        - Missing or unknown sub-tool name
        - runtime_exec dispatched to itself (circular)
        """
        start = time.perf_counter()

        if intent.tool_name != RuntimeToolName.RUNTIME_EXEC:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Tool '{intent.tool_name.value}' is not supported for "
                    "runtime_exec dispatch"
                ),
            )

        payload = intent.payload or {}
        sub_tool_name_str: str = payload.get("tool_name", "")

        if not sub_tool_name_str:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="invalid_payload",
                refusal_reason="runtime_exec payload requires 'tool_name'",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        try:
            sub_tool = RuntimeToolName(sub_tool_name_str)
        except ValueError:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="unsupported_tool",
                refusal_reason=f"Unknown sub-tool: '{sub_tool_name_str}'",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        if sub_tool == RuntimeToolName.RUNTIME_EXEC:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="unsupported_tool",
                refusal_reason="runtime_exec cannot dispatch to itself (circular)",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        sub_payload = {k: v for k, v in payload.items() if k != "tool_name"}
        sub_intent = RuntimeToolIntent(
            intent_id=intent.intent_id,
            tool_name=sub_tool,
            payload=sub_payload,
            requested_paths=intent.requested_paths,
            require_worktree=intent.require_worktree,
            allow_main_repo_mutation=intent.allow_main_repo_mutation,
        )

        if sub_tool == RuntimeToolName.VALIDATE:
            return await self.execute_validate(sub_intent, resolution)
        elif sub_tool == RuntimeToolName.SEARCH_REPLACE:
            return await self.execute_search_replace(sub_intent, resolution)
        elif sub_tool == RuntimeToolName.WRITE_FILE:
            return await self.execute_write_file(sub_intent, resolution)
        elif sub_tool == RuntimeToolName.BASH_LEGACY:
            return await self.execute_bash(sub_intent, resolution)
        else:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Sub-tool '{sub_tool.value}' is not available via runtime_exec"
                ),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    # ── Internal helpers ───────────────────────────────────────────

    async def _execute_runtime_tool(
        self, *, intent: RuntimeToolIntent, envelope: RuntimeToolInvocationEnvelope
    ) -> Any:
        bundle = self._runtime_adapter.build_request(
            envelope,
            actor=envelope.agent_id,
            trust_tier=getattr(envelope, "trust_tier", None),
        )
        request = bundle.request
        request = request.model_copy(
            update={
                "tool_name": self._runtime_adapter._map_tool_name(envelope.tool_name),
                "tool_call_id": envelope.invocation_id,
            }
        )
        runtime_result = await self._tool_runtime.execute_one(request)
        return runtime_result

    @staticmethod
    def _build_runtime_receipt(tool_name: str, result: Any) -> Any | None:
        return None

    @staticmethod
    def _capture_runtime_receipt(
        session_id: str, tool_name: str, receipt: dict[str, Any]
    ) -> None:
        return None

    async def _invoke_tool_runtime(
        self, args_dict: dict[str, Any]
    ) -> AsyncGenerator[Any, None]:
        if False:
            yield None
        tool_name = args_dict.get("_tool_runtime_name", "")
        meta = args_dict.get("_tool_runtime_meta", {})
        payload = {
            k: v for k, v in args_dict.items() if not k.startswith("_tool_runtime_")
        }
        if tool_name == "validate":
            envelope = RuntimeToolInvocationEnvelope(
                invocation_id=meta.get("invocation_id", ""),
                intent_id=meta.get("runtime_intent_id", ""),
                tool_name=RuntimeToolName.VALIDATE,
                status=RuntimeToolInvocationStatus.PREPARED,
                payload=payload,
                cwd=meta.get("worktree_path") or meta.get("workspace_root"),
                worktree_path=meta.get("worktree_path"),
                repo_root=meta.get("workspace_root"),
                session_id=meta.get("session_id"),
                task_id=meta.get("turn_id"),
                lane_id=meta.get("lane_id"),
                workspace_id=meta.get("workspace_id"),
                agent_id=meta.get("actor"),
            )
            result = await self._run_validate_tool(envelope)
            yield result
            return
        if tool_name == "search_replace":
            envelope = RuntimeToolInvocationEnvelope(
                invocation_id=meta.get("invocation_id", ""),
                intent_id=meta.get("runtime_intent_id", ""),
                tool_name=RuntimeToolName.SEARCH_REPLACE,
                status=RuntimeToolInvocationStatus.PREPARED,
                payload=payload,
                cwd=meta.get("worktree_path") or meta.get("workspace_root"),
                worktree_path=meta.get("worktree_path"),
                repo_root=meta.get("workspace_root"),
                session_id=meta.get("session_id"),
                task_id=meta.get("turn_id"),
                lane_id=meta.get("lane_id"),
                workspace_id=meta.get("workspace_id"),
                agent_id=meta.get("actor"),
            )
            result = await self._run_search_replace_tool(envelope)
            yield result
            return
        if tool_name == "write_file":
            envelope = RuntimeToolInvocationEnvelope(
                invocation_id=meta.get("invocation_id", ""),
                intent_id=meta.get("runtime_intent_id", ""),
                tool_name=RuntimeToolName.WRITE_FILE,
                status=RuntimeToolInvocationStatus.PREPARED,
                payload=payload,
                cwd=meta.get("worktree_path") or meta.get("workspace_root"),
                worktree_path=meta.get("worktree_path"),
                repo_root=meta.get("workspace_root"),
                session_id=meta.get("session_id"),
                task_id=meta.get("turn_id"),
                lane_id=meta.get("lane_id"),
                workspace_id=meta.get("workspace_id"),
                agent_id=meta.get("actor"),
            )
            result = await self._run_write_file_tool(envelope)
            yield result
            return
        if tool_name == "bash":
            envelope = RuntimeToolInvocationEnvelope(
                invocation_id=meta.get("invocation_id", ""),
                intent_id=meta.get("runtime_intent_id", ""),
                tool_name=RuntimeToolName.BASH_LEGACY,
                status=RuntimeToolInvocationStatus.PREPARED,
                payload=payload,
                cwd=meta.get("worktree_path") or meta.get("workspace_root"),
                worktree_path=meta.get("worktree_path"),
                repo_root=meta.get("workspace_root"),
                session_id=meta.get("session_id"),
                task_id=meta.get("turn_id"),
                lane_id=meta.get("lane_id"),
                workspace_id=meta.get("workspace_id"),
                agent_id=meta.get("actor"),
            )
            invoke_ctx = self._build_invoke_context(envelope)
            subprocess_runner = meta.get("subprocess_runner")
            if invoke_ctx is not None and subprocess_runner is not None:
                invoke_ctx.subprocess_runner = subprocess_runner
            result = await self._run_bash_tool(envelope, invoke_ctx)
            yield result
            return
        raise RuntimeError(f"Unsupported runtime tool: {tool_name}")

    async def _run_validate_tool(self, envelope: RuntimeToolInvocationEnvelope) -> Any:
        from rig_relay.core.tools.base import BaseToolState
        from rig_relay.core.tools.builtins.validate import Validate, ValidateArgs
        from rig_relay.core.tools.builtins.validate_models import ValidateToolConfig

        payload = envelope.payload or {}

        args = ValidateArgs(
            profile=payload.get("profile", "quick"),
            paths=payload.get("paths") or [],
            workspace_root=envelope.worktree_path or envelope.repo_root or None,
        )

        config = ValidateToolConfig()
        tool = Validate(config_getter=lambda: config, state=BaseToolState())
        result: Any = None
        async for item in tool.run(args):
            result = item

        return result

    async def _run_search_replace_tool(
        self, envelope: RuntimeToolInvocationEnvelope
    ) -> Any:
        from rig_relay.core.tools.base import BaseToolState
        from rig_relay.core.tools.builtins.search_replace import (
            SearchReplace,
            SearchReplaceArgs,
            SearchReplaceConfig,
        )

        payload = envelope.payload or {}

        args = SearchReplaceArgs(
            file_path=payload.get("file_path", ""),
            content=payload.get("content", ""),
            expected_before_sha256=payload.get("expected_before_sha256"),
            expected_replacements=payload.get("expected_replacements"),
            allow_multiple=payload.get("allow_multiple", True),
        )

        invoke_ctx = self._build_invoke_context(envelope)
        config = SearchReplaceConfig()
        tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

        with self._cwd_for_envelope(envelope):
            result: Any = None
            async for item in tool.run(args, ctx=invoke_ctx):
                result = item

        return result

    async def _run_write_file_tool(
        self, envelope: RuntimeToolInvocationEnvelope
    ) -> Any:
        from rig_relay.core.tools.base import BaseToolState
        from rig_relay.core.tools.builtins.write_file import (
            WriteFile,
            WriteFileArgs,
            WriteFileConfig,
        )

        payload = envelope.payload or {}

        args = WriteFileArgs(
            path=payload.get("path", ""),
            content=payload.get("content", ""),
            overwrite=payload.get("overwrite", False),
            allow_overwrite_protected=payload.get("allow_overwrite_protected", False),
            expected_before_sha256=payload.get("expected_before_sha256"),
        )

        invoke_ctx = self._build_invoke_context(envelope)
        config = WriteFileConfig()
        tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

        with self._cwd_for_envelope(envelope):
            result: Any = None
            async for item in tool.run(args, ctx=invoke_ctx):
                result = item

        return result

    async def _run_bash_tool(
        self, envelope: RuntimeToolInvocationEnvelope, invoke_ctx: Any | None = None
    ) -> Any:
        from rig_relay.core.tools.base import BaseToolState
        from rig_relay.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig

        payload = envelope.payload or {}

        args = BashArgs(
            command=payload.get("command", ""),
            timeout=payload.get("timeout"),
            cwd=payload.get("cwd"),
            max_stdout_bytes=payload.get("max_stdout_bytes"),
            max_stderr_bytes=payload.get("max_stderr_bytes"),
        )

        if invoke_ctx is None:
            invoke_ctx = self._build_invoke_context(envelope)
        config = BashToolConfig()
        tool = Bash(config_getter=lambda: config, state=BaseToolState())

        with self._cwd_for_envelope(envelope):
            result: Any = None
            async for item in tool.run(args, ctx=invoke_ctx):
                result = item

        return result

    @staticmethod
    def _build_invoke_context(envelope: RuntimeToolInvocationEnvelope) -> Any | None:
        from rig_relay.core.tools.base import InvokeContext

        if not envelope.session_id or not envelope.task_id:
            return None

        session_dir = Path(f"/runtime/sessions/{envelope.session_id}")

        return InvokeContext(tool_call_id=envelope.task_id, session_dir=session_dir)

    @staticmethod
    @contextmanager
    def _cwd_for_envelope(envelope: RuntimeToolInvocationEnvelope) -> Any:
        target = envelope.cwd
        if target is None:
            yield
            return
        original = os.getcwd()
        if original == target:
            yield
            return
        os.chdir(target)
        try:
            yield
        finally:
            os.chdir(original)

    def _persist_if_configured(
        self,
        result: RuntimeToolExecutionResult,
        envelope: RuntimeToolInvocationEnvelope | None = None,
    ) -> None:
        if self._audit_store is None:
            return
        try:
            mission_id = getattr(envelope, "mission_id", None)
            agent_id = getattr(envelope, "agent_id", None)
            lease_id = getattr(envelope, "lease_id", None)
            parent_event_id = getattr(envelope, "parent_event_id", None)

            event = build_runtime_audit_event(
                result,
                mission_id=mission_id,
                agent_id=agent_id,
                lease_id=lease_id,
                parent_event_id=parent_event_id,
            )
            self._audit_store.append(event)
        except Exception:
            pass

    def _validate_envelope_schema(
        self, envelope: RuntimeToolInvocationEnvelope
    ) -> tuple[bool, list[str]]:
        import jsonschema

        schema_path = self._envelope_schema_path
        if not schema_path.is_file():
            return False, ["Schema file not found"]

        try:
            with open(schema_path) as f:
                schema = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return False, [f"Could not load schema: {e}"]

        try:
            validator = jsonschema.Draft7Validator(schema)
            errors = list(validator.iter_errors(envelope.model_dump(mode="json")))
            if errors:
                return False, [e.message for e in errors]
            return True, []
        except jsonschema.SchemaError as e:
            return False, [f"Schema error: {e}"]


__all__ = [
    "RuntimeToolExecutionResult",
    "RuntimeToolExecutionRunner",
    "RuntimeToolExecutionStatus",
]

# Resolve forward reference in RuntimeToolExecutionResult.receipt field.
# tool_invocation_receipt.py uses TYPE_CHECKING for its execution import,
# so this does not create a circular dependency.
from rig_relay.runtime.tool_invocation_receipt import RuntimeToolInvocationReceipt

RuntimeToolExecutionResult.model_rebuild()
