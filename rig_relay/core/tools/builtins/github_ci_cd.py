"""GitHub CI/CD and git operations tool.

Uses the stored GitHub OAuth token (from DevFileTokenStore) to:
  - Trigger workflow dispatches
  - Check workflow run status
  - List repository workflows
  - Authenticate git operations (push, clone)

The token is read from the local store, never exposed in tool arguments.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any, ClassVar

import httpx
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
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolStreamEvent

GITHUB_API_BASE = "https://api.github.com"

# ── Args Models ──────────────────────────────────────────────────────


class GitHubDispatchArgs(BaseModel):
    """Trigger a GitHub Actions workflow dispatch."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    workflow_id: str
    ref: str = "main"
    inputs: dict[str, str] = Field(default_factory=dict)


class GitHubWorkflowStatusArgs(BaseModel):
    """Check the status of a workflow run."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    run_id: int


class GitHubListWorkflowsArgs(BaseModel):
    """List workflows in a repository."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str


class GitHubListRunsArgs(BaseModel):
    """List recent workflow runs."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    workflow_id: str | None = None
    branch: str | None = None
    limit: int = 10


class GitHubCheckPRArgs(BaseModel):
    """Check pull request status."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    pr_number: int


class GitHubToolArgs(BaseModel):
    """Arguments for the GitHub CI/CD tool."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        description="Action to perform: dispatch, workflow_status, list_workflows, "
        "list_runs, check_pr"
    )
    owner: str = ""
    repo: str = ""
    workflow_id: str = ""
    run_id: int = 0
    pr_number: int = 0
    ref: str = "main"
    branch: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
    limit: int = 10


# ── Result Models ────────────────────────────────────────────────────


class GitHubDispatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    workflow_id: str
    run_id: int | None = None
    html_url: str = ""


class GitHubWorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int
    workflow_id: str
    status: str
    conclusion: str | None = None
    html_url: str = ""
    branch: str = ""
    created_at: str = ""
    updated_at: str = ""


class GitHubWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    path: str
    state: str


class GitHubPRInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pr_number: int
    title: str
    state: str
    mergeable: bool | None = None
    mergeable_state: str = ""
    draft: bool = False
    html_url: str = ""
    head_branch: str = ""
    base_branch: str = ""
    checks_status: str = "unknown"


class GitHubToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    status: str
    summary: str
    error_kind: str | None = None
    dispatch_result: GitHubDispatchResult | None = None
    workflow_run: GitHubWorkflowRun | None = None
    workflows: list[GitHubWorkflow] = Field(default_factory=list)
    runs: list[GitHubWorkflowRun] = Field(default_factory=list)
    pr_info: GitHubPRInfo | None = None
    warnings: list[str] = Field(default_factory=list)


# ── Error Vocabulary ───────────────────────────────────────────────────

_GITHUB_ERROR_KINDS: dict[str, str] = {
    "token_unavailable": "github.token_unavailable",
    "token_expired": "github.token_expired",
    "api_error": "github.api_error",
    "not_found": "github.not_found",
    "permission_denied": "github.permission_denied",
    "rate_limited": "github.rate_limited",
    "unknown_action": "github.unknown_action",
    "network_error": "github.network_error",
    "timeout": "github.timeout",
}


# ── Token Helper ─────────────────────────────────────────────────────


def _get_github_token() -> str:
    """Read the GitHub OAuth token from the local token store.

    Returns:
        The access token.

    Raises:
        ToolError: If no token is available.
    """
    from rig_relay.identity.models import IdentityProviderKind
    from rig_relay.identity.token_store import (
        DevFileTokenStore,
        enable_dev_file_token_store,
    )

    # explicitly opt in to dev-only plaintext token storage
    enable_dev_file_token_store()
    store = DevFileTokenStore()
    metadata = store.get(IdentityProviderKind.GITHUB)
    if metadata is None:
        raise ToolError(
            "Not signed in to GitHub. Run sign_in_github_start + sign_in_github_exchange first."
        )
    if metadata.status.value != "signed_in":
        raise ToolError(
            f"GitHub sign-in status is '{metadata.status.value}', expected 'signed_in'."
        )

    # Read token from dev store file
    token_path = store._path(IdentityProviderKind.GITHUB)
    if not token_path.is_file():
        raise ToolError("GitHub token file not found.")

    data = json.loads(token_path.read_text(encoding="utf-8"))
    token_bundle = data.get("token_bundle", {})
    access_token = token_bundle.get("access_token", "")
    if not access_token:
        raise ToolError("GitHub access token not found in store.")

    return access_token


# ── API Helpers (sync, run in executor) ──────────────────────────────


def _api_get(path: str, token: str, params: dict | None = None) -> dict[str, Any]:
    import httpx

    resp = httpx.get(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        params=params,
        timeout=15.0,
    )
    resp.raise_for_status()
    return dict(resp.json())


def _api_post(
    path: str, token: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    import httpx

    resp = httpx.post(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
        json=body,
        timeout=15.0,
    )
    if resp.status_code == 204:
        return {"status": "accepted"}
    resp.raise_for_status()
    return dict(resp.json())


def _execute_dispatch(args: GitHubDispatchArgs, token: str) -> GitHubDispatchResult:
    path = f"/repos/{args.owner}/{args.repo}/actions/workflows/{args.workflow_id}/dispatches"
    body: dict[str, Any] = {"ref": args.ref}
    if args.inputs:
        body["inputs"] = args.inputs
    _api_post(path, token, body)
    return GitHubDispatchResult(
        status="dispatched",
        workflow_id=args.workflow_id,
        html_url=f"https://github.com/{args.owner}/{args.repo}/actions/workflows/{args.workflow_id}",
    )


def _execute_workflow_status(
    args: GitHubWorkflowStatusArgs, token: str
) -> GitHubWorkflowRun:
    data = _api_get(
        f"/repos/{args.owner}/{args.repo}/actions/runs/{args.run_id}", token
    )
    return GitHubWorkflowRun(
        run_id=data.get("id", args.run_id),
        workflow_id=str(data.get("workflow_id", "")),
        status=data.get("status", "unknown"),
        conclusion=data.get("conclusion"),
        html_url=data.get("html_url", ""),
        branch=data.get("head_branch", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def _execute_list_workflows(
    args: GitHubListWorkflowsArgs, token: str
) -> list[GitHubWorkflow]:
    data = _api_get(f"/repos/{args.owner}/{args.repo}/actions/workflows", token)
    return [
        GitHubWorkflow(
            id=wf.get("id", 0),
            name=wf.get("name", ""),
            path=wf.get("path", ""),
            state=wf.get("state", ""),
        )
        for wf in data.get("workflows", [])
    ]


def _execute_list_runs(args: GitHubListRunsArgs, token: str) -> list[GitHubWorkflowRun]:
    params: dict[str, Any] = {"per_page": min(args.limit, 50)}
    if args.workflow_id:
        path = (
            f"/repos/{args.owner}/{args.repo}/actions/workflows/{args.workflow_id}/runs"
        )
    else:
        path = f"/repos/{args.owner}/{args.repo}/actions/runs"
    if args.branch:
        params["branch"] = args.branch

    data = _api_get(path, token, params=params)
    return [
        GitHubWorkflowRun(
            run_id=run.get("id", 0),
            workflow_id=str(run.get("workflow_id", "")),
            status=run.get("status", "unknown"),
            conclusion=run.get("conclusion"),
            html_url=run.get("html_url", ""),
            branch=run.get("head_branch", ""),
            created_at=run.get("created_at", ""),
            updated_at=run.get("updated_at", ""),
        )
        for run in data.get("workflow_runs", [])
    ]


def _execute_check_pr(args: GitHubCheckPRArgs, token: str) -> GitHubPRInfo:
    pr_data = _api_get(f"/repos/{args.owner}/{args.repo}/pulls/{args.pr_number}", token)
    # Fetch latest commit status
    head_sha = pr_data.get("head", {}).get("sha", "")
    check_status = "unknown"
    if head_sha:
        try:
            combined = _api_get(
                f"/repos/{args.owner}/{args.repo}/commits/{head_sha}/status", token
            )
            check_status = combined.get("state", "unknown")
        except Exception:
            pass

    return GitHubPRInfo(
        pr_number=args.pr_number,
        title=pr_data.get("title", ""),
        state=pr_data.get("state", ""),
        mergeable=pr_data.get("mergeable"),
        mergeable_state=pr_data.get("mergeable_state", ""),
        draft=pr_data.get("draft", False),
        html_url=pr_data.get("html_url", ""),
        head_branch=pr_data.get("head", {}).get("ref", ""),
        base_branch=pr_data.get("base", {}).get("ref", ""),
        checks_status=check_status,
    )


# ── Tool Class ───────────────────────────────────────────────────────


class GitHubToolConfig(BaseToolConfig):
    pass


class GitHubTool(
    BaseTool[GitHubToolArgs, GitHubToolResult, GitHubToolConfig, BaseToolState],
    ToolUIData[GitHubToolArgs, GitHubToolResult],
):
    description: ClassVar[str] = (
        "Interact with GitHub CI/CD: trigger workflow dispatches, "
        "check workflow run status, list workflows, list recent runs, "
        "and check pull request status. Requires prior GitHub OAuth sign-in."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.EXTERNAL_SIDE_EFFECT

    @classmethod
    def format_call_display(cls, args: GitHubToolArgs) -> ToolCallDisplay:
        action_descriptions = {
            "dispatch": f"Dispatch workflow {args.workflow_id} on {args.owner}/{args.repo}",
            "workflow_status": f"Check run #{args.run_id} on {args.owner}/{args.repo}",
            "list_workflows": f"List workflows on {args.owner}/{args.repo}",
            "list_runs": f"List recent runs on {args.owner}/{args.repo}",
            "check_pr": f"Check PR #{args.pr_number} on {args.owner}/{args.repo}",
        }
        return ToolCallDisplay(
            summary=action_descriptions.get(args.action, f"GitHub: {args.action}")
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Interacting with GitHub CI/CD"

    @classmethod
    def format_result_display(cls, result: GitHubToolResult) -> ToolResultDisplay:
        return ToolResultDisplay(
            success=result.status == "ok",
            message=result.summary,
            warnings=list(result.warnings),
        )

    async def run(
        self, args: GitHubToolArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitHubToolResult, None]:
        loop = None
        import asyncio

        loop = asyncio.get_running_loop()

        try:
            token = await loop.run_in_executor(None, _get_github_token)
        except ToolError:
            yield GitHubToolResult(
                action=args.action,
                status="refused",
                summary="GitHub authentication required — sign in first",
                error_kind=_GITHUB_ERROR_KINDS["token_unavailable"],
                warnings=[
                    "GitHub sign-in required. Use sign_in_github_start + sign_in_github_exchange."
                ],
            )
            return

        warnings: list[str] = []

        try:
            match args.action:
                case "dispatch":
                    da = GitHubDispatchArgs(
                        owner=args.owner,
                        repo=args.repo,
                        workflow_id=args.workflow_id,
                        ref=args.ref,
                        inputs=args.inputs,
                    )
                    dr = await loop.run_in_executor(None, _execute_dispatch, da, token)
                    yield GitHubToolResult(
                        action=args.action,
                        status="ok",
                        summary=f"Dispatched workflow {args.workflow_id} on {args.owner}/{args.repo} @ {args.ref}",
                        dispatch_result=dr,
                    )

                case "workflow_status":
                    wa = GitHubWorkflowStatusArgs(
                        owner=args.owner, repo=args.repo, run_id=args.run_id
                    )
                    run = await loop.run_in_executor(
                        None, _execute_workflow_status, wa, token
                    )
                    yield GitHubToolResult(
                        action=args.action,
                        status="ok",
                        summary=(
                            f"Run #{run.run_id}: {run.status}"
                            f"{f' ({run.conclusion})' if run.conclusion else ''}"
                        ),
                        workflow_run=run,
                    )

                case "list_workflows":
                    la = GitHubListWorkflowsArgs(owner=args.owner, repo=args.repo)
                    workflows = await loop.run_in_executor(
                        None, _execute_list_workflows, la, token
                    )
                    yield GitHubToolResult(
                        action=args.action,
                        status="ok",
                        summary=f"{len(workflows)} workflows in {args.owner}/{args.repo}",
                        workflows=workflows,
                    )

                case "list_runs":
                    ra = GitHubListRunsArgs(
                        owner=args.owner,
                        repo=args.repo,
                        workflow_id=args.workflow_id or None,
                        branch=args.branch,
                        limit=args.limit,
                    )
                    runs = await loop.run_in_executor(
                        None, _execute_list_runs, ra, token
                    )
                    yield GitHubToolResult(
                        action=args.action,
                        status="ok",
                        summary=f"{len(runs)} recent runs in {args.owner}/{args.repo}",
                        runs=runs,
                    )

                case "check_pr":
                    pa = GitHubCheckPRArgs(
                        owner=args.owner, repo=args.repo, pr_number=args.pr_number
                    )
                    pr_info = await loop.run_in_executor(
                        None, _execute_check_pr, pa, token
                    )
                    yield GitHubToolResult(
                        action=args.action,
                        status="ok",
                        summary=(
                            f"PR #{pr_info.pr_number}: {pr_info.title} "
                            f"({pr_info.state}, checks: {pr_info.checks_status})"
                        ),
                        pr_info=pr_info,
                    )

                case _:
                    yield GitHubToolResult(
                        action=args.action,
                        status="error",
                        summary=f"Unknown action: {args.action}",
                        error_kind=_GITHUB_ERROR_KINDS["unknown_action"],
                        warnings=[
                            "Valid actions: dispatch, workflow_status, list_workflows, list_runs, check_pr"
                        ],
                    )

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 404:
                ek = _GITHUB_ERROR_KINDS["not_found"]
            elif status_code in {401, 403}:
                ek = _GITHUB_ERROR_KINDS["permission_denied"]
            elif status_code == 429:
                ek = _GITHUB_ERROR_KINDS["rate_limited"]
            else:
                ek = _GITHUB_ERROR_KINDS["api_error"]
            yield GitHubToolResult(
                action=args.action,
                status="error",
                summary=f"GitHub API error (HTTP {status_code})",
                error_kind=ek,
                warnings=warnings,
            )
        except TimeoutError:
            yield GitHubToolResult(
                action=args.action,
                status="error",
                summary="GitHub API request timed out",
                error_kind=_GITHUB_ERROR_KINDS["timeout"],
                warnings=warnings,
            )
        except Exception:
            yield GitHubToolResult(
                action=args.action,
                status="error",
                summary="GitHub API request failed",
                error_kind=_GITHUB_ERROR_KINDS["network_error"],
                warnings=warnings,
            )


__all__ = ["GitHubTool", "GitHubToolArgs", "GitHubToolResult"]
