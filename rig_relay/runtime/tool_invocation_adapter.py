"""RuntimeToolInvocationAdapter — converts context + intent into safe invocation envelopes.

This module defines the adapter that bridges RuntimeContextResolution and
high-level tool intents into structured invocation envelopes or refusals.

Key distinction: Invocation envelopes carry tool input payloads needed to
execute the tool. They are NOT receipts — they must not be indexed as
evidence. Receipts are content-light; invocation envelopes may contain
payload content (file content, SEARCH/REPLACE blocks) that the tool needs.

No tools are executed. No leases are acquired. No files are mutated.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.execution_request import ExecutionRequest
from rig_relay.runtime.models import RuntimeCapabilityKind

# ── Enums ──────────────────────────────────────────────────────────────


class RuntimeToolName(StrEnum):
    """Known tool names the adapter can prepare invocations for."""

    WRITE_FILE = "write_file"
    SEARCH_REPLACE = "search_replace"
    SEARCH_REPLACE_PROPOSAL = "search_replace_proposal"
    CREATE_PENDING_SEARCH_REPLACE_PROPOSAL = "create_pending_search_replace_proposal"
    VALIDATE = "validate"
    RUNTIME_EXEC = "runtime_exec"
    BASH_LEGACY = "bash_legacy"
    GIT_STATUS = "git_status"
    GIT_DIFF = "git_diff"
    GIT_LOG = "git_log"
    GIT_BRANCH = "git_branch"
    GIT_SHOW = "git_show"
    GIT_LS_FILES = "git_ls_files"
    CHECKPOINT = "checkpoint"

    @property
    def mutation_class(self) -> ToolMutationClass:
        """Canonical mutation classification for this tool name.

        Enriches the existing runtime tool name registry with tool contract metadata.
        This is NOT a separate registry — it is canonical metadata on the one
        RuntimeToolName registry used by the runtime execution spine.
        """
        match self:
            case (
                RuntimeToolName.VALIDATE
                | RuntimeToolName.GIT_STATUS
                | RuntimeToolName.GIT_DIFF
                | RuntimeToolName.GIT_LOG
                | RuntimeToolName.GIT_BRANCH
                | RuntimeToolName.GIT_SHOW
                | RuntimeToolName.GIT_LS_FILES
            ):
                return ToolMutationClass.READ_ONLY
            case RuntimeToolName.RUNTIME_EXEC:
                return ToolMutationClass.UNKNOWN
            case _:
                return ToolMutationClass.WRITES_WORKSPACE


class RuntimeToolInvocationStatus(StrEnum):
    """Status of a prepared invocation envelope."""

    PREPARED = "prepared"
    BLOCKED = "blocked"
    REFUSED = "refused"


class RuntimeToolInvocationErrorKind(StrEnum):
    """Structured error kinds for blocked/refused invocations."""

    CONTEXT_UNRESOLVED = "context_unresolved"
    SESSION_REQUIRED = "session_required"
    TASK_REQUIRED = "task_required"
    WORKTREE_REQUIRED = "worktree_required"
    UNSAFE_PATH = "unsafe_path"
    DIRTY_POLICY_FAILED = "dirty_policy_failed"
    LEASE_CONFLICT = "lease_conflict"
    PATH_RESERVED = "path_reserved"
    EXPECTED_HASH_MISSING = "expected_hash_missing"
    UNSUPPORTED_TOOL = "unsupported_tool"
    UNSUPPORTED_MUTATION_LOCATION = "unsupported_mutation_location"
    INVALID_PAYLOAD = "invalid_payload"


# ── Input model ────────────────────────────────────────────────────────


class RuntimeToolIntent(BaseModel):
    """High-level intent to invoke a tool under runtime context.

    Carries the tool name, payload, and policy hints. The adapter combines
    this with a RuntimeContextResolution to produce an invocation envelope.

    payload is tool-specific:
    - write_file: {"path": str, "content": str, "overwrite": bool,
                   "expected_before_sha256": str | None}
    - search_replace: {"file_path": str, "content": str,
                       "expected_before_sha256": str | None}
    - validate: {"profile": str | None, "paths": list[str] | None}
    - runtime_exec: {"argv": list[str], "timeout_ms": int, "purpose": str,
                     "cwd": str | None}
    - bash_legacy: {"command": str, "legacy_fallback_allowed": bool}
    """

    model_config = ConfigDict(extra="forbid")

    intent_id: str
    tool_name: RuntimeToolName
    payload: dict[str, Any]
    requested_paths: list[str] = Field(default_factory=list)
    require_worktree: bool = False
    allow_main_repo_mutation: bool = False

    # ── Context propagation (Otel-inspired) ───────────────────────
    mission_id: str | None = None
    agent_id: str | None = None
    lease_id: str | None = None
    parent_event_id: str | None = None


# ── Output envelope ────────────────────────────────────────────────────


class RuntimeToolInvocationEnvelope(BaseModel):
    """Structured invocation envelope for tool execution.

    Contains canonical runtime metadata injected from the resolved context
    plus the tool payload. The payload may contain file content (write_file)
    or SEARCH/REPLACE blocks (search_replace) — this is NOT a receipt and
    must not be indexed as evidence.

    Status:
    - prepared: ready for tool execution
    - blocked: context or policy prevented preparation
    - refused: tool/path/payload was invalid
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.runtime_tool_invocation.v1"
    invocation_id: str
    intent_id: str
    tool_name: RuntimeToolName
    status: RuntimeToolInvocationStatus

    # Canonical runtime context (injected from resolution)
    session_id: str | None = None
    task_id: str | None = None
    lane_id: str | None = None
    workspace_id: str | None = None
    worktree_path: str | None = None
    repo_root: str | None = None
    cwd: str | None = None

    # Tool payload (NOT content-light — contains tool input)
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_paths: list[str] = Field(default_factory=list)

    # Coordination policy
    coordination_enabled: bool = True
    lease_ttl_seconds: int | None = None

    # ── Context propagation (Otel-inspired) ───────────────────────
    mission_id: str | None = None
    agent_id: str | None = None
    lease_id: str | None = None
    parent_event_id: str | None = None

    # Refusal details
    error_kind: RuntimeToolInvocationErrorKind | None = None
    refusal_reason: str | None = None


# ── Adapter ────────────────────────────────────────────────────────────


class RuntimeToolInvocationAdapter:
    """Converts RuntimeContextResolution + RuntimeToolIntent into invocation envelopes.

    This is a pure translation layer: no I/O, no tool execution, no lease
    acquisition, no file mutation. Outputs are structured invocation
    envelopes or structured refusals.
    """

    def prepare(  # noqa: PLR0911
        self, intent: RuntimeToolIntent, resolution: RuntimeContextResolution
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare an invocation envelope from intent and context resolution.

        Returns a prepared envelope with canonical runtime metadata injected,
        or a blocked/refused envelope when context or policy prevents it.
        """
        base_envelope = RuntimeToolInvocationEnvelope(
            invocation_id=intent.intent_id,
            intent_id=intent.intent_id,
            tool_name=intent.tool_name,
            status=RuntimeToolInvocationStatus.PREPARED,
            payload=dict(intent.payload),
            requested_paths=list(intent.requested_paths),
        )

        # ── Check resolution status ─────────────────────────────────
        if resolution.status != "resolved":
            return _blocked(
                base_envelope,
                RuntimeToolInvocationErrorKind.CONTEXT_UNRESOLVED,
                resolution.refusal_reason
                or "Context resolution status is not 'resolved'",
            )

        if resolution.context is None:
            return _blocked(
                base_envelope,
                RuntimeToolInvocationErrorKind.CONTEXT_UNRESOLVED,
                "Context resolution status is 'resolved' but context is None",
            )

        ctx = resolution.context

        # ── Validate session/task ───────────────────────────────────
        if not ctx.session_id:
            return _blocked(
                base_envelope,
                RuntimeToolInvocationErrorKind.SESSION_REQUIRED,
                "Resolved context has no session_id",
            )
        if not ctx.task_id:
            return _blocked(
                base_envelope,
                RuntimeToolInvocationErrorKind.TASK_REQUIRED,
                "Resolved context has no task_id",
            )

        # ── Check worktree requirement ──────────────────────────────
        if intent.require_worktree and not ctx.worktree_path:
            return _blocked(
                base_envelope,
                RuntimeToolInvocationErrorKind.WORKTREE_REQUIRED,
                "Intent requires a worktree but context has no worktree_path",
            )

        # ── Determine cwd ───────────────────────────────────────────
        effective_cwd: str | None = None
        if ctx.worktree_path:
            effective_cwd = ctx.worktree_path
        elif ctx.repo_root:
            effective_cwd = ctx.repo_root
        else:
            effective_cwd = None

        # ── Validate requested paths ────────────────────────────────
        safe_paths = self._resolve_paths(
            intent.requested_paths, ctx.worktree_path, ctx.repo_root
        )
        if safe_paths is not None:
            pass  # paths are safe
        elif intent.requested_paths:
            return _refused(
                base_envelope,
                RuntimeToolInvocationErrorKind.UNSAFE_PATH,
                "Requested paths could not be resolved within context scope",
            )

        # ── Inject canonical metadata ───────────────────────────────
        base_envelope.session_id = ctx.session_id
        base_envelope.task_id = ctx.task_id
        base_envelope.lane_id = ctx.lane_id
        base_envelope.workspace_id = ctx.workspace_id
        base_envelope.worktree_path = ctx.worktree_path
        base_envelope.repo_root = ctx.repo_root
        base_envelope.cwd = effective_cwd
        base_envelope.coordination_enabled = ctx.coordination_enabled

        # ── Propagate context fields ───────────────────────────────
        base_envelope.mission_id = intent.mission_id
        base_envelope.agent_id = intent.agent_id
        base_envelope.lease_id = intent.lease_id
        base_envelope.parent_event_id = intent.parent_event_id

        # ── Tool-specific validation ────────────────────────────────
        return self._apply_tool_policy(intent, base_envelope, ctx)

    def _apply_tool_policy(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Apply tool-specific policy checks and payload normalization."""
        tool = intent.tool_name

        if tool in {
            RuntimeToolName.GIT_STATUS,
            RuntimeToolName.GIT_DIFF,
            RuntimeToolName.GIT_LOG,
            RuntimeToolName.GIT_BRANCH,
            RuntimeToolName.GIT_SHOW,
            RuntimeToolName.GIT_LS_FILES,
            RuntimeToolName.CHECKPOINT,
        }:
            return _prepared(envelope, intent.payload)

        if tool in {
            RuntimeToolName.WRITE_FILE,
            RuntimeToolName.SEARCH_REPLACE,
            RuntimeToolName.SEARCH_REPLACE_PROPOSAL,
            RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
            RuntimeToolName.VALIDATE,
            RuntimeToolName.RUNTIME_EXEC,
            RuntimeToolName.BASH_LEGACY,
        }:
            return self._apply_non_git_tool_policy(intent, envelope, ctx)

        return _refused(
            envelope,
            RuntimeToolInvocationErrorKind.UNSUPPORTED_TOOL,
            f"Unsupported tool: {tool}",
        )

    def _apply_non_git_tool_policy(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Apply policy for tools that need detailed payload normalization."""
        tool = intent.tool_name
        if tool == RuntimeToolName.WRITE_FILE:
            return self._prepare_write_file(intent, envelope, ctx)
        if tool == RuntimeToolName.SEARCH_REPLACE:
            return self._prepare_search_replace(intent, envelope, ctx)
        if tool == RuntimeToolName.SEARCH_REPLACE_PROPOSAL:
            return self._prepare_search_replace_proposal(intent, envelope)
        if tool == RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL:
            return self._prepare_create_pending_search_replace_proposal(
                intent, envelope
            )
        if tool == RuntimeToolName.VALIDATE:
            return self._prepare_validate(intent, envelope, ctx)
        if tool == RuntimeToolName.RUNTIME_EXEC:
            return self._prepare_runtime_exec(intent, envelope, ctx)
        if tool == RuntimeToolName.BASH_LEGACY:
            return self._prepare_bash_legacy(intent, envelope)
        return _refused(
            envelope,
            RuntimeToolInvocationErrorKind.UNSUPPORTED_TOOL,
            f"Unsupported tool: {tool}",
        )

    def _prepare_write_file(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare write_file envelope: resolve path, enforce hash for protected."""
        payload = dict(intent.payload)
        target_path = payload.get("path", "")

        if not target_path:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "write_file payload requires 'path'",
            )
        if "content" not in payload:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "write_file payload requires 'content'",
            )

        # Mutation in main repo not allowed unless explicitly permitted
        if not intent.allow_main_repo_mutation and (ctx.worktree_path is None):
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.UNSUPPORTED_MUTATION_LOCATION,
                "write_file mutation requires a worktree context; "
                "set allow_main_repo_mutation=True to override",
            )

        # If overwriting a protected file and expected_before_sha256 is missing, refuse
        allow_overwrite_protected = payload.get("allow_overwrite_protected", False)
        expected_hash = payload.get("expected_before_sha256")
        if allow_overwrite_protected and not expected_hash:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.EXPECTED_HASH_MISSING,
                "allow_overwrite_protected=True requires expected_before_sha256",
            )

        return _prepared(envelope, payload)

    def _prepare_search_replace(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare search_replace envelope: require file_path + content."""
        payload = dict(intent.payload)
        file_path = payload.get("file_path", "")

        if not file_path:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "search_replace payload requires 'file_path'",
            )
        if "content" not in payload:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "search_replace payload requires 'content' (SEARCH/REPLACE blocks)",
            )

        if not intent.allow_main_repo_mutation and (ctx.worktree_path is None):
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.UNSUPPORTED_MUTATION_LOCATION,
                "search_replace mutation requires a worktree context; "
                "set allow_main_repo_mutation=True to override",
            )

        return _prepared(envelope, payload)

    def _prepare_search_replace_proposal(
        self, intent: RuntimeToolIntent, envelope: RuntimeToolInvocationEnvelope
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare search_replace_proposal: require file_path + content.

        Like _prepare_search_replace but skips the mutation-location check
        because proposals do not mutate the active workspace. Path safety
        and dirty-guard checks are handled inside SearchReplace.compute_proposal().
        """
        payload = dict(intent.payload)
        file_path = payload.get("file_path", "")

        if not file_path:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "search_replace_proposal payload requires 'file_path'",
            )
        if "content" not in payload:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "search_replace_proposal payload requires 'content' (SEARCH/REPLACE blocks)",
            )

        return _prepared(envelope, payload)

    def _prepare_create_pending_search_replace_proposal(
        self, intent: RuntimeToolIntent, envelope: RuntimeToolInvocationEnvelope
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare create_pending_search_replace_proposal envelope.

        Requires file_path, content (SEARCH/REPLACE blocks), and
        idempotency_key in the payload. Candidate verification and
        proposal persistence occur during runtime execution — this
        adapter only validates required fields are present.
        """
        payload = dict(intent.payload)
        file_path = payload.get("file_path", "")
        if not file_path:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "create_pending_search_replace_proposal requires 'file_path'",
            )
        if "content" not in payload:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "create_pending_search_replace_proposal requires 'content'",
            )
        if "idempotency_key" not in payload:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "create_pending_search_replace_proposal requires 'idempotency_key'",
            )
        return _prepared(envelope, payload)

    def _prepare_validate(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare validate envelope: inject profile/paths/dirty_policy."""
        payload = dict(intent.payload)
        profile = payload.get("profile", "quick")
        paths = payload.get("paths")

        # Normalize
        normalized: dict[str, Any] = {
            "profile": profile,
            "paths": paths,
            "dirty_policy": ctx.dirty_policy or "inherit",
        }
        if ctx.worktree_path:
            normalized["worktree_path"] = ctx.worktree_path
        if ctx.repo_root:
            normalized["repo_root"] = ctx.repo_root

        return _prepared(envelope, normalized)

    def _prepare_runtime_exec(
        self,
        intent: RuntimeToolIntent,
        envelope: RuntimeToolInvocationEnvelope,
        ctx: RuntimeContext,
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare runtime_exec envelope: build ExecutionRequest-shaped payload.

        Validates the payload by constructing an ExecutionRequest model.
        Does NOT acquire a lease or execute. Only builds the payload shape
        that an ExecutionRequest would need.
        """
        payload = dict(intent.payload)
        argv = payload.get("argv")
        timeout_ms = payload.get("timeout_ms", 30000)
        purpose = payload.get("purpose", "runtime execution")
        cwd = payload.get("cwd")

        if not argv or not isinstance(argv, list):
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "runtime_exec payload requires 'argv' as a non-empty list of strings",
            )

        exec_payload: dict[str, Any] = {
            "request_id": f"exec_{intent.intent_id}",
            "argv": list(argv),
            "timeout_ms": timeout_ms,
            "purpose": purpose,
            "cwd": cwd or envelope.cwd or "",
            "workspace_id": ctx.workspace_id,
            "worktree_path": ctx.worktree_path,
            "env_overlay": payload.get("env_overlay", {}),
            "requested_capabilities": payload.get("requested_capabilities", []),
            "mission_id": intent.mission_id,
            "agent_id": intent.agent_id,
            "lease_id": intent.lease_id,
            "parent_event_id": intent.parent_event_id,
        }

        # Validate shape by constructing ExecutionRequest (no side effects)
        try:
            caps_raw = exec_payload["requested_capabilities"]
            ExecutionRequest(
                request_id=exec_payload["request_id"],
                argv=exec_payload["argv"],
                cwd=exec_payload["cwd"],
                env_overlay=exec_payload["env_overlay"],
                timeout_ms=exec_payload["timeout_ms"],
                purpose=exec_payload["purpose"],
                workspace_id=exec_payload["workspace_id"],
                worktree_path=exec_payload["worktree_path"],
                mission_id=exec_payload["mission_id"],
                agent_id=exec_payload["agent_id"],
                lease_id=exec_payload["lease_id"],
                parent_event_id=exec_payload["parent_event_id"],
                requested_capabilities=[
                    RuntimeCapabilityKind(c) if isinstance(c, str) else c
                    for c in caps_raw
                ],
            )
        except (ValueError, Exception) as e:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                f"Invalid execution request payload: {e}",
            )

        return _prepared(envelope, exec_payload)

    def _prepare_bash_legacy(
        self, intent: RuntimeToolIntent, envelope: RuntimeToolInvocationEnvelope
    ) -> RuntimeToolInvocationEnvelope:
        """Prepare bash_legacy envelope: refuse by default."""
        payload = dict(intent.payload)
        legacy_allowed = payload.get("legacy_fallback_allowed", False)

        if not legacy_allowed:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.UNSUPPORTED_TOOL,
                "bash_legacy is refused by default; set legacy_fallback_allowed=True "
                "to explicitly allow legacy bash execution",
            )

        command = payload.get("command", "")
        if not command:
            return _refused(
                envelope,
                RuntimeToolInvocationErrorKind.INVALID_PAYLOAD,
                "bash_legacy payload requires 'command'",
            )

        return _prepared(envelope, payload)

    @staticmethod
    def _resolve_paths(
        paths: list[str], worktree_path: str | None, repo_root: str | None
    ) -> list[str] | None:
        """Resolve paths against context scope. Returns None if any path is unsafe."""
        if not paths:
            return paths
        if repo_root is None:
            return paths
        repo = Path(repo_root).resolve()
        worktree = Path(worktree_path).resolve() if worktree_path else None
        for raw in paths:
            try:
                resolved = Path(raw).resolve()
            except (ValueError, OSError):
                return None
            try:
                resolved.relative_to(repo)
            except ValueError:
                return None
            if worktree is not None:
                try:
                    resolved.relative_to(worktree)
                except ValueError:
                    return None
        return paths


# ── Helpers ────────────────────────────────────────────────────────────


def _prepared(
    envelope: RuntimeToolInvocationEnvelope, payload: dict[str, Any]
) -> RuntimeToolInvocationEnvelope:
    """Return a prepared envelope with the given payload."""
    envelope.status = RuntimeToolInvocationStatus.PREPARED
    envelope.payload = payload
    envelope.error_kind = None
    envelope.refusal_reason = None
    return envelope


def _refused(
    envelope: RuntimeToolInvocationEnvelope,
    error_kind: RuntimeToolInvocationErrorKind,
    reason: str,
) -> RuntimeToolInvocationEnvelope:
    """Return a refused envelope — tool-level policy violation."""
    envelope.status = RuntimeToolInvocationStatus.REFUSED
    envelope.error_kind = error_kind
    envelope.refusal_reason = reason
    envelope.payload = {}
    return envelope


def _blocked(
    envelope: RuntimeToolInvocationEnvelope,
    error_kind: RuntimeToolInvocationErrorKind,
    reason: str,
) -> RuntimeToolInvocationEnvelope:
    """Return a blocked envelope — context-level issue (unresolved, missing context)."""
    envelope.status = RuntimeToolInvocationStatus.BLOCKED
    envelope.error_kind = error_kind
    envelope.refusal_reason = reason
    envelope.payload = {}
    return envelope


__all__ = [
    "RuntimeToolIntent",
    "RuntimeToolInvocationAdapter",
    "RuntimeToolInvocationEnvelope",
    "RuntimeToolInvocationErrorKind",
    "RuntimeToolInvocationStatus",
    "RuntimeToolName",
]
