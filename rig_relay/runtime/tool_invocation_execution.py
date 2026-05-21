"""RuntimeToolExecutionRunner — executes tools through the adapter.

Provides validate and search_replace execution paths that call
RuntimeToolInvocationAdapter.prepare(), validate the envelope schema,
map envelope payloads to tool args, run the tool, and return
structured content-light results.

Context injection:
- validate: no InvokeContext (read-only, no coordination needed).
- search_replace: InvokeContext built from envelope (session_id, task_id)
  and passed to the tool. CWD is set to envelope.cwd during execution
  for path validation and coordination store resolution.

Constraints:
- RuntimeSupervisor integration is deferred.
- Lease acquisition: wired for search_replace and write_file.
- Audit persistence: wired for all execute_* methods via RuntimeAuditPersistenceStore.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.lease_manager import DEFAULT_LEASE_TTL_SECONDS
from rig_relay.core.logger import logger
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
    # ── Linkage fields (from audit: dec_20260517_001 through 006) ──
    tool_receipt_kind: str | None = None
    tool_receipt_schema_version: str | None = None
    receipt_envelope_id: str | None = None
    audit_event_id: str | None = None
    changed_paths: list[str] = Field(default_factory=list)
    supervisor_result_envelope_id: str | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None
    # ── Receipt model (produced alongside result) ─────────────────
    receipt: RuntimeToolInvocationReceipt | None = None


# ── Execution runner ──────────────────────────────────────────────────


@dataclass
class _LeaseClaimOutcome:
    """Result of a lease claim attempt in the execution runner."""

    blocked: RuntimeToolExecutionResult | None = None
    lease_info: tuple[str, str, list[str]] | None = None


def _build_tool_receipt(tool_name: str, result: Any) -> Any:
    """Build a receipt for a given tool result.

    Creates a minimal tool instance and delegates to its build_receipt method.
    """
    from rig_relay.core.tools.base import BaseToolState

    match tool_name:
        case "validate":
            from rig_relay.core.tools.builtins.validate import Validate
            from rig_relay.core.tools.builtins.validate_models import ValidateToolConfig

            tool = Validate(
                config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
            )
        case "search_replace":
            from rig_relay.core.tools.builtins.search_replace import (
                SearchReplace,
                SearchReplaceConfig,
            )

            tool = SearchReplace(
                config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
            )
        case "write_file":
            from rig_relay.core.tools.builtins.write_file import (
                WriteFile,
                WriteFileConfig,
            )

            tool = WriteFile(
                config_getter=lambda: WriteFileConfig(), state=BaseToolState()
            )
        case "bash":
            from rig_relay.core.tools.builtins.bash import Bash, BashToolConfig

            tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
        case _:
            return None
    return tool.build_receipt(result)


class RuntimeToolExecutionRunner:
    """Executes tools through the adapter.

    Currently supports validate and search_replace execution.

    - validate: read-only, runs the Validate tool.
    - search_replace: mutation, runs the SearchReplace tool through its
      hardened interface (coordination + dirty guard handled internally).

    No lease acquisition, no RuntimeSupervisor integration.
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

    # ── Public API ─────────────────────────────────────────────────

    async def execute_validate(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a validate tool invocation through the adapter.

        Calls RuntimeToolInvocationAdapter.prepare(), validates the
        envelope, maps the payload to ValidateArgs, runs the validate
        tool, and returns a structured content-light result.
        """
        start = time.perf_counter()

        # ── Refuse non-validate tools ──────────────────────────────
        if intent.tool_name != RuntimeToolName.VALIDATE:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Tool '{intent.tool_name.value}' is not supported for "
                    "validate-only execution"
                ),
            )
            self._persist_if_configured(_result, None)
            return _result

        # ── Run adapter prepare ────────────────────────────────────
        envelope = self._adapter.prepare(intent, resolution)

        # ── Handle blocked/refused ─────────────────────────────────
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        # ── Validate envelope against schema ───────────────────────
        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=(
                    f"Envelope failed schema validation: {'; '.join(schema_errors)}"
                ),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        runtime_result = await self._execute_runtime_tool(
            intent=intent, envelope=envelope
        )
        result = self._to_execution_result(
            runtime_result=runtime_result, intent=intent, envelope=envelope, start=start
        )
        self._persist_if_configured(result, envelope)
        return result

    async def execute_search_replace(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a search_replace tool invocation through the adapter.

        Calls RuntimeToolInvocationAdapter.prepare(), validates the
        envelope, maps the payload to SearchReplaceArgs, runs the
        search_replace tool through its hardened interface, and returns
        a structured content-light result.

        The tool internally handles coordination and dirty guard checks.
        No lease acquisition or RuntimeSupervisor integration here.
        """
        start = time.perf_counter()

        # ── Refuse non-search_replace tools ────────────────────────
        if intent.tool_name != RuntimeToolName.SEARCH_REPLACE:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Tool '{intent.tool_name.value}' is not supported for "
                    "search_replace execution"
                ),
            )
            self._persist_if_configured(_result, None)
            return _result

        # ── Run adapter prepare ────────────────────────────────────
        envelope = self._adapter.prepare(intent, resolution)

        # ── Handle blocked/refused ─────────────────────────────────
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        # ── Validate envelope against schema ───────────────────────
        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=(
                    f"Envelope failed schema validation: {'; '.join(schema_errors)}"
                ),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        # ── Lease acquisition ──────────────────────────────────────
        payload = envelope.payload or {}
        file_path = payload.get("file_path", "")
        lease_outcome = self._claim_mutation_lease(envelope, file_path)
        if lease_outcome.blocked is not None:
            return lease_outcome.blocked
        lease_info = lease_outcome.lease_info
        coordination_root = self._resolve_coordination_root(envelope)

        # ── Execute search_replace tool (with lease release in finally) ─
        try:
            runtime_result = await self._execute_runtime_tool(
                intent=intent, envelope=envelope
            )
            payload = envelope.payload or {}
            file_path = payload.get("file_path", "")
            _out = self._to_execution_result(
                runtime_result=runtime_result,
                intent=intent,
                envelope=envelope,
                start=start,
                changed_paths=[file_path] if file_path else [],
                tool_receipt_kind="search_replace",
            )
            self._persist_if_configured(_out, envelope)
            return _out
        finally:
            if lease_info is not None:
                self._release_mutation_lease(coordination_root, lease_info)

    async def execute_write_file(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a write_file tool invocation through the adapter."""
        start = time.perf_counter()

        if intent.tool_name != RuntimeToolName.WRITE_FILE:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=f"Tool '{intent.tool_name.value}' is not supported for write_file execution",
            )
            self._persist_if_configured(_result, None)
            return _result

        envelope = self._adapter.prepare(intent, resolution)

        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=f"Envelope failed schema validation: {'; '.join(schema_errors)}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        # ── Lease acquisition ──────────────────────────────────────
        payload = envelope.payload or {}
        file_path = payload.get("path", "")
        lease_outcome = self._claim_mutation_lease(envelope, file_path)
        if lease_outcome.blocked is not None:
            return lease_outcome.blocked
        lease_info = lease_outcome.lease_info
        coordination_root = self._resolve_coordination_root(envelope)

        # ── Execute write_file tool (with lease release in finally) ─
        try:
            runtime_result = await self._execute_runtime_tool(
                intent=intent, envelope=envelope
            )
            payload = envelope.payload or {}
            _out = self._to_execution_result(
                runtime_result=runtime_result,
                intent=intent,
                envelope=envelope,
                start=start,
                changed_paths=[payload.get("path", "")] if payload.get("path") else [],
                tool_receipt_kind="write_file",
            )
            self._persist_if_configured(_out, envelope)
            return _out
        finally:
            if lease_info is not None:
                self._release_mutation_lease(coordination_root, lease_info)

    async def execute_bash(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolExecutionResult:
        """Execute a bash tool invocation through the adapter."""
        start = time.perf_counter()

        if intent.tool_name != RuntimeToolName.BASH_LEGACY:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=f"Tool '{intent.tool_name.value}' is not supported for bash execution",
            )
            self._persist_if_configured(_result, None)
            return _result

        envelope = self._adapter.prepare(intent, resolution)

        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            _result = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=f"Envelope failed schema validation: {'; '.join(schema_errors)}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            self._persist_if_configured(_result, envelope)
            return _result

        runtime_result = await self._execute_runtime_tool(
            intent=intent, envelope=envelope
        )
        result = self._to_execution_result(
            runtime_result=runtime_result,
            intent=intent,
            envelope=envelope,
            start=start,
            tool_receipt_kind="bash",
        )
        self._persist_if_configured(result, envelope)
        return result

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

    @staticmethod
    def _to_execution_result(
        *,
        runtime_result: Any,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        start: float,
        changed_paths: list[str] | None = None,
        tool_receipt_kind: str | None = None,
    ) -> RuntimeToolExecutionResult:
        duration = (time.perf_counter() - start) * 1000
        status_value = getattr(runtime_result.status, "value", runtime_result.status)
        provider = getattr(runtime_result, "provider_tool_response", None)
        provider_status = getattr(provider, "status", None)
        provider_status_value = getattr(provider_status, "value", provider_status)
        status_source = provider_status_value or status_value
        tool_status = provider_status_value or status_source
        provider_error_kind = getattr(provider, "error_kind", None)
        provider_refusal = getattr(provider, "refusal_reason", None)
        if status_source == "cached":
            execution_status = RuntimeToolExecutionStatus.COMPLETED
        elif status_source == "completed":
            execution_status = RuntimeToolExecutionStatus.COMPLETED
        elif status_source == "passed":
            execution_status = RuntimeToolExecutionStatus.COMPLETED
        elif status_source == "success":
            execution_status = RuntimeToolExecutionStatus.COMPLETED
        elif status_source == "refused":
            execution_status = RuntimeToolExecutionStatus.REFUSED
        elif status_source == "blocked":
            execution_status = RuntimeToolExecutionStatus.BLOCKED
        elif status_source == "failed":
            execution_status = RuntimeToolExecutionStatus.FAILED
        elif status_source == "timed_out":
            execution_status = RuntimeToolExecutionStatus.FAILED
        else:
            execution_status = RuntimeToolExecutionStatus.COMPLETED
        if (
            intent.tool_name == RuntimeToolName.BASH_LEGACY
            and execution_status == RuntimeToolExecutionStatus.FAILED
        ):
            tool_status = None

        provider_supervisor_envelope = getattr(
            getattr(runtime_result, "provider_tool_response", None),
            "supervisor_result_envelope",
            None,
        )
        supervisor_result_envelope_id = None
        if isinstance(provider_supervisor_envelope, dict):
            supervisor_result_envelope_id = provider_supervisor_envelope.get(
                "result_id"
            )

        result = RuntimeToolExecutionResult(
            status=execution_status,
            invocation_id=envelope.invocation_id,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name.value,
            envelope_schema_valid=True,
            tool_status=tool_status,
            tool_error_kind=provider_error_kind,
            receipt_sha256=None,
            duration_ms=duration,
            error_kind=provider_error_kind,
            refusal_reason=provider_refusal
            or getattr(getattr(runtime_result, "refusal", None), "message", None),
            tool_receipt_kind=tool_receipt_kind or intent.tool_name.value,
            tool_receipt_schema_version=(
                f"rig.relay.{(tool_receipt_kind or intent.tool_name.value)}_receipt.v1"
            ),
            changed_paths=changed_paths or [],
            supervisor_result_envelope_id=supervisor_result_envelope_id,
            supervisor_result_envelope_sha256=getattr(
                runtime_result, "supervisor_result_envelope_sha256", None
            ),
            supervisor_result_classification=getattr(
                runtime_result, "supervisor_result_classification", None
            ),
        )
        result = result.model_copy(
            update={
                "receipt_sha256": hashlib.sha256(
                    json.dumps(result.model_dump(mode="json"), sort_keys=True).encode()
                ).hexdigest()
            }
        )
        if (
            result.status == RuntimeToolExecutionStatus.FAILED
            and result.error_kind is None
        ):
            result = result.model_copy(update={"error_kind": "execution_error"})
        return RuntimeToolExecutionRunner._attach_receipt(result)

    async def _run_validate_tool(self, envelope: RuntimeToolInvocationEnvelope) -> Any:
        """Run the validate tool and extract the final result.

        Iterates the async generator to capture streaming events
        (ToolStreamEvent) as well as the final result model.
        """
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
        """Run the search_replace tool with runtime context injected.

        Builds an InvokeContext from the envelope (session_id, task_id)
        and passes it to the tool so coordination checks and path
        validation use the canonical runtime context.

        CWD is temporarily set to envelope.cwd during execution so the
        tool's Path.cwd()-based checks (path validation, coordination
        store resolution) operate within the correct scope.
        """
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
        """Run the write_file tool with runtime context injected."""
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
        """Run the bash tool with runtime context injected."""
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
    @staticmethod
    def _build_validate_receipt(result: Any) -> Any:
        return _build_tool_receipt("validate", result)

    @staticmethod
    def _build_search_replace_receipt(result: Any) -> Any:
        return _build_tool_receipt("search_replace", result)

    @staticmethod
    def _build_write_file_receipt(result: Any) -> Any:
        return _build_tool_receipt("write_file", result)

    @staticmethod
    def _build_bash_receipt(result: Any) -> Any:
        return _build_tool_receipt("bash", result)

    def _claim_mutation_lease(
        self, envelope: RuntimeToolInvocationEnvelope, file_path: str
    ) -> _LeaseClaimOutcome:
        """Claim a path lease for a mutation tool.

        Attempts to acquire an exclusive_write lease on the given file path.
        Returns a _LeaseClaimOutcome with:
        - blocked: RuntimeToolExecutionResult if the claim was blocked/refused
        - lease_info: (session_id, task_id, [file_path]) if the claim succeeded

        Coordination policy:
        - If coordination_enabled is False on the envelope, lease is skipped
          and execution proceeds without a lease.
        - If coordination_enabled is True and session/task/file_path are present,
          a lease must be acquired or the mutation is BLOCKED.
        - Store errors do not silently allow mutation when coordination is enabled.
        """
        coordination_enabled = getattr(envelope, "coordination_enabled", True)

        if (
            not coordination_enabled
            or not envelope.session_id
            or not envelope.task_id
            or not file_path
        ):
            # Backward compat or coordination disabled: proceed without lease.
            lease_info: tuple[str, str, list[str]] | None = None
            return _LeaseClaimOutcome(blocked=None, lease_info=lease_info)

        try:
            from rig_relay.coordination.lease_manager import PathLeaseManager

            manager = PathLeaseManager(self._resolve_coordination_root(envelope))
            result = manager.claim_paths(
                session_id=envelope.session_id,
                task_id=envelope.task_id,
                mode="exclusive_write",
                paths=[file_path],
                ttl_seconds=envelope.lease_ttl_seconds or DEFAULT_LEASE_TTL_SECONDS,
            )
            if result.status == "conflict":
                blocked = RuntimeToolExecutionResult(
                    status=RuntimeToolExecutionStatus.BLOCKED,
                    intent_id=getattr(envelope, "invocation_id", ""),
                    tool_name=getattr(envelope, "tool_name", "unknown"),
                    error_kind=result.error_kind or "lease_conflict",
                    refusal_reason=result.refusal_reason or "Path lease conflict",
                )
                return _LeaseClaimOutcome(blocked=blocked, lease_info=None)
            if result.status == "granted":
                lease_info = (envelope.session_id, envelope.task_id, [file_path])
                return _LeaseClaimOutcome(blocked=None, lease_info=lease_info)
            # Unexpected status — treat as blocked when coordination is enabled
            blocked = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=getattr(envelope, "invocation_id", ""),
                tool_name=getattr(envelope, "tool_name", "unknown"),
                error_kind=result.error_kind or "lease_error",
                refusal_reason=result.refusal_reason
                or "Lease acquisition returned unexpected status",
            )
            return _LeaseClaimOutcome(blocked=blocked, lease_info=None)
        except Exception:
            # Store exception when coordination is enabled blocks mutation
            blocked = RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=getattr(envelope, "invocation_id", ""),
                tool_name=getattr(envelope, "tool_name", "unknown"),
                error_kind="lease_store_error",
                refusal_reason="Lease store error prevented lease acquisition",
            )
            return _LeaseClaimOutcome(blocked=blocked, lease_info=None)

    @staticmethod
    def _release_mutation_lease(
        coordination_root: str | Path, lease_info: tuple[str, str, list[str]]
    ) -> None:
        """Release a previously acquired mutation lease.

        Best-effort: failures are silently ignored so lease release
        never breaks tool execution or result construction.
        """
        session_id, task_id, paths = lease_info
        if not session_id or not task_id or not paths:
            return
        try:
            from rig_relay.coordination.lease_manager import PathLeaseManager

            manager = PathLeaseManager(Path(coordination_root))
            manager.release_paths(session_id=session_id, task_id=task_id, paths=paths)
        except Exception:
            logger.warning(
                "Lease release failed for session=%s task=%s paths=%s",
                session_id,
                task_id,
                paths,
            )

    @staticmethod
    def _resolve_coordination_root(envelope: RuntimeToolInvocationEnvelope) -> Path:
        """Resolve the coordination store root from an envelope.

        Prefers worktree_path, then repo_root, then CWD.
        """
        base = envelope.worktree_path or envelope.repo_root or Path.cwd().as_posix()
        return Path(base) / ".build" / "rig-relay" / "coordination"

    @staticmethod
    def _build_invoke_context(envelope: RuntimeToolInvocationEnvelope) -> Any | None:
        """Build an InvokeContext from an invocation envelope.

        Returns None when the envelope lacks session_id or task_id
        (preserving the current behavior of skipping coordination).
        """
        from rig_relay.core.tools.base import InvokeContext

        if not envelope.session_id or not envelope.task_id:
            return None

        session_dir = Path(f"/runtime/sessions/{envelope.session_id}")

        return InvokeContext(tool_call_id=envelope.task_id, session_dir=session_dir)

    @staticmethod
    @contextmanager
    def _cwd_for_envelope(envelope: RuntimeToolInvocationEnvelope) -> Any:
        """Context manager that sets CWD to envelope.cwd during execution.

        Restores the original CWD on exit. If envelope.cwd is None,
        this is a no-op.
        """
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

    @staticmethod
    def _attach_receipt(
        result: RuntimeToolExecutionResult,
    ) -> RuntimeToolExecutionResult:
        """Attach a receipt model to the execution result.

        Propagates any exception from receipt building.
        """
        from rig_relay.runtime.tool_invocation_receipt import (
            build_runtime_tool_invocation_receipt,
        )

        receipt_model = build_runtime_tool_invocation_receipt(result)
        result = result.model_copy(update={"receipt": receipt_model})
        return result

    def _persist_if_configured(
        self,
        result: RuntimeToolExecutionResult,
        envelope: RuntimeToolInvocationEnvelope | None = None,
    ) -> None:
        """Persist a RuntimeAuditEvent if an audit store is configured.

        Best-effort: failures are silently ignored so audit persistence
        never breaks tool execution.
        """
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
        """Validate the envelope against the runtime_tool_invocation schema."""
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
