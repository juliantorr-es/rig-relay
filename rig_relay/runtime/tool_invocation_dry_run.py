"""RuntimeToolDryRunRunner — validates adapter envelopes without executing tools.

Provides a dry-run integration layer that calls RuntimeToolInvocationAdapter.prepare(),
validates the resulting envelope against the runtime_tool_invocation schema, and
optionally validates tool-specific payload shape. No tools are executed, no leases
acquired, and no files mutated.

Key design decisions:
- Dry-run validates adapter output, not tool implementations.
- would_execute is always False — this is a dry run.
- would_mutate is a classification for write_file/search_replace, not an action.
- would_acquire_lease is always False.
- Envelope payloads may contain operational tool input (file content, SEARCH/REPLACE
  blocks). The dry-run result must NOT store raw content — only bool flags and paths.
"""

from __future__ import annotations

from enum import StrEnum
import json
from pathlib import Path
from typing import Any

import jsonschema
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

_SCHEMA_VERSION = "rig.relay.runtime_tool_invocation_dry_run.v1"

# Path to the runtime_tool_invocation schema relative to repo root
_DEFAULT_ENVELOPE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.runtime_tool_invocation.v1.schema.json"
)

# ── Enums ──────────────────────────────────────────────────────────────


class RuntimeToolDryRunStatus(StrEnum):
    """Status of a dry-run execution assessment."""

    WOULD_PREPARE = "would_prepare"
    BLOCKED = "blocked"
    REFUSED = "refused"
    INVALID = "invalid"


# ── Model ──────────────────────────────────────────────────────────────


class RuntimeToolDryRunResult(BaseModel):
    """Result of a dry-run tool invocation assessment.

    Content-light: no raw file contents, stdout, stderr, diffs, snippets,
    or secrets. Only boolean flags, paths, schema validity indicators,
    and structured error/refusal information.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    status: RuntimeToolDryRunStatus
    invocation_id: str | None = None
    intent_id: str
    tool_name: str
    envelope_schema_valid: bool = False
    tool_schema_valid: bool | None = None
    would_execute: bool = False
    would_mutate: bool = False
    would_acquire_lease: bool = False
    requested_paths: list[str] = Field(default_factory=list)
    error_kind: str | None = None
    refusal_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ── Dry-Run Runner ────────────────────────────────────────────────────


class RuntimeToolDryRunRunner:
    """Dry-run runner that validates adapter envelopes without executing tools.

    Usage::

        runner = RuntimeToolDryRunRunner()
        result = runner.dry_run(intent, resolution)

    No tools are executed, no leases acquired, no files mutated.
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

    def dry_run(
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolDryRunResult:
        """Run a dry-run assessment of a tool invocation.

        Calls RuntimeToolInvocationAdapter.prepare(), validates the
        resulting envelope, and returns a structured assessment without
        executing any tool, acquiring any lease, or mutating any file.

        Args:
            intent: The tool invocation intent.
            resolution: The resolved runtime context.

        Returns:
            A RuntimeToolDryRunResult with assessment data.
        """
        base_result = RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name.value,
            requested_paths=list(intent.requested_paths),
        )

        # ── Classify mutation potential ─────────────────────────────
        if intent.tool_name in {
            RuntimeToolName.WRITE_FILE,
            RuntimeToolName.SEARCH_REPLACE,
        }:
            base_result.would_mutate = True

        # ── Run adapter prepare ─────────────────────────────────────
        envelope = self._adapter.prepare(intent, resolution)

        # ── Reflect envelope status ─────────────────────────────────
        if envelope.status == RuntimeToolInvocationStatus.BLOCKED:
            return RuntimeToolDryRunResult(
                status=RuntimeToolDryRunStatus.BLOCKED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
                requested_paths=list(intent.requested_paths),
                would_mutate=base_result.would_mutate,
            )

        if envelope.status == RuntimeToolInvocationStatus.REFUSED:
            return RuntimeToolDryRunResult(
                status=RuntimeToolDryRunStatus.REFUSED,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                error_kind=envelope.error_kind.value if envelope.error_kind else None,
                refusal_reason=envelope.refusal_reason,
                requested_paths=list(intent.requested_paths),
                would_mutate=base_result.would_mutate,
            )

        # ── Validate envelope against schema ────────────────────────
        schema_valid, schema_errors = self._validate_envelope_schema(envelope)
        if not schema_valid:
            return RuntimeToolDryRunResult(
                status=RuntimeToolDryRunStatus.INVALID,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=False,
                error_kind="envelope_schema_invalid",
                refusal_reason=f"Envelope failed schema validation: {'; '.join(schema_errors)}",
                requested_paths=list(intent.requested_paths),
                would_mutate=base_result.would_mutate,
            )

        # ── Validate tool-specific payload shape ────────────────────
        tool_valid, tool_error = self._validate_tool_payload(
            intent.tool_name, envelope.payload
        )

        if not tool_valid:
            return RuntimeToolDryRunResult(
                status=RuntimeToolDryRunStatus.INVALID,
                intent_id=intent.intent_id,
                tool_name=intent.tool_name.value,
                envelope_schema_valid=True,
                tool_schema_valid=False,
                error_kind="invalid_payload",
                refusal_reason=tool_error,
                requested_paths=list(intent.requested_paths),
                would_mutate=base_result.would_mutate,
            )

        # ── Prepared — return assessment ────────────────────────────
        return RuntimeToolDryRunResult(
            status=RuntimeToolDryRunStatus.WOULD_PREPARE,
            invocation_id=envelope.invocation_id,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name.value,
            envelope_schema_valid=True,
            tool_schema_valid=True,
            would_execute=False,
            would_mutate=base_result.would_mutate,
            would_acquire_lease=False,
            requested_paths=list(intent.requested_paths),
        )

    # ── Internal helpers ───────────────────────────────────────────

    @staticmethod
    def _validate_tool_payload(  # noqa: PLR0911
        tool_name: RuntimeToolName, payload: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Validate tool-specific payload shape structurally.

        Checks for required fields based on the tool. Does NOT call any
        actual tool implementation.
        """
        if tool_name == RuntimeToolName.WRITE_FILE:
            if "path" not in payload:
                return False, "write_file payload missing required 'path'"
            if "content" not in payload:
                return False, "write_file payload missing required 'content'"
            return True, None

        if tool_name == RuntimeToolName.SEARCH_REPLACE:
            if "file_path" not in payload:
                return False, "search_replace payload missing required 'file_path'"
            if "content" not in payload:
                return (
                    False,
                    "search_replace payload missing required 'content' (SEARCH/REPLACE blocks)",
                )
            return True, None

        if tool_name == RuntimeToolName.VALIDATE:
            if "profile" not in payload:
                return False, "validate payload missing required 'profile'"
            return True, None

        if tool_name == RuntimeToolName.RUNTIME_EXEC:
            argv = payload.get("argv")
            if not argv or not isinstance(argv, list) or len(argv) == 0:
                return (
                    False,
                    "runtime_exec payload missing required 'argv' (non-empty list)",
                )
            return True, None

        if tool_name == RuntimeToolName.BASH_LEGACY:
            # bash_legacy is always refused by the adapter; this path
            # is reached only if the adapter allowed it (unlikely).
            return True, None

        return True, None

    def _validate_envelope_schema(
        self, envelope: RuntimeToolInvocationEnvelope
    ) -> tuple[bool, list[str]]:
        """Validate the envelope against the runtime_tool_invocation schema."""
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
    "RuntimeToolDryRunResult",
    "RuntimeToolDryRunRunner",
    "RuntimeToolDryRunStatus",
]
