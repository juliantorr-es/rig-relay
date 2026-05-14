from __future__ import annotations

from collections.abc import Callable, Coroutine
import time
from typing import Any

from rig_relay.evidence.validation_cache import (
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
    SCHEDULER_NOT_SCHEDULED,
    SCHEDULER_RUNNING,
    ValidationSchedulerStore,
    apply_parallel_policy,
)
from rig_relay.core.tools.builtins.validate_models import (
    ProfileCheck,
    ValidateArgs,
    ValidateCheckResult,
)
from rig_relay.core.tools.builtins.validate_paths import _scope_check_argv
from rig_relay.core.tools.builtins.validate_runner import _compute_fingerprint, _run_check


def run_validate_check(
    *,
    check: ProfileCheck,
    args: ValidateArgs,
    cwd: str,
    timeout: int,
    normalized_paths: list[str],
    cache_enabled: bool,
    scheduler_enabled: bool,
    cache_store: ValidationCacheStore,
    scheduler_store: ValidationSchedulerStore,
    scheduler_warnings: list[str],
    output_cap: int,
) -> tuple[ValidateCheckResult | None, Callable[[], Coroutine[Any, Any, ValidateCheckResult]] | None]:
    check_timeout = min(timeout, 600)
    run_argv = check.argv
    if normalized_paths:
        scoped_argv, should_run = _scope_check_argv(check, normalized_paths)
        if not should_run:
            return None, None
        run_argv = scoped_argv
    if (check.allow_mutation and not args.allow_mutation) or (
        check.allow_network and not args.allow_network
    ):
        return None, None

    cmd_fp = _compute_fingerprint(run_argv)
    input_fp, file_fps = compute_input_fingerprint(cwd, cmd_fp, check.command_kind)
    ck = compute_cache_key(check.check_id, check.command_kind, cmd_fp, input_fp, cwd, cwd)

    if cache_enabled and args.cache_policy != "force_rerun":
        lookup = cache_store.lookup(ck)
        cache_status, _reason = decide_cache_eligibility(
            args.cache_policy, lookup, args.allow_failed_cache_reuse
        )
        if cache_status == CACHE_STATUS_HIT and lookup.record is not None:
            return (
                ValidateCheckResult(
                    check_id=check.check_id,
                    command_kind=check.command_kind,
                    cache_key=ck,
                    cache_status=cache_status,
                    input_fingerprint=input_fp,
                    status=lookup.record.status,
                    exit_code=lookup.record.exit_code,
                    duration_ms=lookup.record.duration_ms,
                ),
                None,
            )

    if scheduler_enabled and args.lock_running_checks:
        acquired, _blocking_key = scheduler_store.acquire_lock(ck)
        if not acquired:
            return (
                ValidateCheckResult(
                    check_id=check.check_id,
                    command_kind=check.command_kind,
                    cache_key=ck,
                    cache_status=CACHE_STATUS_DISABLED,
                    scheduler_status="blocked_duplicate",
                    input_fingerprint=input_fp,
                    status="blocked",
                ),
                None,
            )

    modified_argv, parallel_status, parallel_warning = apply_parallel_policy(
        run_argv, args.parallel_policy, args.max_workers, args.xdist_distribution
    )
    if parallel_warning:
        scheduler_warnings.append(parallel_warning)

    async def _run() -> ValidateCheckResult:
        cr = await _run_check(
            modified_argv, output_cap=output_cap, timeout=check_timeout, cwd=cwd
        )
        if normalized_paths:
            cr.affected_paths = list(normalized_paths)
        cr.cache_status = CACHE_STATUS_MISS_RAN if cache_enabled else CACHE_STATUS_DISABLED
        cr.cache_key = ck
        cr.input_fingerprint = input_fp
        cr.scheduler_status = SCHEDULER_RUNNING if scheduler_enabled else SCHEDULER_NOT_SCHEDULED
        cr.parallel_status = parallel_status
        cr.validation_phase = args.validation_phase
        if parallel_status == PARALLEL_ENABLED:
            cr.worker_count = args.max_workers or 4
            cr.distribution = args.xdist_distribution
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
        return cr

    return None, _run
