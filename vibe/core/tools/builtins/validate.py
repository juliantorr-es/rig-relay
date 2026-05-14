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

from vibe.core.tools.base import BaseTool, BaseToolState, InvokeContext

# Git state
from vibe.core.tools.builtins.validate_git import (
    _check_dirty_policy,
    _collect_git_state,
    _parse_git_status_branch,
    _parse_git_status_porcelain,
    _parse_git_status_porcelain_line,
)

# ── Re-exports from submodules ────────────────────────────────────────
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


# ── Tool implementation ────────────────────────────────────────────────


class Validate(
    BaseTool[ValidateArgs, ValidateResult, ValidateToolConfig, BaseToolState],
    ToolUIData[ValidateArgs, ValidateResult],
):
    description: ClassVar[str] = (
        "Run a read-only validation profile (quick, python, schemas, "
        "receipt-policy, tool-hardening). Returns structured results "
        "with blocker taxonomy."
    )

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
        """Build a content-light receipt from a validate result.

        The receipt contains no raw stdout/stderr — only hashes, byte counts,
        timing, statuses, and blocker summary.
        """
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
        """Resolve and normalize paths, returning refusal reason if unsafe."""
        if not args.paths:
            return [], None
        return _normalize_validate_paths(args.paths, cwd)

    @staticmethod
    def _build_checks(
        profile: Profile, normalized_paths: list[str]
    ) -> list[ProfileCheck]:
        """Build check list with optional dynamic checks for path scoping."""
        checks = list(profile.checks)
        if normalized_paths and profile.name == "quick":
            # Only add scoped ruff if at least one path is Python-relevant
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
        """Create a skipped ValidateCheckResult for a check."""
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
    def _build_run_result(
        results: list[ValidateCheckResult],
        profile: Profile,
        start: float,
        before_git_state: ValidateGitState | None = None,
        after_git_state: ValidateGitState | None = None,
    ) -> ValidateResult:
        """Build overall ValidateResult from check results."""
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

        # ── Resolve profile ──
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

        # ── Check mutation policy ──
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

        # ── Check network policy ──
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

        # ── Compute output cap ──
        output_cap = args.output_cap_bytes or self.config.default_output_cap
        output_cap = min(output_cap, MAX_CAP_BYTES)

        # ── Resolve cwd ──
        cwd = args.workspace_root
        if cwd is None and ctx and ctx.session_dir:
            cwd = str(ctx.session_dir.parent.parent.resolve())
        if cwd is None:
            cwd = os.getcwd()

        # ── Collect git state ──
        before_git_state = await _collect_git_state(cwd)

        # ── Enforce dirty policy ──
        if args.expected_dirty_policy == "clean" and before_git_state.dirty_count > 0:
            yield ValidateResult(
                status="failed",
                profile=args.profile,
                error_kind="dirty_workspace",
                refusal_reason=(
                    f"expected_dirty_policy='clean' but workspace has "
                    f"{before_git_state.dirty_count} dirty files"
                ),
                before_git_state=before_git_state,
                blocker_summary={"dirty_workspace": 1},
            )
            return

        if (
            args.expected_dirty_policy == "allow_listed_dirty"
            and before_git_state.dirty_count > 0
        ):
            allowed = set(args.paths)
            unlisted = [p for p in before_git_state.dirty_paths if p not in allowed]
            if unlisted:
                yield ValidateResult(
                    status="failed",
                    profile=args.profile,
                    error_kind="dirty_workspace",
                    refusal_reason=(
                        f"expected_dirty_policy='allow_listed_dirty' but "
                        f"{len(unlisted)} dirty paths not in allowed list"
                    ),
                    before_git_state=before_git_state,
                    blocker_summary={"dirty_workspace": 1},
                )
                return

        # ── Resolve path scopes ──
        normalized_paths, refusal = self._resolve_paths(args, cwd)
        if refusal:
            yield ValidateResult(
                status="refused",
                profile=args.profile,
                error_kind="unsafe_paths",
                refusal_reason=refusal,
            )
            return

        # ── Build check list ──
        checks = self._build_checks(profile, normalized_paths)

        # ── Run checks ──
        timeout = args.timeout_seconds or profile.default_timeout
        results: list[ValidateCheckResult] = []

        for check in checks:
            check_timeout = min(timeout, 600)

            # Scope argv when paths are provided
            if normalized_paths:
                scoped_argv, should_run = _scope_check_argv(check, normalized_paths)
                if not should_run:
                    results.append(self._skipped_result(check))
                    continue
                run_argv = scoped_argv
            else:
                run_argv = check.argv

            # Skip mutation/network checks if not allowed
            if (check.allow_mutation and not args.allow_mutation) or (
                check.allow_network and not args.allow_network
            ):
                results.append(self._skipped_result(check))
                continue

            cr = await _run_check(
                run_argv, output_cap=output_cap, timeout=check_timeout, cwd=cwd
            )
            if normalized_paths:
                cr.affected_paths = list(normalized_paths)
            results.append(cr)

        # ── Build result ──
        after_git_state = await _collect_git_state(cwd)
        yield self._build_run_result(
            results,
            profile,
            start,
            before_git_state=before_git_state,
            after_git_state=after_git_state,
        )
