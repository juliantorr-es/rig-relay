"""Tests for GitHub repository bootstrap — plan, authorization-gated creation."""

from __future__ import annotations

import pytest
import respx

from rig_relay.integrations.github_provider._repo_bootstrap import (
    BootstrapErrorKind,
    GitHubBootstrapAdapter,
    RepoPurpose,
)

GITHUB_API_BASE = "https://api.github.com"
SENTINEL_TOKEN = "ghp_BootstrapSentinelTokenForTesting1234567890abcdef"


# ── Plan Building ──────────────────────────────────────────────────────


def test_build_ordinary_repo_plan():
    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value,
        proposed_name="my-new-repo",
        proposed_description="A new project",
        local_head_sha="a" * 40,
    )
    assert plan.purpose == "ordinary"
    assert plan.proposed_name == "my-new-repo"
    assert plan.required_permissions == ["Administration:write"]
    assert plan.authorization_status == "pending"
    assert not plan.is_ready()


def test_build_dirty_local_refused():
    adapter = GitHubBootstrapAdapter()
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="repo", is_dirty=True
    )
    assert plan.status == "refused"
    assert len(plan.blockers) >= 1
    assert "uncommitted" in plan.blockers[0].lower()


def test_build_no_name_refused():
    adapter = GitHubBootstrapAdapter()
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name=""
    )
    assert plan.status == "refused"
    assert any("name" in b.lower() for b in plan.blockers)


def test_build_user_pages_warns_wrong_convention():
    adapter = GitHubBootstrapAdapter()
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.USER_PAGES.value, proposed_name="my-cool-site"
    )
    assert any(".github.io" in w for w in plan.warnings)


# ── Authorization-Gated Creation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_refuses_without_authorization():
    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="test-repo"
    )

    result = await adapter.create_repository(plan, authorization_id="")
    assert result.status == "authorization_required"
    assert result.error_kind == BootstrapErrorKind.AUTHORIZATION_PENDING
    assert "Lane A" in (result.suggested_next_action or "")


@pytest.mark.asyncio
async def test_create_refuses_stale_plan():
    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="test-repo"
    )
    plan.stale = True

    result = await adapter.create_repository(plan, authorization_id="")
    assert result.status == "stale_refused"
    assert result.error_kind == BootstrapErrorKind.STALE_LOCAL_HEAD


@pytest.mark.asyncio
async def test_create_refuses_no_token():
    adapter = GitHubBootstrapAdapter(user_token=None)
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="test-repo"
    )

    result = await adapter.create_repository(plan, authorization_id="")
    assert result.status == "authorization_required"


@pytest.mark.asyncio
async def test_create_succeeds_when_authorized(respx_mock: respx.MockRouter):
    from rig_relay.integrations.github_provider._authorization_consumer import (
        GitHubAuthorizationConsumer,
    )

    adapter = GitHubBootstrapAdapter(user_token="valid-token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value,
        proposed_name="test-repo",
        proposed_description="A test repo",
    )

    payload = {
        "name": plan.proposed_name,
        "private": False,
        "auto_init": False,
        "description": plan.proposed_description,
    }
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=f"authenticated-user/{plan.proposed_name}",
    )

    respx_mock.post(f"{GITHUB_API_BASE}/user/repos").respond(
        json={
            "id": 98765,
            "name": "test-repo",
            "full_name": "test-owner/test-repo",
            "html_url": "https://github.com/test-owner/test-repo",
            "private": False,
        }
    )

    result = await adapter.create_repository(
        plan, authorization_id=issue_result.authorization_id
    )
    assert result.status == "executed"
    assert result.repository_name == "test-repo"
    assert result.repository_id == 98765


@pytest.mark.asyncio
async def test_create_name_collision(respx_mock: respx.MockRouter):
    from rig_relay.integrations.github_provider._authorization_consumer import (
        GitHubAuthorizationConsumer,
    )

    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="existing-repo"
    )

    payload = {"name": plan.proposed_name, "private": False, "auto_init": False}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=f"authenticated-user/{plan.proposed_name}",
    )

    respx_mock.post(f"{GITHUB_API_BASE}/user/repos").respond(
        422, json={"message": "name already exists"}
    )

    result = await adapter.create_repository(
        plan, authorization_id=issue_result.authorization_id
    )
    assert result.status == "refused"
    assert result.error_kind == BootstrapErrorKind.NAME_COLLISION


@pytest.mark.asyncio
async def test_create_missing_permission(respx_mock: respx.MockRouter):
    from rig_relay.integrations.github_provider._authorization_consumer import (
        GitHubAuthorizationConsumer,
    )

    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="repo"
    )

    payload = {"name": plan.proposed_name, "private": False, "auto_init": False}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=f"authenticated-user/{plan.proposed_name}",
    )

    respx_mock.post(f"{GITHUB_API_BASE}/user/repos").respond(
        403, json={"message": "Resource not accessible"}
    )

    result = await adapter.create_repository(
        plan, authorization_id=issue_result.authorization_id
    )
    assert result.status == "refused"
    assert result.error_kind == BootstrapErrorKind.MISSING_ADMIN_PERMISSION


# ── Token Non-Disclosure ────────────────────────────────────────────────


def test_plan_no_token_in_serialization():
    adapter = GitHubBootstrapAdapter(user_token=SENTINEL_TOKEN)
    plan = adapter.build_bootstrap_plan(
        purpose=RepoPurpose.ORDINARY.value, proposed_name="repo"
    )
    serialized = plan.model_dump_json()
    assert SENTINEL_TOKEN not in serialized
    assert "ghp_" not in serialized
