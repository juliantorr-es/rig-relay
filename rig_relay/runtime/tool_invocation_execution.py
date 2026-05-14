"""RuntimeToolExecutionRunner — executes tools through the adapter.

Provides validate and search_replace execution paths that call
RuntimeToolInvocationAdapter.prepare(), validate the envelope schema,
map envelope payloads to tool args, run the tool, and return
structured content-light results.

Constraints:
- Validate execution only (read-only).
- search_replace execution (mutation) behind the adapter.
- No lease acquisition.
- No RuntimeSupervisor integration.
- Audit integration is optional (not wired here).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.runtime.context import RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import (
    RuntimeToolIntent,
    RuntimeToolInvocationAdapter,
    RuntimeToolInvocationEnvelope,
    RuntimeToolInvocationStatus,
    RuntimeToolName,
)

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


# ── Execution runner ──────────────────────────────────────────────────


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
    ) -> None:
        self._adapter = adapter or RuntimeToolInvocationAdapter()
        self._envelope_schema_path = (
            envelope_schema_path or _DEFAULT_ENVELOPE_SCHEMA_PATH
        )

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
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Tool '{intent.tool_name.value}' is not supported for "
                    "validate-only execution"
                ),
            )

        # ── Run adapter prepare ────────────────────────────────────
        envelope = self._adapter.prepare(intent, resolution)

        # ── Handle blocked/refused ─────────────────────────────────
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )

        # ── Validate envelope against schema ───────────────────────
        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            return RuntimeToolExecutionResult(
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

        # ── Execute validate tool ──────────────────────────────────
        try:
            result = await self._run_validate_tool(envelope)
        except Exception as e:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=True,
                error_kind="execution_error",
                refusal_reason=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        # ── Build receipt hash ─────────────────────────────────────
        receipt_sha256: str | None = None
        receipt: Any = None
        try:
            receipt = self._build_validate_receipt(result)
            rj = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
            receipt_sha256 = hashlib.sha256(rj.encode()).hexdigest()
        except Exception:
            pass

        # ── Extract receipt metadata ───────────────────────────────
        receipt_kind = "validate"
        receipt_schema_version = None
        if receipt is not None:
            receipt_schema_version = getattr(receipt, "schema_version", None)

        duration = (time.perf_counter() - start) * 1000

        # ── Map validate status to execution status ────────────────
        execution_status = RuntimeToolExecutionStatus.COMPLETED
        tool_status = getattr(result, "status", "unknown")
        tool_error_kind = getattr(result, "error_kind", None)
        tool_refusal = getattr(result, "refusal_reason", None)

        if tool_status in {"refused", "blocked"}:
            execution_status = RuntimeToolExecutionStatus.REFUSED
        elif tool_status == "failed":
            execution_status = RuntimeToolExecutionStatus.COMPLETED

        return RuntimeToolExecutionResult(
            status=execution_status,
            invocation_id=envelope.invocation_id,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name.value,
            envelope_schema_valid=True,
            tool_status=tool_status,
            tool_error_kind=tool_error_kind,
            receipt_sha256=receipt_sha256,
            duration_ms=duration,
            error_kind=tool_error_kind,
            refusal_reason=tool_refusal,
            tool_receipt_kind=receipt_kind,
            tool_receipt_schema_version=receipt_schema_version,
        )

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
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind="unsupported_tool",
                refusal_reason=(
                    f"Tool '{intent.tool_name.value}' is not supported for "
                    "search_replace execution"
                ),
            )

        # ── Run adapter prepare ────────────────────────────────────
        envelope = self._adapter.prepare(intent, resolution)

        # ── Handle blocked/refused ─────────────────────────────────
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
            )

        # ── Validate envelope against schema ───────────────────────
        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            return RuntimeToolExecutionResult(
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

        # ── Execute search_replace tool ────────────────────────────
        try:
            result = await self._run_search_replace_tool(envelope)
        except Exception as e:
            return RuntimeToolExecutionResult(
                status=RuntimeToolExecutionStatus.FAILED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=True,
                error_kind="execution_error",
                refusal_reason=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        # ── Build receipt hash ─────────────────────────────────────
        receipt_sha256: str | None = None
        try:
            receipt = self._build_search_replace_receipt(result)
            rj = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
            receipt_sha256 = hashlib.sha256(rj.encode()).hexdigest()
        except Exception:
            pass

        duration = (time.perf_counter() - start) * 1000

        # ── Map search_replace status to execution status ──────────
        execution_status = RuntimeToolExecutionStatus.COMPLETED
        tool_status = getattr(result, "status", "unknown")
        tool_error_kind = getattr(result, "error_kind", None)
        tool_refusal = getattr(result, "refusal_reason", None)

        if tool_status in {"refused", "blocked"}:
            execution_status = RuntimeToolExecutionStatus.REFUSED
        elif tool_status in {"no_match", "ambiguous_match", "count_mismatch"}:
            execution_status = RuntimeToolExecutionStatus.COMPLETED

        return RuntimeToolExecutionResult(
            status=execution_status,
            invocation_id=envelope.invocation_id,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name.value,
            envelope_schema_valid=True,
            tool_status=tool_status,
            tool_error_kind=tool_error_kind,
            receipt_sha256=receipt_sha256,
            duration_ms=duration,
            error_kind=tool_error_kind,
            refusal_reason=tool_refusal,
        )

    # ── Internal helpers ───────────────────────────────────────────

    async def _run_validate_tool(self, envelope: RuntimeToolInvocationEnvelope) -> Any:
        """Run the validate tool and extract the final result.

        The validate tool's run() method is an AsyncGenerator that yields
        ToolStreamEvent | ValidateResult. The final yielded value is the
        ValidateResult, which we extract via anext().
        """
        from vibe.core.tools.base import BaseToolState
        from vibe.core.tools.builtins.validate import Validate, ValidateArgs
        from vibe.core.tools.builtins.validate_models import ValidateToolConfig

        payload = envelope.payload or {}

        args = ValidateArgs(
            profile=payload.get("profile", "quick"),
            paths=payload.get("paths") or [],
            workspace_root=envelope.worktree_path or envelope.repo_root or None,
        )

        config = ValidateToolConfig()
        tool = Validate(config_getter=lambda: config, state=BaseToolState())
        agen: AsyncGenerator[Any, None] = tool.run(args)
        result: Any = None
        while True:
            try:
                item = await anext(agen)  # type: ignore[arg-type]
                result = item
            except StopAsyncIteration:
                break

        return result

    async def _run_search_replace_tool(
        self, envelope: RuntimeToolInvocationEnvelope
    ) -> Any:
        """Run the search_replace tool and extract the final result.

        The search_replace tool's run() method is an AsyncGenerator that
        yields ToolStreamEvent | SearchReplaceResult. The final yielded
        value is the SearchReplaceResult, extracted via anext().
        """
        from vibe.core.tools.base import BaseToolState
        from vibe.core.tools.builtins.search_replace import (
            SearchReplace,
            SearchReplaceArgs,
            SearchReplaceConfig,
        )

        payload = envelope.payload or {}

        args = SearchReplaceArgs(
            file_path=payload.get("file_path", ""),
            content=payload.get("content", ""),
            workspace_root=envelope.worktree_path or envelope.repo_root or None,
        )

        config = SearchReplaceConfig()
        tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())
        agen: AsyncGenerator[Any, None] = tool.run(args)
        result: Any = None
        while True:
            try:
                item = await anext(agen)  # type: ignore[arg-type]
                result = item
            except StopAsyncIteration:
                break

        return result

    @staticmethod
    def _build_validate_receipt(result: Any) -> Any:
        """Build a receipt from a validate result."""
        from vibe.core.tools.base import BaseToolState
        from vibe.core.tools.builtins.validate import Validate
        from vibe.core.tools.builtins.validate_models import ValidateToolConfig

        tool = Validate(
            config_getter=lambda: ValidateToolConfig(), state=BaseToolState()
        )
        return tool.build_receipt(result)

    @staticmethod
    def _build_search_replace_receipt(result: Any) -> Any:
        """Build a receipt from a search_replace result."""
        from vibe.core.tools.base import BaseToolState
        from vibe.core.tools.builtins.search_replace import (
            SearchReplace,
            SearchReplaceConfig,
        )

        tool = SearchReplace(
            config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
        )
        return tool.build_receipt(result)

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
