"""Tests for the GitHub Truth Tool — publication verification, CI observation, etc.

Uses respx for the fake GitHub HTTP boundary and a fake token manager
for adapter construction. Tests the tool through its handler methods.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import respx

from rig_relay.core.tools.builtins.github_truth_tool import (
    GitHubTruthArgs,
    GitHubTruthTool,
)

GITHUB_API_BASE = "https://api.github.com"


@pytest.fixture
def fake_token_manager():
    mgr = MagicMock()
    mgr.get_token.return_value = "test-installation-token"
    mgr.config_summary.return_value = {
        "app_id": 123,
        "installation_id": 456,
        "token_cached": True,
        "token_expires_in_seconds": 3000,
        "private_key_present": True,
        "config_source": "environment_variables",
    }
    return mgr


@pytest.fixture
def truth_tool(fake_token_manager):
    """Patch _build_adapter to return a truth adapter with the fake token manager."""
    from rig_relay.integrations.github_provider._truth_adapter import GitHubTruthAdapter

    original = GitHubTruthTool._build_adapter

    def patched():
        return GitHubTruthAdapter(fake_token_manager)

    GitHubTruthTool._build_adapter = staticmethod(patched)
    tool = GitHubTruthTool.from_config(
        lambda: GitHubTruthTool._get_tool_config_class()()
    )
    yield tool
    GitHubTruthTool._build_adapter = original


# ── Tool Metadata ──────────────────────────────────────────────────────


def test_tool_metadata():
    assert GitHubTruthTool.determinism_class.value == "nondeterministic_external_io"
    assert GitHubTruthTool.mutation_class.value == "read_only"
    assert "publication" in GitHubTruthTool.description.lower()
    name = GitHubTruthTool.get_name()
    assert "git_hub_truth" in name


def test_tool_args_validation():
    args = GitHubTruthArgs(
        action="verify_publication", owner="o", repo="r", expected_sha="a" * 40
    )
    assert args.owner == "o"
    assert args.ref == "main"  # default


# ── No Adapter ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_adapter_returns_unavailable():
    original = GitHubTruthTool._build_adapter
    GitHubTruthTool._build_adapter = staticmethod(lambda: None)
    try:
        tool = GitHubTruthTool.from_config(
            lambda: GitHubTruthTool._get_tool_config_class()()
        )
        results = [r async for r in tool.run(GitHubTruthArgs(action="observe_ref"))]
        assert len(results) == 1
        assert results[0].status == "unavailable"
        assert "No GitHub App" in results[0].summary
    finally:
        GitHubTruthTool._build_adapter = original


# ── Publication Verification via Tool ──────────────────────────────────


@pytest.mark.asyncio
async def test_tool_verify_publication_exact(respx_mock: respx.MockRouter, truth_tool):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{sha}/status").respond(
        json={"state": "success", "statuses": []}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{sha}/check-runs").respond(
        json={"check_runs": []}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/actions/runs").respond(
        json={"workflow_runs": []}
    )

    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(
                action="verify_publication", owner="o", repo="r", expected_sha=sha
            )
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.verification_status == "exact_promoted"
    assert result.accepted_head_present is True
    assert result.ci_state == "success"


@pytest.mark.asyncio
async def test_tool_verify_publication_follow_on(
    respx_mock: respx.MockRouter, truth_tool
):
    accepted = "a" * 40
    follow = "b" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": follow}}
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/o/r/compare/{accepted}...{follow}"
    ).respond(
        json={
            "status": "ahead",
            "ahead_by": 2,
            "behind_by": 0,
            "total_commits": 2,
            "files": [],
        }
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{follow}/status").respond(
        json={"state": "success", "statuses": []}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{follow}/check-runs").respond(
        json={"check_runs": []}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/actions/runs").respond(
        json={"workflow_runs": []}
    )

    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(
                action="verify_publication", owner="o", repo="r", expected_sha=accepted
            )
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.verification_status == "accepted_with_follow_on_commits"
    assert result.accepted_head_present is True
    assert result.follow_on_commits_count == 2


# ── CI Status via Tool ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_observe_ci(respx_mock: respx.MockRouter, truth_tool):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{sha}/status").respond(
        json={
            "state": "failure",
            "statuses": [
                {"state": "failure", "context": "ci/test"},
                {"state": "success", "context": "ci/lint"},
            ],
        }
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/commits/{sha}/check-runs").respond(
        json={"check_runs": []}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/actions/runs").respond(
        json={"workflow_runs": []}
    )

    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(action="observe_ci_status", owner="o", repo="r", sha=sha)
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.overall_state == "failure"
    assert result.failed_count == 1
    assert result.passed_count == 1


# ── Ref Observation via Tool ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_observe_ref(respx_mock: respx.MockRouter, truth_tool):
    sha = "c" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/o/r/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )

    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(action="observe_ref", owner="o", repo="r", ref="heads/main")
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert result.remote_head_sha == sha


# ── Missing Args ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_verify_publication_missing_args(truth_tool):
    results = [
        r async for r in truth_tool.run(GitHubTruthArgs(action="verify_publication"))
    ]
    assert results[0].status == "refused"
    assert results[0].error_kind == "github.missing_required_args"


@pytest.mark.asyncio
async def test_tool_observe_ci_missing_args(truth_tool):
    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(action="observe_ci_status", owner="o", repo="r")
        )
    ]
    assert results[0].status == "refused"


# ── Unknown Action ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_unknown_action(truth_tool):
    results = [r async for r in truth_tool.run(GitHubTruthArgs(action="nonexistent"))]
    assert results[0].status == "error"
    assert "Unknown action" in results[0].summary


# ── Installation Access via Tool ───────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_installation_access(truth_tool):
    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(action="observe_installation_access")
        )
    ]
    assert len(results) == 1
    result = results[0]
    assert result.status == "ok"
    assert "available" in result.summary
    assert result.evidence_digest is not None
    assert result.evidence_digest.startswith("sha256:")


# ── Token Non-Disclosure from Tool ────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_result_no_token_leakage(truth_tool):
    """Tool result serialization must not contain tokens."""
    results = [
        r
        async for r in truth_tool.run(
            GitHubTruthArgs(action="observe_installation_access")
        )
    ]
    serialized = results[0].model_dump_json()
    assert "test-installation-token" not in serialized
    assert "ghp_" not in serialized
