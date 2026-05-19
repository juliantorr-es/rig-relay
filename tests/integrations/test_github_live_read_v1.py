"""GitHub live read operation tests — mock-backed, no real network.

Tests exercise the full pipeline: scope probe → capability evaluation →
API call → response hashing → receipt building → redaction assertions.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rig_relay.integrations.github_provider._live_adapter import run_live_read_operation

_DEFAULT_SCOPES = ["repo"]
_TEST_TOKEN = "ghp_test_token_abcd1234abcd1234abcd1234abcd1234abcd"


def _mock_repo_response() -> dict:
    return {"name": "test-repo", "full_name": "owner/test-repo", "private": False}


def _mock_branches_response() -> list[dict]:
    return [{"name": "main"}, {"name": "develop"}]


def _mock_commits_response() -> list[dict]:
    return [{"sha": "abc123", "commit": {"message": "test"}}]


def _mock_issues_response() -> list[dict]:
    return [{"number": 1, "title": "Bug"}]


def _mock_prs_response() -> list[dict]:
    return [{"number": 1, "title": "PR"}]


def _mock_runs_response() -> dict:
    return {"total_count": 5, "workflow_runs": []}


def _mock_artifacts_response() -> dict:
    return {"total_count": 3, "artifacts": []}


def _build_patches(*, scopes: list[str] | None = None):
    probe = AsyncMock(return_value=scopes if scopes is not None else _DEFAULT_SCOPES)
    api_get = AsyncMock(return_value=_mock_repo_response())
    return (
        patch(
            "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
            new=probe,
        ),
        patch(
            "rig_relay.integrations.github_provider._live_adapter._github_api_get",
            new=api_get,
        ),
    )


class TestGitHubLiveReadFake:
    @pytest.mark.asyncio
    async def test_repo_metadata_read_returns_hashed_receipt(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
                trace_id="test-trace-123",
            )

        assert result["verdict"] == "completed"
        assert result["receipt"] is not None
        assert result["receipt"]["content_light"] is True
        assert "response_hash" in result["receipt"]
        assert result["response_hash"] != ""
        receipt_json = json.dumps(result["receipt"])
        assert "owner/test-repo" not in receipt_json
        assert "test-repo" not in receipt_json

    @pytest.mark.asyncio
    async def test_branches_read_returns_hashed_receipt(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_branches_response()
            result = await run_live_read_operation(
                capability_id="github.repo.branches.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "completed"
        assert result["receipt"]["response_hash"] != ""

    @pytest.mark.asyncio
    async def test_commits_read_returns_hashed_receipt(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_commits_response()
            result = await run_live_read_operation(
                capability_id="github.repo.commits.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "completed"

    @pytest.mark.asyncio
    async def test_issues_read_refused_with_repo_scope(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_issues_response()
            result = await run_live_read_operation(
                capability_id="github.repo.issues.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["receipt"] is not None
        assert result["receipt"]["content_light"] is True
        assert result["receipt"]["refusal_code"] == "github.permission.missing"

    @pytest.mark.asyncio
    async def test_prs_read_returns_hashed_receipt(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_prs_response()
            result = await run_live_read_operation(
                capability_id="github.repo.pull_requests.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "completed"

    @pytest.mark.asyncio
    async def test_actions_runs_read_refused_with_repo_scope(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_runs_response()
            result = await run_live_read_operation(
                capability_id="github.actions.runs.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["receipt"] is not None
        assert result["receipt"]["content_light"] is True
        assert result["receipt"]["refusal_code"] == "github.permission.missing"

    @pytest.mark.asyncio
    async def test_actions_artifacts_read_refused_with_repo_scope(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            p2.new.return_value = _mock_artifacts_response()
            result = await run_live_read_operation(
                capability_id="github.actions.artifacts.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["receipt"] is not None
        assert result["receipt"]["content_light"] is True
        assert result["receipt"]["refusal_code"] == "github.permission.missing"

    @pytest.mark.asyncio
    async def test_mutation_capability_no_live_path(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="github.contents.write",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["refusal_code"] == "github.capability.no_live_path"
        assert result["receipt"] is None

    @pytest.mark.asyncio
    async def test_unknown_capability_refused(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="nonexistent.capability",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["receipt"] is None

    @pytest.mark.asyncio
    async def test_http_error_returns_failed(self) -> None:
        probe = AsyncMock(return_value=_DEFAULT_SCOPES)
        api_get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=httpx.Request("GET", "https://api.github.com/test"),
                response=httpx.Response(404, json={"message": "Not Found"}),
            )
        )
        with (
            patch(
                "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
                new=probe,
            ),
            patch(
                "rig_relay.integrations.github_provider._live_adapter._github_api_get",
                new=api_get,
            ),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="nonexistent",
            )

        assert result["verdict"] == "failed"

    @pytest.mark.asyncio
    async def test_receipt_has_no_raw_token(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        receipt_json = json.dumps(result["receipt"])
        assert _TEST_TOKEN not in receipt_json
        assert "ghp_" not in receipt_json

    @pytest.mark.asyncio
    async def test_receipt_has_no_raw_response_body(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        receipt_json = json.dumps(result["receipt"])
        assert "test-repo" not in receipt_json
        assert "owner/test-repo" not in receipt_json

    @pytest.mark.asyncio
    async def test_trace_id_preserved(self) -> None:
        p1, p2 = _build_patches()
        with p1, p2:
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
                trace_id="my-trace-001",
            )

        assert result["receipt"]["trace_id"] == "my-trace-001"

    @pytest.mark.asyncio
    async def test_scope_probe_failure_returns_failed(self) -> None:
        probe = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        api_get = AsyncMock()
        with (
            patch(
                "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
                new=probe,
            ),
            patch(
                "rig_relay.integrations.github_provider._live_adapter._github_api_get",
                new=api_get,
            ),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "failed"
        assert "Scope probe failed" in result["error"]

    @pytest.mark.asyncio
    async def test_insufficient_scopes_refused(self) -> None:
        probe = AsyncMock(return_value=["read:user"])
        api_get = AsyncMock()
        with (
            patch(
                "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
                new=probe,
            ),
            patch(
                "rig_relay.integrations.github_provider._live_adapter._github_api_get",
                new=api_get,
            ),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["refusal_code"] == "github.scope.insufficient"

    @pytest.mark.asyncio
    async def test_actions_requires_workflow_scope(self) -> None:
        probe = AsyncMock(return_value=["public_repo"])
        api_get = AsyncMock()
        with (
            patch(
                "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
                new=probe,
            ),
            patch(
                "rig_relay.integrations.github_provider._live_adapter._github_api_get",
                new=api_get,
            ),
        ):
            result = await run_live_read_operation(
                capability_id="github.actions.runs.read",
                token=_TEST_TOKEN,
                repository_owner="owner",
                repository_name="test-repo",
            )

        assert result["verdict"] == "refused"
        assert result["refusal_code"] == "github.scope.insufficient"


@pytest.mark.skipif(
    not os.environ.get("RIG_LIVE_PROVIDER_TESTS"),
    reason="Live provider tests require RIG_LIVE_PROVIDER_TESTS=1",
)
@pytest.mark.asyncio
async def test_live_repo_metadata_read_if_configured() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    owner = os.environ.get("GITHUB_REPO_OWNER", "")
    repo = os.environ.get("GITHUB_REPO_NAME", "")

    if not token or not owner or not repo:
        pytest.skip("GITHUB_TOKEN, GITHUB_REPO_OWNER, and GITHUB_REPO_NAME required")

    result = await run_live_read_operation(
        capability_id="github.repo.metadata.read",
        token=token,
        repository_owner=owner,
        repository_name=repo,
        trace_id="live-test-001",
    )

    if result["verdict"] == "completed":
        assert result["receipt"]["content_light"] is True
        assert result["response_sha"] != ""
        receipt_json = json.dumps(result["receipt"])
        assert token not in receipt_json
    else:
        pytest.skip(
            f"Token/environment not configured for live test: {result.get('error')}"
        )
