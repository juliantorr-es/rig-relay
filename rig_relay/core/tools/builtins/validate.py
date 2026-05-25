"""Validate — read-only profile-based validation tool.

Stage 1: Read-Only Validate Profiles.
Stage 3: Path-Scoped Validation Profiles.

Composes known read-only command families (ruff, pyright, pytest, git,
schema validation, receipt-policy validation) into named profiles with
structured results and blocker taxonomy.

Not a general shell wrapper. Not a replacement for bash.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
import os
import time
from typing import Any, ClassVar, final

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import BaseTool, BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.validate_advice import (
    retryable as _validate_retryable,
    suggested_next_action as _validate_suggested_next_action,
)

# Git state
from rig_relay.core.tools.builtins.validate_git import (
    _check_dirty_policy,
    _collect_git_state,
    _parse_git_status_branch,
    _parse_git_status_porcelain,
    _parse_git_status_porcelain_line,
)

# Models
from rig_relay.core.tools.builtins.validate_models import (
    DIRTY_POLICY_ALLOW_DIRTY,
    DIRTY_POLICY_ALLOW_LISTED_DIRTY,
    DIRTY_POLICY_CLEAN,
    MAX_CAP_BYTES,
    VALIDATE_RECEIPT_SCHEMA_VERSION,
    Profile,
    ProfileCheck,
    ValidateArgs,
    ValidateCheckReceipt,
    ValidateCheckResult,
    ValidateGitState,
    ValidateReceipt,
    ValidateResult,
    ValidateToolConfig,
)

# Paths
from rig_relay.core.tools.builtins.validate_paths import (
    _is_python_path,
    _is_test_path,
    _normalize_validate_paths,
    _scope_check_argv,
)

# Profiles
from rig_relay.core.tools.builtins.validate_profiles import get_profile, list_profiles

# Runner
from rig_relay.core.tools.builtins.validate_runner import (
    _compute_fingerprint,
    _infer_kind_from_argv,
    _run_check,
    check_missing_dependency,
    classify_failure,
)
from rig_relay.core.tools.builtins.validate_state_machine import (
    ValidateProfileEvent,
    ValidateProfileStateMachine,
)

# Summaries
from rig_relay.core.tools.builtins.validate_summaries import (
    _parse_check_summary,
    _parse_policy_summary,
    _parse_pyright_summary,
    _parse_pytest_summary,
    _parse_ruff_summary,
    _parse_schema_summary,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolResultEvent, ToolStreamEvent
from rig_relay.evidence.validation_cache import (
    CACHE_POLICY_DISABLED,
    CACHE_STATUS_BLOCKED_RUNNING,
    CACHE_STATUS_DISABLED,
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS_RAN,
    ValidationCacheRecord,
    ValidationCacheStore,
    compute_cache_key,
    compute_input_fingerprint,
    decide_cache_eligibility,
)
from rig_relay.evidence.validation_scheduler import (
    PARALLEL_ENABLED,
    SCHEDULER_BLOCKED_DUPLICATE,
    SCHEDULER_COMPLETED,
    SCHEDULER_NOT_SCHEDULED,
    SCHEDULER_RUNNING,
    ValidationSchedulerStore,
    apply_parallel_policy,
    check_lifecycle_policy,
    resolve_cache_root,
    resolve_scheduler_root,
)


@dataclass(slots=True)
class _ValidateProfileRunContext:
    args: ValidateArgs
    profile: Profile
    normalized_paths: list[str]
    cwd: str
    output_cap: int
    cache_store: ValidationCacheStore
    scheduler_store: ValidationSchedulerStore
    cache_enabled: bool
    scheduler_enabled: bool
    scheduler_warnings: list[str]
    timeout: float
    state_machine: ValidateProfileStateMachine


@dataclass(slots=True)
class _ValidateCheckRunContext:
    run: _ValidateProfileRunContext
    check: ProfileCheck
    check_timeout: float
    run_argv: list[str]
    cmd_fp: str
    input_fp: str
    file_fps: dict[str, str]
    cache_key: str
    modified_argv: list[str]
    parallel_status: str


@dataclass(slots=True)
class _ValidateProfileExecutionContext:
    args: ValidateArgs
    ctx: InvokeContext | None
    profile: Profile
    start: float
    cwd: str
    state_machine: ValidateProfileStateMachine
    normalized_paths: list[str]
    before_git_state: ValidateGitState | None
    output_cap: int
    cache_store: ValidationCacheStore
    scheduler_store: ValidationSchedulerStore
    cache_enabled: bool
    scheduler_enabled: bool
    scheduler_warnings: list[str]
    prepared_digest: str | None = None
    worktree_matched: bool | None = None
    ignored_candidates: int = 0
    ignored_observable_count: int = 0
    ignored_disposable_count: int = 0
    ignored_unknown_count: int = 0


@dataclass(slots=True)
class _ValidateRunContext:
    start: float
    cwd: str
    output_cap: int
    cache_store: ValidationCacheStore
    scheduler_store: ValidationSchedulerStore
    cache_enabled: bool
    scheduler_enabled: bool
    scheduler_warnings: list[str]


__all__ = [
    "DIRTY_POLICY_ALLOW_DIRTY",
    "DIRTY_POLICY_ALLOW_LISTED_DIRTY",
    "DIRTY_POLICY_CLEAN",
    "MAX_CAP_BYTES",
    "VALIDATE_RECEIPT_SCHEMA_VERSION",
    "Profile",
    "ProfileCheck",
    "Validate",
    "ValidateArgs",
    "ValidateCheckReceipt",
    "ValidateCheckResult",
    "ValidateGitState",
    "ValidateReceipt",
    "ValidateResult",
    "ValidateToolConfig",
    "_check_dirty_policy",
    "_collect_git_state",
    "_compute_fingerprint",
    "_infer_kind_from_argv",
    "_normalize_validate_paths",
    "_parse_check_summary",
    "_parse_git_status_branch",
    "_parse_git_status_porcelain",
    "_parse_git_status_porcelain_line",
    "_parse_policy_summary",
    "_parse_pyright_summary",
    "_parse_pytest_summary",
    "_parse_ruff_summary",
    "_parse_schema_summary",
    "_run_check",
    "_scope_check_argv",
    "check_missing_dependency",
    "classify_failure",
    "get_profile",
    "list_profiles",
]


def _make_trace_on_transition(recorder: Any) -> Any:
    """Create an on_transition callback that emits trace events."""

    def _on_transition(**kwargs: Any) -> None:
        from_state = kwargs.get("from_state")
        to_state = kwargs.get("to_state")
        event = kwargs.get("event")
        reason = kwargs.get("reason")
        attrs_from_kwargs = kwargs.get("attributes", {}) or {}
        attrs: dict[str, object] = {
            "profile.state.from": from_state.value  # type: ignore[reportOptionalMemberAccess]
            if hasattr(from_state, "value")
            else str(from_state),
            "profile.state.to": to_state.value  # type: ignore[reportOptionalMemberAccess]
            if hasattr(to_state, "value")
            else str(to_state),
            "profile.event": event.value if hasattr(event, "value") else str(event),  # type: ignore[reportOptionalMemberAccess]
        }
        if reason:
            attrs["profile.reason"] = str(reason)[:200]
        if attrs_from_kwargs:
            safe = {
                k: v
                for k, v in attrs_from_kwargs.items()
                if k
                in {
                    "profile",
                    "check_count",
                    "check_name",
                    "check_kind",
                    "check_index",
                    "check_status",
                    "refusal_code",
                    "failure_kind",
                    "duration_ms",
                    "exit_code",
                }
            }
            attrs.update(safe)
        recorder.event("validate.state.transition", attributes=attrs)

    return _on_transition


class Validate(
    BaseTool[ValidateArgs, ValidateResult, ValidateToolConfig, BaseToolState],
    ToolUIData[ValidateArgs, ValidateResult],
):
    description: ClassVar[str] = (
        "Run a read-only validation profile. Returns structured results with blocker taxonomy.\n\n"
        "Available profiles:\n"
        "  quick — Fast git status + focused pytest. Use for fast feedback during editing.\n"
        "  python — ruff check + pyright + pytest. Use before committing or requesting review.\n"
        "  schemas — Schema and receipt validation. Use when modifying schema files.\n"
        "  receipt-policy — Content-light receipt validation. Use for evidence/telemetry changes.\n"
        "  tool-hardening — Deterministic tool-envelope checks. Use when modifying built-in tools.\n"
        "  worktree-readiness — Git state + dirty policy. Use before starting work in a lane.\n\n"
        "Use validate for fixed profile-based validation. For custom step sequences, use validation_suite."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY
    _MAX_CHANGED_PATHS_SHOWN: ClassVar[int] = 5

    @classmethod
    def format_call_display(cls, args: ValidateArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"validate: {args.profile}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ValidateResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        r = event.result
        return ToolResultDisplay(
            success=r.status == "passed",
            message=f"validate {r.profile}: {r.passed_count}/{r.command_count} passed, "
            f"{r.failed_count} failed, {r.skipped_count} skipped",
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Running validation"

    @final
    def build_receipt(self, result: ValidateResult) -> ValidateReceipt:
        check_receipts = [
            ValidateCheckReceipt(
                check_id=c.check_id,
                command_kind=c.command_kind,
                command_fingerprint=c.command_fingerprint,
                status=c.status,
                exit_code=c.exit_code,
                duration_ms=c.duration_ms,
                stdout_sha256=c.stdout_sha256,
                stderr_sha256=c.stderr_sha256,
                stdout_bytes=c.stdout_bytes,
                stderr_bytes=c.stderr_bytes,
                stdout_truncated=c.stdout_truncated,
                stderr_truncated=c.stderr_truncated,
                failure_kind=c.failure_kind,
                affected_paths=list(c.affected_paths),
            )
            for c in result.checks
        ]

        def _git_summary(gs: ValidateGitState | None) -> dict[str, int] | None:
            if gs is None:
                return None
            return {
                "dirty_count": gs.dirty_count,
                "modified_count": gs.modified_count,
                "deleted_count": gs.deleted_count,
                "untracked_count": gs.untracked_count,
                "staged_count": gs.staged_count,
                "conflicted_count": gs.conflicted_count,
            }

        return ValidateReceipt(
            profile=result.profile,
            scope=result.scope,
            status=result.status,
            command_count=result.command_count,
            passed_count=result.passed_count,
            failed_count=result.failed_count,
            skipped_count=result.skipped_count,
            duration_ms=result.duration_ms,
            suggested_next_action=(
                result.suggested_next_action or _validate_suggested_next_action(result)
            ),
            retryable=result.retryable
            if result.retryable is not None
            else _validate_retryable(result),
            blocker_summary=dict(result.blocker_summary),
            error_kind=result.error_kind,
            refusal_reason=result.refusal_reason,
            check_receipts=check_receipts,
            before_git_summary=_git_summary(result.before_git_state),
            after_git_summary=_git_summary(result.after_git_state),
        )

    def _resolve_paths(
        self, args: ValidateArgs, cwd: str
    ) -> tuple[list[str], str | None]:
        if not args.paths:
            return [], None
        return _normalize_validate_paths(args.paths, cwd)

    @staticmethod
    def _build_checks(
        profile: Profile, normalized_paths: list[str]
    ) -> list[ProfileCheck]:
        checks = list(profile.checks)
        if normalized_paths and profile.name == "quick":
            if any(_is_test_path(p) for p in normalized_paths):
                if not any(check.command_kind == "pytest" for check in checks):
                    checks.append(
                        ProfileCheck(
                            check_id="pytest",
                            command_kind="pytest",
                            argv=["uv", "run", "pytest"],
                            display="pytest (scoped)",
                        )
                    )
            if any(_is_python_path(p) for p in normalized_paths):
                checks.append(
                    ProfileCheck(
                        check_id="ruff_check",
                        command_kind="ruff",
                        argv=["uv", "run", "ruff", "check"],
                        display="ruff check (scoped)",
                    )
                )
        return checks

    @staticmethod
    def _skipped_result(check: ProfileCheck) -> ValidateCheckResult:
        fp = _compute_fingerprint(check.argv)
        return ValidateCheckResult(
            check_id=check.check_id,
            command_kind=check.command_kind,
            command_display=check.display,
            command_fingerprint=fp,
            status="skipped",
            failure_kind=None,
            stdout_bytes=0,
            stderr_bytes=0,
        )

    @staticmethod
    def _build_cached_result(
        check: ProfileCheck,
        cache_status: str,
        cache_key: str,
        input_fingerprint: str,
        record: ValidationCacheRecord | None,
    ) -> ValidateCheckResult:
        fp = _compute_fingerprint(check.argv)
        if record is not None:
            return ValidateCheckResult(
                check_id=check.check_id,
                command_kind=check.command_kind,
                command_display=check.display,
                command_fingerprint=fp,
                status=record.status,
                exit_code=record.exit_code,
                duration_ms=record.duration_ms,
                stdout_sha256=record.stdout_sha256,
                stderr_sha256=record.stderr_sha256,
                stdout_bytes=record.stdout_bytes,
                stderr_bytes=record.stderr_bytes,
                failure_kind=record.failure_kind,
                cache_status=cache_status,
                cache_key=cache_key,
                cache_record_sha256=record.record_sha256(),
                input_fingerprint=input_fingerprint,
                scheduler_status=SCHEDULER_COMPLETED,
            )
        return ValidateCheckResult(
            check_id=check.check_id,
            command_kind=check.command_kind,
            command_display=check.display,
            command_fingerprint=fp,
            status="skipped",
            cache_status=cache_status,
            cache_key=cache_key,
            input_fingerprint=input_fingerprint,
            scheduler_status=SCHEDULER_COMPLETED,
        )

    @staticmethod
    def _build_blocked_result(
        check: ProfileCheck,
        reason: str,
        cache_key: str | None = None,
        input_fingerprint: str | None = None,
        cache_status: str = CACHE_STATUS_BLOCKED_RUNNING,
    ) -> ValidateCheckResult:
        fp = _compute_fingerprint(check.argv)
        return ValidateCheckResult(
            check_id=check.check_id,
            command_kind=check.command_kind,
            command_display=check.display,
            command_fingerprint=fp,
            status="blocked",
            failure_kind=reason,
            cache_status=cache_status,
            cache_key=cache_key,
            input_fingerprint=input_fingerprint,
            scheduler_status=SCHEDULER_BLOCKED_DUPLICATE,
        )

    @staticmethod
    def _build_run_result(
        results: list[ValidateCheckResult],
        profile: Profile,
        start: float,
        before_git_state: ValidateGitState | None = None,
        after_git_state: ValidateGitState | None = None,
        prepared_index_tree_digest: str | None = None,
        worktree_matched_prepared_index: bool | None = None,
    ) -> ValidateResult:
        total_ms = (time.perf_counter() - start) * 1000
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status in {"skipped", "blocked"})
        timed_out = sum(1 for r in results if r.status == "timed_out")

        blocker_summary: dict[str, int] = {}
        for r in results:
            if r.failure_kind:
                blocker_summary[r.failure_kind] = (
                    blocker_summary.get(r.failure_kind, 0) + 1
                )

        overall_status = "passed"
        if failed > 0:
            overall_status = "failed"
        elif timed_out > 0:
            overall_status = "timed_out"
        elif skipped == len(results):
            overall_status = "skipped"

        result = ValidateResult(
            status=overall_status,
            profile=profile.name,
            command_count=len(results),
            passed_count=passed,
            failed_count=failed,
            skipped_count=skipped,
            duration_ms=total_ms,
            checks=results,
            blocker_summary=blocker_summary,
            before_git_state=before_git_state,
            after_git_state=after_git_state,
            prepared_index_tree_digest=prepared_index_tree_digest,
            worktree_matched_prepared_index=worktree_matched_prepared_index,
        )
        return result.model_copy(
            update={
                "suggested_next_action": _validate_suggested_next_action(result),
                "retryable": _validate_retryable(result),
            }
        )

    def _refuse(
        self, args: ValidateArgs, *, error_kind: str, reason: str
    ) -> ValidateResult:
        result = ValidateResult(
            status="refused",
            profile=args.profile,
            error_kind=error_kind,
            refusal_reason=reason,
        )
        return result.model_copy(
            update={
                "suggested_next_action": _validate_suggested_next_action(result),
                "retryable": _validate_retryable(result),
            }
        )

    def _denied_profile_reason(
        self, args: ValidateArgs, profile: Profile
    ) -> str | None:
        if args.env_profile is not None:
            return None
        if profile.allow_mutation and not args.allow_mutation:
            return "Profile requires mutation but --allow-mutation not set"
        if profile.allow_network and not args.allow_network:
            return "Profile requires network but --allow-network not set"
        return None

    def _build_run_context(
        self, args: ValidateArgs, ctx: InvokeContext | None
    ) -> _ValidateRunContext:
        start = time.perf_counter()
        output_cap = min(
            args.output_cap_bytes or self.config.default_output_cap, MAX_CAP_BYTES
        )
        cwd = args.workspace_root
        if cwd is None and ctx and ctx.session_dir:
            cwd = str(ctx.session_dir.parent.parent.resolve())
        if cwd is None:
            cwd = os.getcwd()
        cache_store = ValidationCacheStore(resolve_cache_root(args.cache_root, cwd))
        scheduler_store = ValidationSchedulerStore(resolve_scheduler_root(None, cwd))
        cache_enabled = args.cache_policy != CACHE_POLICY_DISABLED
        scheduler_enabled = args.scheduler_policy != "disabled"
        profile = get_profile(args.profile)
        scheduler_warnings = [
            warning
            for check in (profile.checks if profile is not None else [])
            for warning in check_lifecycle_policy(
                args.validation_phase, args.profile, check.argv
            )
        ]
        return _ValidateRunContext(
            start=start,
            cwd=cwd,
            output_cap=output_cap,
            cache_store=cache_store,
            scheduler_store=scheduler_store,
            cache_enabled=cache_enabled,
            scheduler_enabled=scheduler_enabled,
            scheduler_warnings=scheduler_warnings,
        )

    def _new_state_machine(self) -> ValidateProfileStateMachine:
        return ValidateProfileStateMachine()

    async def _run_profile_checks(
        self, run: _ValidateProfileRunContext
    ) -> list[ValidateCheckResult]:
        results: list[ValidateCheckResult] = []
        for check in self._build_checks(run.profile, run.normalized_paths):
            run.state_machine.transition(
                ValidateProfileEvent.CHECK_STARTED,
                reason="check started",
                attributes={
                    "profile": run.args.profile,
                    "check_id": check.check_id,
                    "command_kind": check.command_kind,
                },
            )
            results.append(await self._run_profile_check(run, check=check))
        return results

    async def _run_profile_check(
        self, run: _ValidateProfileRunContext, check: ProfileCheck
    ) -> ValidateCheckResult:
        prepared = await self._prepare_profile_check(run, check)
        if isinstance(prepared, ValidateCheckResult):
            return prepared
        cr = await self._execute_profile_check(prepared)
        if prepared.run.normalized_paths:
            cr.affected_paths = list(prepared.run.normalized_paths)
        if cr.status == "passed":
            prepared.run.state_machine.transition(
                ValidateProfileEvent.CHECK_PASSED,
                reason="check passed",
                attributes={
                    "profile": prepared.run.args.profile,
                    "check_id": check.check_id,
                },
            )
        elif cr.status == "failed":
            prepared.run.state_machine.transition(
                ValidateProfileEvent.CHECK_FAILED,
                reason="check failed",
                attributes={
                    "profile": prepared.run.args.profile,
                    "check_id": check.check_id,
                },
            )
        elif cr.status == "timed_out":
            prepared.run.state_machine.transition(
                ValidateProfileEvent.TIMEOUT,
                reason="check timed out",
                attributes={
                    "profile": prepared.run.args.profile,
                    "check_id": check.check_id,
                },
            )
        cr.cache_status = (
            CACHE_STATUS_MISS_RAN
            if prepared.run.cache_enabled
            else CACHE_STATUS_DISABLED
        )
        cr.cache_key = prepared.cache_key
        cr.input_fingerprint = prepared.input_fp
        cr.scheduler_status = (
            SCHEDULER_RUNNING
            if prepared.run.scheduler_enabled
            else SCHEDULER_NOT_SCHEDULED
        )
        cr.parallel_status = prepared.parallel_status
        cr.validation_phase = prepared.run.args.validation_phase
        if prepared.parallel_status == PARALLEL_ENABLED:
            cr.worker_count = prepared.run.args.max_workers or 4
            cr.distribution = prepared.run.args.xdist_distribution
        if prepared.run.cache_enabled and cr.status in {"passed", "failed"}:
            record = ValidationCacheRecord(
                cache_key=prepared.cache_key,
                check_id=check.check_id,
                command_kind=check.command_kind,
                command_fingerprint=prepared.cmd_fp,
                input_fingerprint=prepared.input_fp,
                input_file_fingerprints=prepared.file_fps,
                status=cr.status,
                exit_code=cr.exit_code,
                duration_ms=cr.duration_ms,
                stdout_sha256=cr.stdout_sha256,
                stderr_sha256=cr.stderr_sha256,
                stdout_bytes=cr.stdout_bytes,
                stderr_bytes=cr.stderr_bytes,
                failure_kind=cr.failure_kind,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                validation_phase=prepared.run.args.validation_phase,
                worker_count=cr.worker_count,
                distribution=cr.distribution,
                warnings=list(prepared.run.scheduler_warnings),
            )
            cr.cache_record_sha256 = record.record_sha256()
            prepared.run.cache_store.store(record)
        return cr

    async def _prepare_profile_check(
        self, run: _ValidateProfileRunContext, check: ProfileCheck
    ) -> _ValidateCheckRunContext | ValidateCheckResult:
        run_argv = check.argv
        if run.normalized_paths:
            scoped_argv, should_run = _scope_check_argv(check, run.normalized_paths)
            if not should_run:
                run.state_machine.transition(
                    ValidateProfileEvent.CHECK_SKIPPED,
                    reason="check skipped by path scope",
                    attributes={
                        "profile": run.args.profile,
                        "check_id": check.check_id,
                    },
                )
                return self._skipped_result(check)
            run_argv = scoped_argv
        if (check.allow_mutation and not run.args.allow_mutation) or (
            check.allow_network and not run.args.allow_network
        ):
            run.state_machine.transition(
                ValidateProfileEvent.CHECK_SKIPPED,
                reason="check skipped by policy",
                attributes={"profile": run.args.profile, "check_id": check.check_id},
            )
            return self._skipped_result(check)

        cmd_fp = _compute_fingerprint(run_argv)
        input_fp, file_fps = compute_input_fingerprint(
            run.cwd, cmd_fp, check.command_kind
        )
        cache_key = compute_cache_key(
            check.check_id, check.command_kind, cmd_fp, input_fp, run.cwd, run.cwd
        )
        if run.cache_enabled and run.args.cache_policy != "force_rerun":
            lookup = run.cache_store.lookup(cache_key)
            cache_status, _reason = decide_cache_eligibility(
                run.args.cache_policy, lookup, run.args.allow_failed_cache_reuse
            )
            if cache_status == CACHE_STATUS_HIT and lookup.record is not None:
                run.state_machine.transition(
                    ValidateProfileEvent.CHECK_PASSED,
                    reason="check returned from cache",
                    attributes={
                        "profile": run.args.profile,
                        "check_id": check.check_id,
                    },
                )
                return self._build_cached_result(
                    check, cache_status, cache_key, input_fp, lookup.record
                )
        if run.scheduler_enabled and run.args.lock_running_checks:
            acquired, _blocking_key = run.scheduler_store.acquire_lock(cache_key)
            if not acquired:
                run.state_machine.transition(
                    ValidateProfileEvent.CHECK_SKIPPED,
                    reason="validation already running",
                    attributes={
                        "profile": run.args.profile,
                        "check_id": check.check_id,
                    },
                )
                return self._build_blocked_result(
                    check,
                    reason="validation_already_running",
                    cache_key=cache_key,
                    input_fingerprint=input_fp,
                )
        modified_argv, parallel_status, parallel_warning = apply_parallel_policy(
            run_argv,
            run.args.parallel_policy,
            run.args.max_workers,
            run.args.xdist_distribution,
        )
        if parallel_warning:
            run.scheduler_warnings.append(parallel_warning)
        return _ValidateCheckRunContext(
            run=run,
            check=check,
            check_timeout=min(run.timeout, 600),
            run_argv=run_argv,
            cmd_fp=cmd_fp,
            input_fp=input_fp,
            file_fps=file_fps,
            cache_key=cache_key,
            modified_argv=modified_argv,
            parallel_status=parallel_status,
        )

    async def _execute_profile_check(
        self, prepared: _ValidateCheckRunContext
    ) -> ValidateCheckResult:
        try:
            return await _run_check(
                prepared.modified_argv,
                output_cap=prepared.run.output_cap,
                timeout=int(prepared.check_timeout),
                cwd=prepared.run.cwd,
            )
        finally:
            if prepared.run.scheduler_enabled:
                prepared.run.scheduler_store.release_lock(prepared.cache_key)

    def _check_preparation_binding(
        self, args: ValidateArgs, cwd: str, out_ignored: dict[str, int] | None = None
    ) -> tuple[str | None, bool | None, tuple[str, str, str, str] | None]:
        """Check worktree/index delta for preparation-bound validation.

        Returns (prepared_digest, worktree_matched, refusal_result).
        If refusal_result is not None, the caller should return it immediately.
        """
        if not args.preparation_receipt_sha256:
            return None, None, None
        try:
            from rig_relay.governance.auth_receipts import load_preparation_receipt

            receipt = load_preparation_receipt(args.preparation_receipt_sha256)
            if receipt is None:
                return (
                    None,
                    None,
                    (
                        "refused",
                        "preparation_receipt_missing",
                        "Preparation receipt not found. Run prepare_checkpoint again.",
                        "",
                    ),
                )

            prepared_digest: str | None = None

            expected_paths = receipt.get("prepared_paths", []) or []
            dig = receipt.get("post_index_tree_digest")
            if dig:
                prepared_digest = dig

            import subprocess as _sp

            from rig_relay.core.git_index_operations import compute_index_tree_digest

            current_digest = compute_index_tree_digest(cwd)
            if current_digest is None:
                return (
                    None,
                    None,
                    (
                        "refused",
                        "index_tree_digest_unavailable",
                        "Cannot compute current index tree digest. Index may be empty or unmerged.",
                        "Ensure the index has staged content and is fully merged before bound validation.",
                    ),
                )
            if prepared_digest is not None and current_digest != prepared_digest:
                return (
                    None,
                    None,
                    (
                        "refused",
                        "prepared_index_changed",
                        (
                            f"Current index tree digest ({current_digest[:12]}...) does not "
                            f"match preparation receipt ({prepared_digest[:12]}...). "
                            "The staged index has changed since preparation."
                        ),
                        "Re-inspect changes and create a new prepare_checkpoint request with updated expected file hashes.",
                    ),
                )

            # ── Verify branch binding ──
            receipt_branch = receipt.get("branch")
            if receipt_branch:
                branch_proc = _sp.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(cwd),
                )
                current_branch = (
                    branch_proc.stdout.strip() if branch_proc.returncode == 0 else None
                )
                if current_branch and current_branch != receipt_branch:
                    return (
                        None,
                        None,
                        (
                            "refused",
                            "preparation_branch_mismatch",
                            f"Receipt was prepared on branch '{receipt_branch}' but current branch is '{current_branch}'.",
                            "Run prepare_checkpoint on the current branch to create a branch-bound receipt.",
                        ),
                    )

            # ── Verify worktree_root binding ──
            from pathlib import Path

            receipt_worktree = receipt.get("worktree_root")
            if receipt_worktree:
                current_worktree_proc = _sp.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(cwd),
                )
                current_worktree = (
                    current_worktree_proc.stdout.strip()
                    if current_worktree_proc.returncode == 0
                    else None
                )
                if current_worktree:
                    try:
                        resolved_receipt_wt = str(Path(receipt_worktree).resolve())
                        resolved_current_wt = str(Path(current_worktree).resolve())
                    except Exception:
                        resolved_receipt_wt = receipt_worktree
                        resolved_current_wt = current_worktree
                    if resolved_receipt_wt != resolved_current_wt:
                        return (
                            None,
                            None,
                            (
                                "refused",
                                "preparation_worktree_mismatch",
                                "Receipt was prepared in a different worktree. Receipt worktree identity does not match current repository.",
                                "Run prepare_checkpoint in the current worktree to create a worktree-bound receipt.",
                            ),
                        )

            proc = _sp.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(cwd),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                changed = [p for p in proc.stdout.strip().splitlines() if p]
                prepared_changed = [p for p in changed if p in expected_paths]
                if prepared_changed:
                    visible = min(len(prepared_changed), self._MAX_CHANGED_PATHS_SHOWN)
                    extra = (
                        f" and {len(prepared_changed) - self._MAX_CHANGED_PATHS_SHOWN} more"
                        if len(prepared_changed) > self._MAX_CHANGED_PATHS_SHOWN
                        else ""
                    )
                    return (
                        None,
                        None,
                        (
                            "refused",
                            "worktree_changed_after_preparation",
                            (
                                f"Prepared paths have unstaged changes since preparation: "
                                f"{', '.join(prepared_changed[:visible])}" + extra
                            ),
                            "Review unstaged changes. Revert to match prepared index or run "
                            "prepare_checkpoint again with updated expected hashes.",
                        ),
                    )
                visible = min(len(changed), self._MAX_CHANGED_PATHS_SHOWN)
                extra = (
                    f" and {len(changed) - self._MAX_CHANGED_PATHS_SHOWN} more"
                    if len(changed) > self._MAX_CHANGED_PATHS_SHOWN
                    else ""
                )
                return (
                    None,
                    None,
                    (
                        "refused",
                        "unprepared_worktree_changes_present",
                        (
                            f"Unprepared worktree changes exist: "
                            f"{', '.join(changed[:visible])}"
                            + extra
                            + ". Broad validators like pytest/pyright can observe these files. "
                            "Revert or commit unrelated changes before bound validation."
                        ),
                        "Revert or stage unrelated changes before bound validation, "
                        "or run unbound validation if the changes are known-safe.",
                    ),
                )

            # ── Tracking variables for ignored-file classification ──
            _ignored_candidates = 0
            _ignored_observable_count = 0
            _ignored_disposable_count = 0
            _ignored_unknown_count = 0

            # Check untracked files that may be observable by broad validators
            untracked_proc = _sp.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(cwd),
            )
            if untracked_proc.returncode == 0 and untracked_proc.stdout.strip():
                untracked = [p for p in untracked_proc.stdout.strip().splitlines() if p]
                # Filter out known disposable directories
                disposable_prefixes = (
                    ".venv/",
                    "node_modules/",
                    "__pycache__/",
                    ".pytest_cache/",
                    ".mypy_cache/",
                    ".ruff_cache/",
                )
                _MAX_UNTRACKED_SHOWN = 5
                relevant_untracked = [
                    p
                    for p in untracked
                    if not any(p.startswith(prefix) for prefix in disposable_prefixes)
                ]
                if relevant_untracked:
                    return (
                        prepared_digest,
                        None,
                        (
                            "refused",
                            "relevant_untracked_files_present",
                            (
                                f"Relevant untracked files exist and may be observed by validators: "
                                f"{', '.join(relevant_untracked[:_MAX_UNTRACKED_SHOWN])}"
                                + (
                                    f" and {len(relevant_untracked) - _MAX_UNTRACKED_SHOWN} more"
                                    if len(relevant_untracked) > _MAX_UNTRACKED_SHOWN
                                    else ""
                                )
                            ),
                            "Remove, stage, or explicitly exclude untracked files before bound validation.",
                        ),
                    )

            # ── Check ignored files that may be observable by broad validators ──
            ignored_proc = _sp.run(
                ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(cwd),
            )
            if ignored_proc.returncode == 0 and ignored_proc.stdout.strip():
                ignored = [p for p in ignored_proc.stdout.strip().splitlines() if p]
                from rig_relay.core.observable_input_policy import (
                    classify_ignored_observable_inputs,
                )

                assessment = classify_ignored_observable_inputs(ignored)

                # Record counts for receipt
                _ignored_candidates = assessment.disposable_count
                _ignored_observable_count = assessment.observable_count
                _ignored_disposable_count = assessment.disposable_count
                _ignored_unknown_count = assessment.unknown_count

                if assessment.blocked:
                    max_shown = 5
                    if assessment.observable_count > 0:
                        shown = min(len(assessment.observable_paths), max_shown)
                        extra = (
                            f" and {len(assessment.observable_paths) - max_shown} more"
                            if len(assessment.observable_paths) > max_shown
                            else ""
                        )
                        return (
                            prepared_digest,
                            None,
                            (
                                "refused",
                                "ignored_observable_inputs_present",
                                (
                                    f"Ignored files that validators can observe exist: "
                                    f"{', '.join(assessment.observable_paths[:shown])}"
                                    + extra
                                    + ". These files are gitignored but may be imported "
                                    "or read during validation."
                                ),
                                "Remove, explicitly admit, or git-add these files before bound validation.",
                            ),
                        )
                    else:
                        shown = min(len(assessment.unknown_paths), max_shown)
                        extra = (
                            f" and {len(assessment.unknown_paths) - max_shown} more"
                            if len(assessment.unknown_paths) > max_shown
                            else ""
                        )
                        return (
                            prepared_digest,
                            None,
                            (
                                "refused",
                                "unknown_ignored_inputs_present",
                                (
                                    f"Unknown ignored files exist: "
                                    f"{', '.join(assessment.unknown_paths[:shown])}"
                                    + extra
                                    + ". These files may be observed during validation. "
                                    "Classify or remove them before bound validation."
                                ),
                                "Classify, remove, or explicitly admit these files before bound validation.",
                            ),
                        )

            # ── Store classification data for receipt generation ──
            if out_ignored is not None:
                out_ignored["ignored_candidates"] = _ignored_candidates
                out_ignored["ignored_observable_count"] = _ignored_observable_count
                out_ignored["ignored_disposable_count"] = _ignored_disposable_count
                out_ignored["ignored_unknown_count"] = _ignored_unknown_count

            return prepared_digest, True, None
        except Exception as exc:
            from rig_relay.core.logger import logger

            logger.error("Preparation binding check failed: %s", exc, exc_info=True)
            return (
                None,
                None,
                (
                    "refused",
                    "preparation_binding_error",
                    f"Preparation binding verification failed: {exc}. Cannot proceed with bound validation.",
                    "Run prepare_checkpoint again to create a fresh receipt and retry bound validation.",
                ),
            )

    async def _prepare_validate_profile_run(
        self, args: ValidateArgs, ctx: InvokeContext | None, recorder: Any | None = None
    ) -> _ValidateProfileExecutionContext | ValidateResult | str:
        profile = get_profile(args.profile)
        if profile is None:
            known = ", ".join(list_profiles())
            return self._refuse(
                args,
                error_kind="tool_refusal",
                reason=f"Unknown profile '{args.profile}'. Known profiles: {known}",
            )

        denied_reason = self._denied_profile_reason(args, profile)
        if denied_reason is not None:
            self._new_state_machine().transition(
                ValidateProfileEvent.PROFILE_REFUSED,
                reason=denied_reason,
                attributes={"profile": args.profile},
            )
            return denied_reason

        run_context = self._build_run_context(args, ctx)
        state_machine = ValidateProfileStateMachine(
            on_transition=_make_trace_on_transition(recorder) if recorder else None
        )
        state_machine.transition(
            ValidateProfileEvent.PROFILE_REQUESTED,
            reason="validate profile requested",
            attributes={"profile": args.profile},
        )
        normalized_paths, refusal = self._resolve_paths(args, run_context.cwd)
        if refusal:
            state_machine.transition(
                ValidateProfileEvent.PROFILE_REFUSED,
                reason=refusal,
                attributes={"profile": args.profile},
            )
            return self._refuse(args, error_kind="unsafe_paths", reason=refusal)

        before_git_state = await _collect_git_state(run_context.cwd)

        # ── Bound validation: verify prepared paths match index ───
        ignored_cls: dict[str, int] = {}
        prepared_digest_val, worktree_matched_val, refusal = (  # type: ignore[misc]
            self._check_preparation_binding(
                args, run_context.cwd, out_ignored=ignored_cls
            )
        )
        if refusal is not None:
            refusal_result = ValidateResult(
                status=refusal[0],
                profile=args.profile,
                error_kind=refusal[1],
                refusal_reason=refusal[2],
                suggested_next_action=refusal[3],
                prepared_index_tree_digest=prepared_digest_val,
                worktree_matched_prepared_index=False,
            )
            return refusal_result.model_copy(
                update={"retryable": _validate_retryable(refusal_result)}
            )

        policy_reason = _check_dirty_policy(
            before_git_state, args.expected_dirty_policy, normalized_paths
        )
        if policy_reason:
            state_machine.transition(
                ValidateProfileEvent.PROFILE_REFUSED,
                reason=policy_reason,
                attributes={"profile": args.profile},
            )
            refusal_result = ValidateResult(
                status="failed",
                profile=args.profile,
                error_kind="dirty_workspace",
                refusal_reason=policy_reason,
            )
            return ValidateResult(
                status="failed",
                profile=args.profile,
                error_kind="dirty_workspace",
                refusal_reason=policy_reason,
                before_git_state=before_git_state,
                blocker_summary={"dirty_workspace": 1},
                suggested_next_action=_validate_suggested_next_action(refusal_result),
                retryable=_validate_retryable(refusal_result),
            )

        state_machine.transition(
            ValidateProfileEvent.CHECKS_SELECTED,
            reason="checks selected",
            attributes={
                "profile": args.profile,
                "check_count": len(self._build_checks(profile, normalized_paths)),
            },
        )
        return _ValidateProfileExecutionContext(
            args=args,
            ctx=ctx,
            profile=profile,
            start=run_context.start,
            cwd=run_context.cwd,
            state_machine=state_machine,
            normalized_paths=normalized_paths,
            before_git_state=before_git_state,
            output_cap=run_context.output_cap,
            cache_store=run_context.cache_store,
            scheduler_store=run_context.scheduler_store,
            cache_enabled=run_context.cache_enabled,
            scheduler_enabled=run_context.scheduler_enabled,
            scheduler_warnings=run_context.scheduler_warnings,
            prepared_digest=prepared_digest_val,
            worktree_matched=worktree_matched_val,
            ignored_candidates=ignored_cls.get("ignored_candidates", 0),
            ignored_observable_count=ignored_cls.get("ignored_observable_count", 0),
            ignored_disposable_count=ignored_cls.get("ignored_disposable_count", 0),
            ignored_unknown_count=ignored_cls.get("ignored_unknown_count", 0),
        )

    async def _execute_validate_profile_run(
        self, run: _ValidateProfileExecutionContext
    ) -> AsyncGenerator[ToolStreamEvent | ValidateResult | str, None]:
        timeout = run.args.timeout_seconds or run.profile.default_timeout
        results = await self._run_profile_checks(
            _ValidateProfileRunContext(
                args=run.args,
                profile=run.profile,
                normalized_paths=run.normalized_paths,
                cwd=run.cwd,
                output_cap=run.output_cap,
                cache_store=run.cache_store,
                scheduler_store=run.scheduler_store,
                cache_enabled=run.cache_enabled,
                scheduler_enabled=run.scheduler_enabled,
                scheduler_warnings=run.scheduler_warnings,
                timeout=timeout,
                state_machine=run.state_machine,
            )
        )
        after_git_state = await _collect_git_state(run.cwd)
        overall_result = self._build_run_result(
            results,
            run.profile,
            run.start,
            before_git_state=run.before_git_state,
            after_git_state=after_git_state,
            prepared_index_tree_digest=run.prepared_digest,
            worktree_matched_prepared_index=run.worktree_matched,
        )

        # ── Persist durable validation receipt when bound ──────────────
        if (
            run.prepared_digest is not None
            and run.worktree_matched is True
            and run.args.preparation_receipt_sha256
        ):
            try:
                from rig_relay.governance.receipt_store import (
                    generate_validation_receipt,
                    persist_validation_receipt,
                )

                v_receipt = generate_validation_receipt(
                    preparation_receipt_sha256=run.args.preparation_receipt_sha256,
                    prepared_index_tree_digest=run.prepared_digest,
                    validation_profile=run.args.profile,
                    validation_outcome=(
                        "passed"
                        if overall_result.status == "passed"
                        else overall_result.status
                    ),
                    worktree_matched_prepared_index=run.worktree_matched,
                    untracked_observation_status=(
                        "classified_disposable_only"
                        if run.ignored_candidates == 0
                        else f"classified_{run.ignored_candidates}_disposable_excluded"
                    ),
                    observed_worktree_policy=(
                        "tracked_and_non_ignored_untracked_and_ignored_classified_v1"
                    ),
                    exclusion_categories=[
                        "venv",
                        "node_modules",
                        "pycache",
                        "pytest_cache",
                        "mypy_cache",
                        "ruff_cache",
                        "tox",
                        "eggs",
                        "build",
                        "dist",
                    ],
                    branch=(run.before_git_state.branch if run.before_git_state else "")
                    or "",
                    worktree_root=run.cwd,
                )
                persisted = persist_validation_receipt(v_receipt)
                if persisted is not None:
                    overall_result = overall_result.model_copy(
                        update={
                            "validation_receipt_sha256": v_receipt["receipt_sha256"]
                        }
                    )
            except Exception:
                pass

        run.state_machine.transition(
            ValidateProfileEvent.PROFILE_COMPLETED,
            reason=f"validate {overall_result.status}",
            attributes={"profile": run.args.profile, "status": overall_result.status},
        )
        yield overall_result

    async def run(  # type: ignore[override]
        self, args: ValidateArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ValidateResult | str, None]:
        trace_span: Any = None
        recorder: Any = None
        if ctx is not None and ctx.trace_recorder is not None:
            recorder = ctx.trace_recorder
            trace_span = recorder.start_span(
                "validate.profile", attributes={"profile": args.profile}
            )

        prepared = await self._prepare_validate_profile_run(args, ctx, recorder)
        if isinstance(prepared, _ValidateProfileExecutionContext):
            async for event in self._execute_validate_profile_run(prepared):
                yield event
            if trace_span is not None:
                from rig_relay.tracing.models import TraceStatus

                recorder.end_span(trace_span, status=TraceStatus.ok)
            return
        if trace_span is not None:
            from rig_relay.tracing.models import TraceStatus

            recorder.end_span(trace_span, status=TraceStatus.error)
        yield prepared
