"""Validate tool — models and constants.

All Pydantic models, data classes, and shared constants for the
validate tool subsystem. This module has zero dependencies on other
validate submodules — only stdlib, pydantic, and framework base types.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vibe.core.tools.base import BaseToolConfig, ToolPermission

# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_OUTPUT_CAP_BYTES: int = 65_536
MAX_CAP_BYTES: int = 524_288
SCHEMA_SCRIPT: str = "scripts/rig_relay_validate_schemas.py"
RECEIPT_SCRIPT: str = "scripts/rig_relay_validate_tool_receipts.py"
VALIDATE_RECEIPT_SCHEMA_VERSION: str = "rig.relay.validate_receipt.v1"

DIRTY_POLICY_ALLOW_DIRTY: str = "allow_dirty"
DIRTY_POLICY_CLEAN: str = "clean"
DIRTY_POLICY_ALLOW_LISTED_DIRTY: str = "allow_listed_dirty"

VALID_DIRTY_POLICIES: frozenset[str] = frozenset({
    DIRTY_POLICY_ALLOW_DIRTY,
    DIRTY_POLICY_CLEAN,
    DIRTY_POLICY_ALLOW_LISTED_DIRTY,
})


# ── Profile data classes ──────────────────────────────────────────────


class ProfileCheck:
    """A single check within a profile."""

    def __init__(
        self,
        check_id: str,
        command_kind: str,
        argv: list[str],
        display: str | None = None,
        *,
        allow_mutation: bool = False,
        allow_network: bool = False,
    ) -> None:
        self.check_id = check_id
        self.command_kind = command_kind
        self.argv = argv
        self.display = display or " ".join(argv)
        self.allow_mutation = allow_mutation
        self.allow_network = allow_network


class Profile:
    """A named validation profile with a list of checks."""

    def __init__(
        self,
        name: str,
        description: str,
        checks: list[ProfileCheck],
        default_timeout: int = 120,
        *,
        allow_mutation: bool = False,
        allow_network: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.checks = checks
        self.default_timeout = default_timeout
        self.allow_mutation = allow_mutation
        self.allow_network = allow_network


# ── Tool argument model ────────────────────────────────────────────────


class ValidateArgs(BaseModel):
    profile: str
    scope: str | None = None
    paths: list[str] = Field(default_factory=list)
    workspace_root: str | None = None
    timeout_seconds: int | None = None
    check_only: bool = True
    allow_network: bool = False
    allow_mutation: bool = False
    env_profile: str | None = None
    expected_dirty_policy: str | None = None
    output_cap_bytes: int | None = None


# ── Check result model ────────────────────────────────────────────────


class ValidateCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    command_kind: str
    command_display: str | None = None
    command_fingerprint: str | None = None
    status: str = "unknown"
    exit_code: int | None = None
    duration_ms: float | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    parsed_summary: dict[str, Any] | None = None
    failure_kind: str | None = None
    affected_paths: list[str] = Field(default_factory=list)


# ── Content-light receipt models ──────────────────────────────────────


class ValidateCheckReceipt(BaseModel):
    """Content-light receipt for a single validate check.

    Contains no raw stdout/stderr — only hashes, byte counts,
    truncation flags, timing, and failure classification.
    """

    model_config = ConfigDict(extra="forbid")

    check_id: str
    command_kind: str
    command_fingerprint: str | None = None
    status: str = "unknown"
    exit_code: int | None = None
    duration_ms: float | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    failure_kind: str | None = None
    affected_paths: list[str] = Field(default_factory=list)


class ValidateReceipt(BaseModel):
    """Content-light receipt for a validate invocation.

    Contains no raw stdout/stderr — only hashes, byte counts,
    per-check metadata, timing, and blocker summary.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = VALIDATE_RECEIPT_SCHEMA_VERSION
    profile: str
    scope: str | None = None
    status: str
    command_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duration_ms: float | None = None
    blocker_summary: dict[str, int] = Field(default_factory=dict)
    error_kind: str | None = None
    refusal_reason: str | None = None
    check_receipts: list[ValidateCheckReceipt] = Field(default_factory=list)
    before_git_summary: dict[str, int] | None = None
    after_git_summary: dict[str, int] | None = None


# ── Validate result model ─────────────────────────────────────────────


class ValidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "unknown"
    profile: str
    scope: str | None = None
    command_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duration_ms: float | None = None
    checks: list[ValidateCheckResult] = Field(default_factory=list)
    blocker_summary: dict[str, int] = Field(default_factory=dict)
    changed_files: list[str] | None = None
    before_git_state: ValidateGitState | None = None
    after_git_state: ValidateGitState | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None


# ── Tool config ────────────────────────────────────────────────────────


class ValidateToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    default_output_cap: int = DEFAULT_OUTPUT_CAP_BYTES


# ── Git state model ────────────────────────────────────────────────────


class ValidateGitState(BaseModel):
    """Content-light git workspace state snapshot.

    Contains no file contents, diffs, patch hunks, or raw git status
    output. Only counts, workspace-relative POSIX paths, and hashes.
    """

    model_config = ConfigDict(extra="forbid")

    branch: str | None = None
    head: str | None = None
    is_git_repo: bool = False
    is_worktree: bool = False
    upstream: str | None = None
    ahead_count: int = 0
    behind_count: int = 0
    dirty_count: int = 0
    modified_count: int = 0
    deleted_count: int = 0
    untracked_count: int = 0
    staged_count: int = 0
    conflicted_count: int = 0
    dirty_paths: list[str] = Field(default_factory=list)
    untracked_paths: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    status_porcelain_sha256: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
