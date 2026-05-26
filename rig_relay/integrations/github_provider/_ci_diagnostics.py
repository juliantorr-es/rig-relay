"""GitHub Issue Intake and CI/CD Diagnostic Adapter — read-only, bounded.

Uses installation tokens for repository-scoped read operations.
Content-light: no raw issue bodies, no raw workflow logs by default.
Log ingestion is withheld until Lane A disclosure authorization.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from rig_relay.integrations.github_provider._issue_intake import (
    GitHubCIDiagnosticEvidence,
    GitHubDiagnosticErrorKind,
    GitHubIssueEvidence,
    GitHubIssueListResult,
    GitHubWorkflowJobEvidence,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    hash_identifier,
    scan_for_tokens,
)

GITHUB_API_BASE = "https://api.github.com"


class GitHubDiagnosticAdapterError(Exception):
    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


class GitHubDiagnosticAdapter:
    """Read-only diagnostic adapter for issues and CI/CD."""

    def __init__(self, token_getter: Any = None) -> None:
        self._token_getter = token_getter

    def _get_token(self) -> str:
        if self._token_getter is None:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.PERMISSION_MISSING,
                "No installation token manager configured",
            )
        token = self._token_getter.get_token()
        if token is None:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.PERMISSION_MISSING,
                "Installation token unavailable or expired",
            )
        return token

    # ── Issue Intake ───────────────────────────────────────────────────

    async def list_issues(
        self, owner: str, repo: str, state: str = "open", per_page: int = 30
    ) -> GitHubIssueListResult:
        repo_hash = hash_identifier(f"{owner}/{repo}")
        try:
            token = self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    params={"state": state, "per_page": min(per_page, 100)},
                )
                response.raise_for_status()
                data = response.json()

            assert_no_raw_github_token(json.dumps(data, sort_keys=True))

            issues = []
            for item in data:
                if "pull_request" in item:
                    continue  # Skip PRs (GitHub returns them in /issues)
                body = item.get("body", "")
                body_hash = None
                body_available = False
                if isinstance(body, str) and body.strip():
                    body_available = True
                    body_hash = f"sha256:{hash_identifier(body)}"

                issues.append(
                    GitHubIssueEvidence(
                        issue_number=item.get("number", 0),
                        title=item.get("title", ""),
                        state=item.get("state", "open"),
                        labels=[
                            lbl.get("name", "")
                            for lbl in item.get("labels", [])
                            if isinstance(lbl, dict)
                        ],
                        assignee_hash=(
                            f"sha256:{hash_identifier(item['assignee']['login'])}"
                            if item.get("assignee") and item["assignee"].get("login")
                            else None
                        ),
                        milestone_title=(
                            item["milestone"]["title"]
                            if item.get("milestone")
                            else None
                        ),
                        created_at=item.get("created_at"),
                        updated_at=item.get("updated_at"),
                        comments_count=item.get("comments", 0),
                        body_hash=body_hash,
                        body_available=body_available,
                        locked=item.get("locked", False),
                        url_hash=(
                            f"sha256:{hash_identifier(item['html_url'])}"
                            if item.get("html_url")
                            else None
                        ),
                    )
                )

            return GitHubIssueListResult(
                repository_hash=repo_hash,
                issues=issues,
                total_count=len(issues),
                returned_count=len(issues),
                truncated=len(issues) >= per_page,
            )
        except GitHubDiagnosticAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.ISSUE_LIST_FAILED,
                f"GitHub API error {e.response.status_code}",
            ) from e
        except Exception as e:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.ISSUE_LIST_FAILED, str(e)
            ) from e

    # ── CI/CD Diagnostics ──────────────────────────────────────────────

    async def list_workflow_runs(
        self, owner: str, repo: str, branch: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        try:
            token = self._get_token()
            params: dict[str, Any] = {"per_page": min(limit, 50)}
            if branch:
                params["branch"] = branch

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

            runs = []
            for run in data.get("workflow_runs", [])[:limit]:
                runs.append({
                    "run_id": run.get("id"),
                    "name": run.get("name", ""),
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "head_branch": run.get("head_branch", ""),
                    "head_sha": run.get("head_sha", ""),
                    "created_at": run.get("created_at"),
                })
            return runs
        except GitHubDiagnosticAdapterError:
            raise
        except Exception as e:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.CI_LIST_RUNS_FAILED, str(e)
            ) from e

    async def list_workflow_jobs(
        self, owner: str, repo: str, run_id: int
    ) -> list[GitHubWorkflowJobEvidence]:
        try:
            token = self._get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                response.raise_for_status()
                data = response.json()

            jobs = []
            for job in data.get("jobs", []):
                steps = job.get("steps", [])
                failed_steps: list[str] = []
                for s in steps:
                    if s.get("conclusion") in {"failure", "timed_out", "cancelled"}:
                        name = s.get("name", "")
                        # Sanitize: scan for tokens in step names
                        if scan_for_tokens(name):
                            name = f"sha256:{hash_identifier(name)}"
                        failed_steps.append(name)

                jobs.append(
                    GitHubWorkflowJobEvidence(
                        job_id=job.get("id", 0),
                        run_id=job.get("run_id", 0),
                        name=job.get("name", ""),
                        status=job.get("status", ""),
                        conclusion=job.get("conclusion"),
                        started_at=job.get("started_at"),
                        completed_at=job.get("completed_at"),
                        steps_count=len(steps),
                        failed_steps_count=len(failed_steps),
                        failed_step_names=failed_steps[:10],  # cap at 10
                        logs_url_hash=(
                            f"sha256:{hash_identifier(job['html_url'])}"
                            if job.get("html_url")
                            else None
                        ),
                        logs_available=False,
                        logs_withheld=True,
                    )
                )
            return jobs
        except GitHubDiagnosticAdapterError:
            raise
        except Exception as e:
            raise GitHubDiagnosticAdapterError(
                GitHubDiagnosticErrorKind.CI_LIST_JOBS_FAILED, str(e)
            ) from e

    async def get_cicd_diagnostics(
        self, owner: str, repo: str, branch: str | None = None, limit: int = 20
    ) -> GitHubCIDiagnosticEvidence:
        repo_hash = hash_identifier(f"{owner}/{repo}")
        try:
            runs = await self.list_workflow_runs(owner, repo, branch, limit)
        except GitHubDiagnosticAdapterError:
            return GitHubCIDiagnosticEvidence(
                repository_hash=repo_hash,
                error_kind=GitHubDiagnosticErrorKind.CI_LIST_RUNS_FAILED,
                suggested_next_action="Check installation token and repository access",
            )

        success = sum(1 for r in runs if r.get("conclusion") == "success")
        failure = sum(
            1 for r in runs if r.get("conclusion") in {"failure", "timed_out"}
        )
        pending = sum(1 for r in runs if r.get("status") not in {"completed"})
        cancelled = sum(1 for r in runs if r.get("conclusion") == "cancelled")

        # Collect failed jobs for failed runs
        failed_jobs: list[GitHubWorkflowJobEvidence] = []
        failure_reasons: list[str] = []
        flaky = False

        for run in runs:
            run_id = run.get("run_id")
            if run.get("conclusion") in {"failure", "timed_out"} and run_id:
                try:
                    jobs = await self.list_workflow_jobs(owner, repo, run_id)
                    for job in jobs:
                        if job.conclusion in {"failure", "timed_out", "cancelled"}:
                            failed_jobs.append(job)
                            for step_name in job.failed_step_names:
                                if step_name not in failure_reasons:
                                    failure_reasons.append(step_name)
                except Exception:
                    pass

        # Flaky detection: more than one run with alternating conclusions
        conclusions = [r.get("conclusion") for r in runs if r.get("conclusion")]
        if (
            len(conclusions) >= 2
            and "success" in conclusions
            and "failure" in conclusions
        ):
            flaky = True

        suggested = None
        if failure > 0:
            suggested = (
                f"{failure} workflow runs failed; inspect failed jobs for root cause"
            )
        elif pending > 0:
            suggested = f"{pending} workflow runs pending; wait for completion"

        return GitHubCIDiagnosticEvidence(
            repository_hash=repo_hash,
            total_runs=len(runs),
            success_runs=success,
            failure_runs=failure,
            pending_runs=pending,
            cancelled_runs=cancelled,
            failure_reasons=failure_reasons[:20],
            flaky_indicator=flaky,
            failed_jobs=failed_jobs[:50],
            log_analysis_withheld=True,
            truncated=len(failed_jobs) >= 50,
            suggested_next_action=suggested,
        )


__all__ = ["GitHubDiagnosticAdapter", "GitHubDiagnosticAdapterError"]
