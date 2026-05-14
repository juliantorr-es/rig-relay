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
import os
import time
from typing import ClassVar, final

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
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.tools.base import BaseTool, BaseToolState, InvokeContext

# Git state
from vibe.core.tools.builtins.validate_git import (
    _check_dirty_policy,
    _collect_git_state,
    _parse_git_status_branch,
    _parse_git_status_porcelain,
    _parse_git_status_porcelain_line,
)

# Models
from vibe.core.tools.builtins.validate_models import (
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
from vibe.core.tools.builtins.validate_paths import (
    _is_python_path,
    _normalize_validate_paths,
    _scope_check_argv,
)

# Profiles
from vibe.core.tools.builtins.validate_profiles import get_profile, list_profiles

# Runner
from vibe.core.tools.builtins.validate_runner import (
    _compute_fingerprint,
    _infer_kind_from_argv,
    _run_check,
    check_missing_dependency,
    classify_failure,
)

# Summaries
from vibe.core.tools.builtins.validate_summaries import (
    _parse_check_summary,
    _parse_policy_summary,
    _parse_pyright_summary,
    _parse_pytest_summary,
    _parse_ruff_summary,
    _parse_schema_summary,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent

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


class Validate(
    BaseTool[ValidateArgs, ValidateResult, ValidateToolConfig, BaseToolState],
    ToolUIData[ValidateArgs, ValidateResult],
):
    description: ClassVar[str] = (
        "Run a read-only validation profile (quick, python, schemas, "
        "receipt-policy, tool-hardening). Returns structured results "
        "with blocker taxonomy."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

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

        return ValidateResult(
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
        )

    # ruff: noqa: PLR0914
    async def run(
        self, args: ValidateArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ValidateResult, None]:
        start = time.perf_counter()
        scheduler_warnings: list[str] = []

        profile = get_profile(args.profile)
        if profile is None:
            known = ", ".join(list_profiles())
            yield ValidateResult(
                status="refused",
                profile=args.profile,
                error_kind="tool_refusal",
                refusal_reason=(
                    f"Unknown profile '{args.profile}'. Known profiles: {known}"
                ),
            )
            return

        if not args.allow_mutation and profile.allow_mutation:
            yield ValidateResult(
                status="refused",
                profile=args.profile,
                error_kind="forbidden_mutation",
                refusal_reason=(
                    f"Profile '{args.profile}' requires mutation but "
                    "allow_mutation is false"
                ),
            )
            return

        if not args.allow_network and profile.allow_network:
            yield ValidateResult(
                status="refused",
                profile=args.profile,
                error_kind="forbidden_network",
                refusal_reason=(
                    f"Profile '{args.profile}' requires network access but "
                    "allow_network is false"
                ),
            )
            return

        output_cap = args.output_cap_bytes or self.config.default_output_cap
        output_cap = min(output_cap, MAX_CAP_BYTES)

        cwd = args.workspace_root
        if cwd is None and ctx and ctx.session_dir:
            cwd = str(ctx.session_dir.parent.parent.resolve())
        if cwd is None:
            cwd = os.getcwd()

        cache_root = resolve_cache_root(args.cache_root, cwd)
        scheduler_root = resolve_scheduler_root(None, cwd)
        cache_store = ValidationCacheStore(cache_root)
        scheduler_store = ValidationSchedulerStore(scheduler_root)
        cache_enabled = args.cache_policy != CACHE_POLICY_DISABLED
        scheduler_enabled = args.scheduler_policy != "disabled"

        for check in profile.checks:
            scheduler_warnings.extend(
                check_lifecycle_policy(args.validation_phase, args.profile, check.argv)
            )

        normalized_paths, refusal = self._resolve_paths(args, cwd)
        if refusal:
            yield ValidateResult(
                status="refused",
                profile=args.profile,
                error_kind="unsafe_paths",
                refusal_reason=refusal,
            )
            return

        before_git_state = await _collect_git_state(cwd)

        policy_reason = _check_dirty_policy(
            before_git_state, args.expected_dirty_policy, normalized_paths
        )
        if policy_reason:
            yield ValidateResult(
                status="failed",
                profile=args.profile,
                error_kind="dirty_workspace",
                refusal_reason=policy_reason,
                before_git_state=before_git_state,
                blocker_summary={"dirty_workspace": 1},
            )
            return

        checks = self._build_checks(profile, normalized_paths)

        timeout = args.timeout_seconds or profile.default_timeout
        results: list[ValidateCheckResult] = []

        for check in checks:
            check_timeout = min(timeout, 600)

            if normalized_paths:
                scoped_argv, should_run = _scope_check_argv(check, normalized_paths)
                if not should_run:
                    results.append(self._skipped_result(check))
                    continue
                run_argv = scoped_argv
            else:
                run_argv = check.argv

            if (check.allow_mutation and not args.allow_mutation) or (
                check.allow_network and not args.allow_network
            ):
                results.append(self._skipped_result(check))
                continue

            cmd_fp = _compute_fingerprint(run_argv)
            input_fp, file_fps = compute_input_fingerprint(
                cwd, cmd_fp, check.command_kind
            )
            ck = compute_cache_key(
                check.check_id, check.command_kind, cmd_fp, input_fp, cwd, cwd
            )

            if cache_enabled and args.cache_policy != "force_rerun":
                lookup = cache_store.lookup(ck)
                cache_status, _reason = decide_cache_eligibility(
                    args.cache_policy, lookup, args.allow_failed_cache_reuse
                )
                if cache_status == CACHE_STATUS_HIT and lookup.record is not None:
                    results.append(
                        self._build_cached_result(
                            check, cache_status, ck, input_fp, lookup.record
                        )
                    )
                    continue

            if scheduler_enabled and args.lock_running_checks:
                acquired, _blocking_key = scheduler_store.acquire_lock(ck)
                if not acquired:
                    results.append(
                        self._build_blocked_result(
                            check,
                            reason="validation_already_running",
                            cache_key=ck,
                            input_fingerprint=input_fp,
                        )
                    )
                    continue

            modified_argv, parallel_status, parallel_warning = apply_parallel_policy(
                run_argv,
                args.parallel_policy,
                args.max_workers,
                args.xdist_distribution,
            )
            if parallel_warning:
                scheduler_warnings.append(parallel_warning)

            cr = await _run_check(
                modified_argv, output_cap=output_cap, timeout=check_timeout, cwd=cwd
            )
            if normalized_paths:
                cr.affected_paths = list(normalized_paths)

            cr.cache_status = (
                CACHE_STATUS_MISS_RAN if cache_enabled else CACHE_STATUS_DISABLED
            )
            cr.cache_key = ck
            cr.input_fingerprint = input_fp
            cr.scheduler_status = (
                SCHEDULER_RUNNING if scheduler_enabled else SCHEDULER_NOT_SCHEDULED
            )
            cr.parallel_status = parallel_status
            cr.validation_phase = args.validation_phase

            if parallel_status == PARALLEL_ENABLED:
                cr.worker_count = args.max_workers or 4
                cr.distribution = args.xdist_distribution

            results.append(cr)

            if cache_enabled and cr.status in {"passed", "failed"}:
                record = ValidationCacheRecord(
                    cache_key=ck,
                    check_id=check.check_id,
                    command_kind=check.command_kind,
                    command_fingerprint=cmd_fp,
                    input_fingerprint=input_fp,
                    input_file_fingerprints=file_fps,
                    status=cr.status,
                    exit_code=cr.exit_code,
                    duration_ms=cr.duration_ms,
                    stdout_sha256=cr.stdout_sha256,
                    stderr_sha256=cr.stderr_sha256,
                    stdout_bytes=cr.stdout_bytes,
                    stderr_bytes=cr.stderr_bytes,
                    failure_kind=cr.failure_kind,
                    created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    validation_phase=args.validation_phase,
                    worker_count=cr.worker_count,
                    distribution=cr.distribution,
                    warnings=list(scheduler_warnings),
                )
                cr.cache_record_sha256 = record.record_sha256()
                cache_store.store(record)

            if scheduler_enabled:
                scheduler_store.release_lock(ck)

        after_git_state = await _collect_git_state(cwd)
        yield self._build_run_result(
            results,
            profile,
            start,
            before_git_state=before_git_state,
            after_git_state=after_git_state,
        )
