"""GitHub Truth Tool — read-only built-in for GitHub Repository Truth observation.

Exposes the GitHubTruthAdapter as a governed read-only built-in tool.
Operations: verify_publication, observe_ci_status, observe_ref,
check_commit_presence, observe_installation_access, observe_repository.

Uses GitHub App installation tokens (never exposed in results).
Content-light by default: no raw paths, logs, token material, or private metadata.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from rig_relay.integrations.github_provider._truth_adapter import GitHubTruthAdapter

# ── Args ───────────────────────────────────────────────────────────────


class GitHubTruthArgs(BaseModel):
    """Arguments for the GitHub truth observation tool."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        description=(
            "Action: verify_publication, observe_ci_status, observe_ref, "
            "check_commit_presence, observe_installation_access, observe_repository"
        )
    )
    owner: str = ""
    repo: str = ""
    expected_sha: str = ""
    ref: str = "main"
    sha: str = ""


# ── Result Models ──────────────────────────────────────────────────────


class GitHubTruthActionResult(BaseModel):
    """Bounded result from a GitHub truth observation operation."""

    model_config = ConfigDict(extra="forbid")

    action: str
    status: str  # ok, refused, error, unavailable
    summary: str = ""
    evidence_digest: str | None = None
    verification_status: str | None = None
    remote_head_sha: str | None = None
    accepted_head_present: bool | None = None
    follow_on_commits_count: int | None = None
    ci_state: str | None = None
    overall_state: str | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    pending_count: int | None = None
    suggested_next_action: str | None = None
    error_kind: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ── Tool ───────────────────────────────────────────────────────────────


class GitHubTruthConfig(BaseToolConfig):
    permission: ToolPermission = BaseToolConfig.model_fields["permission"].default


class GitHubTruthTool(
    BaseTool[
        GitHubTruthArgs, GitHubTruthActionResult, GitHubTruthConfig, BaseToolState
    ],
    ToolUIData[GitHubTruthArgs, GitHubTruthActionResult],
):
    description: ClassVar[str] = (
        "Read-only GitHub repository truth observations: verify publication, "
        "check CI status, observe remote refs and commits. "
        "Requires GitHub App installation authentication. "
        "Content-light — no raw paths, logs, tokens, or private metadata."
    )

    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    @classmethod
    def format_call_display(cls, args: GitHubTruthArgs) -> ToolCallDisplay:
        summaries = {
            "verify_publication": f"Verify publication of {args.expected_sha[:8] if args.expected_sha else '?'} on {args.owner}/{args.repo}",
            "observe_ci_status": f"Check CI status for {args.sha[:8] if args.sha else '?'} on {args.owner}/{args.repo}",
            "observe_ref": f"Observe ref {args.ref} on {args.owner}/{args.repo}",
            "check_commit_presence": f"Check commit {args.sha[:8] if args.sha else '?'} on {args.owner}/{args.repo}",
            "observe_installation_access": "Check GitHub App installation status",
            "observe_repository": f"Observe repository {args.owner}/{args.repo}",
        }
        return ToolCallDisplay(
            summary=summaries.get(args.action, f"GitHub truth: {args.action}")
        )

    @classmethod
    def format_result_display(
        cls, result: GitHubTruthActionResult
    ) -> ToolResultDisplay:
        return ToolResultDisplay(
            success=result.status == "ok",
            message=result.summary,
            warnings=list(result.warnings),
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Observing GitHub repository truth"

    async def run(
        self, args: GitHubTruthArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitHubTruthActionResult, None]:
        """Execute the requested truth observation operation."""
        adapter = self._build_adapter()

        if adapter is None:
            yield self._unavailable("No GitHub App installation configured")
            return

        try:
            match args.action:
                case "verify_publication":
                    result = await self._verify_publication(adapter, args)
                case "observe_ci_status":
                    result = await self._observe_ci(adapter, args)
                case "observe_ref":
                    result = await self._observe_ref(adapter, args)
                case "check_commit_presence":
                    result = await self._commit_presence(adapter, args)
                case "observe_installation_access":
                    result = await self._installation_access(adapter, args)
                case "observe_repository":
                    result = await self._observe_repo(adapter, args)
                case _:
                    result = GitHubTruthActionResult(
                        action=args.action,
                        status="error",
                        summary=f"Unknown action: {args.action}",
                        warnings=[
                            "Valid: verify_publication, observe_ci_status, "
                            "observe_ref, check_commit_presence, "
                            "observe_installation_access, observe_repository"
                        ],
                    )
            yield result
        except ToolError:
            raise
        except Exception as e:
            yield GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=f"GitHub truth operation failed: {e}",
                error_kind="github.unknown_error",
            )

    # ── Handlers (async, return scalar results) ────────────────────────

    async def _verify_publication(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        from rig_relay.integrations.github_provider._truth_adapter import (
            GitHubTruthAdapterError,
        )

        if not args.owner or not args.repo or not args.expected_sha:
            return GitHubTruthActionResult(
                action=args.action,
                status="refused",
                summary="owner, repo, and expected_sha are required for verify_publication",
                error_kind="github.missing_required_args",
            )

        try:
            result = await adapter.verify_publication(
                args.owner, args.repo, args.expected_sha, args.ref
            )
            return GitHubTruthActionResult(
                action=args.action,
                status="ok",
                summary=f"Publication: {result.verification_status}",
                evidence_digest=result._evidence_digest(),
                verification_status=result.verification_status,
                remote_head_sha=result.remote_head_sha,
                accepted_head_present=result.accepted_head_present,
                follow_on_commits_count=result.follow_on_commits_count,
                ci_state=result.ci_state,
                suggested_next_action=result.suggested_next_action,
                error_kind=result.error_kind,
            )
        except GitHubTruthAdapterError as e:
            return GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=str(e),
                error_kind=e.error_kind,
            )

    async def _observe_ci(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        from rig_relay.integrations.github_provider._truth_adapter import (
            GitHubTruthAdapterError,
        )

        if not args.owner or not args.repo or not args.sha:
            return GitHubTruthActionResult(
                action=args.action,
                status="refused",
                summary="owner, repo, and sha are required for observe_ci_status",
                error_kind="github.missing_required_args",
            )

        try:
            result = await adapter.observe_ci_status(args.owner, args.repo, args.sha)
            return GitHubTruthActionResult(
                action=args.action,
                status="ok",
                summary=(
                    f"CI: {result.overall_state} "
                    f"(passed={result.passed_count}, failed={result.failed_count}, "
                    f"pending={result.pending_count})"
                ),
                evidence_digest=result._evidence_digest(),
                overall_state=result.overall_state,
                passed_count=result.passed_count,
                failed_count=result.failed_count,
                pending_count=result.pending_count,
                suggested_next_action=result.suggested_next_action,
                error_kind=result.error_kind,
            )
        except GitHubTruthAdapterError as e:
            return GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=str(e),
                error_kind=e.error_kind,
            )

    async def _observe_ref(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        from rig_relay.integrations.github_provider._truth_adapter import (
            GitHubTruthAdapterError,
        )

        if not args.owner or not args.repo:
            return GitHubTruthActionResult(
                action=args.action,
                status="refused",
                summary="owner and repo are required for observe_ref",
                error_kind="github.missing_required_args",
            )

        try:
            result = await adapter.observe_ref(args.owner, args.repo, args.ref)
            return GitHubTruthActionResult(
                action=args.action,
                status="ok",
                summary=f"Ref {args.ref}: {'resolved' if result.resolved else 'not found'}",
                evidence_digest=result._evidence_digest(),
                remote_head_sha=result.remote_head_sha,
                error_kind=result.error_kind,
            )
        except GitHubTruthAdapterError as e:
            return GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=str(e),
                error_kind=e.error_kind,
            )

    async def _commit_presence(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        from rig_relay.integrations.github_provider._truth_adapter import (
            GitHubTruthAdapterError,
        )

        if not args.owner or not args.repo or not args.sha:
            return GitHubTruthActionResult(
                action=args.action,
                status="refused",
                summary="owner, repo, and sha are required for check_commit_presence",
                error_kind="github.missing_required_args",
            )

        try:
            result = await adapter.check_commit_presence(
                args.owner, args.repo, args.sha, args.ref
            )
            return GitHubTruthActionResult(
                action=args.action,
                status="ok",
                summary=(
                    f"Commit {args.sha[:8]}: {'present' if result.present else 'absent'} "
                    f"({result.relationship})"
                ),
                evidence_digest=result._evidence_digest(),
                remote_head_sha=result.remote_head_sha,
                error_kind=result.error_kind,
            )
        except GitHubTruthAdapterError as e:
            return GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=str(e),
                error_kind=e.error_kind,
            )

    async def _installation_access(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        result = adapter.observe_installation_access()
        return GitHubTruthActionResult(
            action=args.action,
            status="ok" if result.token_status == "available" else "unavailable",
            summary=f"GitHub App: {result.token_status}",
            evidence_digest=result._evidence_digest(),
            error_kind=result.error_kind,
        )

    async def _observe_repo(
        self, adapter: GitHubTruthAdapter, args: GitHubTruthArgs
    ) -> GitHubTruthActionResult:
        from rig_relay.integrations.github_provider._truth_adapter import (
            GitHubTruthAdapterError,
        )

        if not args.owner or not args.repo:
            return GitHubTruthActionResult(
                action=args.action,
                status="refused",
                summary="owner and repo are required for observe_repository",
                error_kind="github.missing_required_args",
            )

        try:
            result = await adapter.observe_repository(args.owner, args.repo)
            return GitHubTruthActionResult(
                action=args.action,
                status="ok",
                summary=f"Repository {args.owner}/{args.repo}: {result.visibility or 'unknown'}",
                evidence_digest=result._evidence_digest(),
            )
        except GitHubTruthAdapterError as e:
            return GitHubTruthActionResult(
                action=args.action,
                status="error",
                summary=str(e),
                error_kind=e.error_kind,
            )

    # ── Adapter Factory (testable) ─────────────────────────────────────

    @staticmethod
    def _build_adapter() -> GitHubTruthAdapter | None:
        """Build a truth adapter from available configuration."""
        try:
            from rig_relay.integrations.github_provider._truth_adapter import (
                create_truth_adapter,
            )

            return create_truth_adapter()
        except Exception:
            return None

    def _unavailable(self, reason: str) -> GitHubTruthActionResult:
        return GitHubTruthActionResult(
            action="",
            status="unavailable",
            summary=reason,
            error_kind="github.installation_missing",
        )


__all__ = ["GitHubTruthActionResult", "GitHubTruthArgs", "GitHubTruthTool"]
