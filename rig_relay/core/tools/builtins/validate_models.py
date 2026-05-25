"""Validate tool — models and constants.

All Pydantic models, data classes, and shared constants for the
validate tool subsystem. This module has zero dependencies on other
validate submodules — only stdlib, pydantic, and framework base types.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.tools.base import BaseToolConfig, ToolPermission

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
    """Invocation arguments for a validate profile run.

    Cache policy (cache_policy):
      - enabled: cache hits return without execution
      - disabled: bypass cache, always run
      - force_rerun: bypass cache and rerun even if cached

    Scheduler policy (scheduler_policy):
      - enabled: use running locks to prevent duplicate execution
      - disabled: bypass scheduler, skip lock

    Validation phase (validation_phase):
      - edit: conservative warnings for full-suite runs
      - pre_report: normal validation
      - cleanup: normal with cache
      - final: normal with cache
    """

    model_config = ConfigDict(extra="forbid")

    profile: str = Field(
        description="Validation profile: quick, python, schemas, receipt-policy, tool-hardening, worktree-readiness."
    )
    scope: str | None = Field(
        default=None, description="Optional scope identifier for profile filtering."
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Scope validation to specific repository-relative paths. Ruff and pytest auto-scoped to relevant file types.",
    )
    workspace_root: str | None = Field(
        default=None,
        description="Override workspace root path. Defaults to current working directory.",
    )
    timeout_seconds: int | None = Field(
        default=None, description="Override default profile timeout in seconds."
    )
    check_only: bool = Field(
        default=True,
        description="When True, run checks without applying fixes. Set False to allow auto-fixes where supported.",
    )
    allow_network: bool = Field(
        default=False, description="Allow profile checks that require network access."
    )
    allow_mutation: bool = Field(
        default=False,
        description="Allow profile checks that may modify files (e.g., auto-formatting).",
    )
    env_profile: str | None = Field(
        default=None, description="Environment profile override for check execution."
    )
    expected_dirty_policy: str | None = Field(
        default=None,
        description="Expected dirty workspace policy: allow_dirty, clean, allow_listed_dirty.",
    )
    output_cap_bytes: int | None = Field(
        default=None, description="Override default output byte cap for check results."
    )

    # ── Cache policy ──────────────────────────────────────────
    cache_policy: str = Field(
        default="enabled", description="Cache policy: enabled, disabled, force_rerun."
    )
    allow_failed_cache_reuse: bool = Field(
        default=False, description="Reuse cached results even when previous run failed."
    )
    cache_root: str | None = Field(
        default=None, description="Override cache storage location."
    )

    # ── Scheduler policy ──────────────────────────────────────
    scheduler_policy: str = Field(
        default="enabled",
        description="Scheduler policy for duplicate prevention: enabled, disabled.",
    )
    lock_running_checks: bool = Field(
        default=True, description="Prevent concurrent duplicate check execution."
    )
    validation_phase: str = Field(
        default="pre_report",
        description="Validation phase: edit (during editing), pre_report (before committing), cleanup, final.",
    )

    # ── Parallel policy ───────────────────────────────────────
    parallel_policy: str = Field(
        default="auto",
        description="Parallel execution policy: auto, enabled, disabled.",
    )
    max_workers: int | None = Field(
        default=None, description="Maximum parallel workers. None = auto-select."
    )
    xdist_distribution: str = Field(
        default="loadfile",
        description="pytest-xdist distribution mode: loadfile, load, each.",
    )

    preparation_receipt_sha256: str | None = Field(
        default=None,
        description="SHA256 of a durable preparation receipt from prepare_checkpoint. "
        "When provided, validate verifies prepared paths have no index/worktree "
        "delta before running checks, and records the prepared index digest in results.",
    )


# ── Check result model ────────────────────────────────────────────────


class ValidateCheckResult(BaseModel):
    """Result for one validate check with cache and scheduler metadata.

    Content-light: no raw stdout/stderr in long-lived fields.
    Cache/scheduler/parallel metadata describes the policy decisions
    that produced this result.
    """

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

    # ── Cache metadata ────────────────────────────────────────
    cache_status: str = "disabled"
    cache_key: str | None = None
    cache_record_sha256: str | None = None
    input_fingerprint: str | None = None
    reused_from: str | None = None

    # ── Scheduler metadata ────────────────────────────────────
    scheduler_status: str = "not_scheduled"
    parallel_status: str = "not_applicable"
    worker_count: int | None = None
    distribution: str | None = None
    validation_phase: str | None = None


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
    suggested_next_action: str | None = None
    retryable: bool | None = None
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
    suggested_next_action: str | None = None
    retryable: bool | None = None
    checks: list[ValidateCheckResult] = Field(default_factory=list)
    blocker_summary: dict[str, int] = Field(default_factory=dict)
    changed_files: list[str] | None = None
    before_git_state: ValidateGitState | None = None
    after_git_state: ValidateGitState | None = None
    prepared_index_tree_digest: str | None = Field(
        default=None,
        description="Index tree digest from preparation receipt, when validation was bound to a prepared state.",
    )
    worktree_matched_prepared_index: bool | None = Field(
        default=None,
        description="True when prepared paths had no worktree/index delta before validation ran. None when no preparation receipt was provided.",
    )
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
