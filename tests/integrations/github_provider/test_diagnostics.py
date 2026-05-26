"""Tests for issue intake and CI/CD diagnostic adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import respx

from rig_relay.integrations.github_provider._ci_diagnostics import (
    GitHubDiagnosticAdapter,
    GitHubDiagnosticAdapterError,
)
from rig_relay.integrations.github_provider._issue_intake import (
    GitHubDiagnosticErrorKind,
)

GITHUB_API_BASE = "https://api.github.com"
SENTINEL_LOG = "Error: leaked token ghp_abc123def4567890ghijklmnopqrstuvwxyz in workflow output at /src/secrets.py"


@pytest.fixture
def token_manager():
    mgr = MagicMock()
    mgr.get_token.return_value = "test-installation-token"
    return mgr


@pytest.fixture
def adapter(token_manager):
    return GitHubDiagnosticAdapter(token_getter=token_manager)


# ── Issue Intake ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_issues_success(respx_mock: respx.MockRouter, adapter):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/issues").respond(
        json=[
            {
                "number": 1,
                "title": "Test issue",
                "state": "open",
                "labels": [{"name": "bug"}],
                "comments": 3,
                "created_at": "2024-01-01T00:00:00Z",
                "body": "This is a test issue body",
                "locked": False,
                "html_url": "https://github.com/owner/repo/issues/1",
            },
            {"number": 2, "title": "PR", "state": "open", "pull_request": {"url": "x"}},
        ]
    )

    result = await adapter.list_issues("owner", "repo")
    assert len(result.issues) == 1  # PR is filtered out
    issue = result.issues[0]
    assert issue.issue_number == 1
    assert issue.title == "Test issue"
    assert "bug" in issue.labels
    assert issue.body_available is True
    assert issue.body_hash is not None
    assert issue.body_hash.startswith("sha256:")
    # Raw body must not be in model
    assert "This is a test issue body" not in json.dumps(issue.model_dump())
    assert result.returned_count == 1


@pytest.mark.asyncio
async def test_list_issues_body_with_hostile_content(
    respx_mock: respx.MockRouter, adapter
):
    """Issue body containing token-like text must cause adapter refusal.

    The adapter must detect token-like content in the API response and refuse
    to process it — never silently accept or leak the token into evidence.
    """
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/issues").respond(
        json=[
            {
                "number": 1,
                "title": "Bug report",
                "state": "open",
                "labels": [],
                "comments": 0,
                "body": f"User reported token: {SENTINEL_LOG}",
                "html_url": "https://github.com/owner/repo/issues/1",
            }
        ]
    )

    with pytest.raises(GitHubDiagnosticAdapterError) as exc_info:
        await adapter.list_issues("owner", "repo")
    # Error message must not contain the token itself
    assert SENTINEL_LOG not in str(exc_info.value)


@pytest.mark.asyncio
async def test_list_issues_no_token(token_manager):
    token_manager.get_token.return_value = None
    adapter = GitHubDiagnosticAdapter(token_getter=token_manager)
    with pytest.raises(GitHubDiagnosticAdapterError) as exc_info:
        await adapter.list_issues("owner", "repo")
    assert exc_info.value.error_kind == GitHubDiagnosticErrorKind.PERMISSION_MISSING


# ── CI/CD Diagnostics ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ci_diagnostics_all_success(respx_mock: respx.MockRouter, adapter):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={
            "workflow_runs": [
                {"id": 1, "name": "CI", "status": "completed", "conclusion": "success"},
                {
                    "id": 2,
                    "name": "Lint",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        }
    )

    result = await adapter.get_cicd_diagnostics("owner", "repo")
    assert result.total_runs == 2
    assert result.success_runs == 2
    assert result.failure_runs == 0
    assert result.flaky_indicator is False


@pytest.mark.asyncio
async def test_ci_diagnostics_with_failures(respx_mock: respx.MockRouter, adapter):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={
            "workflow_runs": [
                {"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"},
                {
                    "id": 2,
                    "name": "Lint",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        }
    )

    # Jobs for failed run
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs/1/jobs").respond(
        json={
            "jobs": [
                {
                    "id": 101,
                    "run_id": 1,
                    "name": "build",
                    "status": "completed",
                    "conclusion": "failure",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Build", "conclusion": "failure"},
                        {"name": "Test", "conclusion": "skipped"},
                    ],
                    "html_url": "https://github.com/owner/repo/runs/1/job/101",
                }
            ]
        }
    )

    result = await adapter.get_cicd_diagnostics("owner", "repo")
    assert result.success_runs == 1
    assert result.failure_runs == 1
    assert len(result.failed_jobs) >= 1
    assert result.failed_jobs[0].failed_steps_count == 1
    assert "Build" in result.failure_reasons


@pytest.mark.asyncio
async def test_ci_diagnostics_flaky(respx_mock: respx.MockRouter, adapter):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={
            "workflow_runs": [
                {"id": 1, "name": "CI", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "CI", "status": "completed", "conclusion": "failure"},
                {"id": 3, "name": "CI", "status": "completed", "conclusion": "success"},
            ]
        }
    )

    result = await adapter.get_cicd_diagnostics("owner", "repo")
    assert result.flaky_indicator is True


@pytest.mark.asyncio
async def test_ci_jobs_no_log_leakage(respx_mock: respx.MockRouter, adapter):
    """Failed jobs must not leak raw logs."""
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={
            "workflow_runs": [
                {"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"}
            ]
        }
    )

    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs/1/jobs").respond(
        json={
            "jobs": [
                {
                    "id": 101,
                    "run_id": 1,
                    "name": "build",
                    "status": "completed",
                    "conclusion": "failure",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": f"Build — {SENTINEL_LOG}", "conclusion": "failure"},
                    ],
                    "html_url": f"https://github.com/runs/1?secret={SENTINEL_LOG}",
                }
            ]
        }
    )

    result = await adapter.get_cicd_diagnostics("owner", "repo")
    serialized = result.model_dump_json()
    assert SENTINEL_LOG not in serialized, "Raw workflow log leaked into CI evidence"
    assert "ghp_" not in serialized, "Token-like pattern leaked into CI evidence"


@pytest.mark.asyncio
async def test_ci_diagnostics_no_token(token_manager):
    token_manager.get_token.return_value = None
    adapter = GitHubDiagnosticAdapter(token_getter=token_manager)
    result = await adapter.get_cicd_diagnostics("owner", "repo")
    assert result.error_kind == GitHubDiagnosticErrorKind.CI_LIST_RUNS_FAILED


# ── Redacted Projection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_list_redacted_projection(respx_mock: respx.MockRouter, adapter):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/issues").respond(
        json=[
            {
                "number": 1,
                "title": "Bug",
                "state": "open",
                "labels": [],
                "body": "secret body",
            }
        ]
    )

    result = await adapter.list_issues("owner", "repo")
    proj = result.redacted_projection()
    assert "evidence_digest" in proj
    assert "secret body" not in json.dumps(proj)
