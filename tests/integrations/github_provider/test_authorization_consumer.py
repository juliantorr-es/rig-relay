"""Tests for authorization consumer and governed GitHub mutation boundary.

Uses Lane A's remote_action_authorization to issue/validate/consume receipts,
then proves the full fake-endpoint mutation corridor for profile update,
repo create, and pages configure. Tests all refusal paths."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from rig_relay.governance.remote_action_authorization import (
    RemoteActionClass,
    issue_remote_action_authorization,
)
from rig_relay.integrations.github_provider._authorization_consumer import (
    ConsumerOutcome,
    ConsumerResult,
    GitHubAuthorizationConsumer,
    compute_request_digest,
)
from rig_relay.integrations.github_provider._user_adapter import GitHubUserAdapter
from rig_relay.integrations.github_provider._user_models import (
    GitHubProfileChangeProposal,
    GitHubUserProfile,
)
from rig_relay.integrations.github_provider._repo_bootstrap import (
    BootstrapPlan,
    BootstrapResult,
    GitHubBootstrapAdapter,
)
from rig_relay.integrations.github_provider._pages_adapter import (
    GitHubPagesAdapter,
    PagesPublicationResult,
)

GITHUB_API_BASE = "https://api.github.com"


def _make_profile():
    return GitHubUserProfile(
        login="test-user",
        user_id=1,
        name="Old Name",
        bio="Old bio",
        email_available=True,
        email_hash="sha256:abc",
    )


# ═══════════════════════════════════════════════════════════════════════
# ── Action Class Mapping ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_all_ten_action_classes_have_mapping():
    """Every Lane A RemoteActionClass must have a Lane B mapping."""
    from rig_relay.integrations.github_provider._authorization_consumer import (
        _LANE_B_TO_LANE_A_ACTION,
    )

    mapped = {v for v in _LANE_B_TO_LANE_A_ACTION.values()}
    for action in RemoteActionClass:
        assert action in mapped, f"Missing mapping for {action.value}"


# ═══════════════════════════════════════════════════════════════════════
# ── Request Digest ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_request_digest_deterministic():
    d1 = compute_request_digest({"name": "test", "value": 42})
    d2 = compute_request_digest({"name": "test", "value": 42})
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_request_digest_different():
    d1 = compute_request_digest({"name": "test"})
    d2 = compute_request_digest({"name": "different"})
    assert d1 != d2


# ═══════════════════════════════════════════════════════════════════════
# ── Issue Authorization ────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_issue_authorization_valid():
    result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload={"name": "test-repo"},
        target_identity="test-user/test-repo",
        purpose="Test repo creation",
    )
    assert result.outcome == ConsumerOutcome.AUTHORIZED.value
    assert result.authorization_id != ""


def test_issue_unknown_operation():
    result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="nonexistent", request_payload={}, target_identity="x"
    )
    assert result.outcome == ConsumerOutcome.ACTION_MISMATCH.value


def test_issue_without_digest_refused():
    result = issue_remote_action_authorization(
        action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        request_digest="",
    )
    assert not result.is_authorized


# ═══════════════════════════════════════════════════════════════════════
# ── Validate and Consume — Success ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_validate_and_consume_success():
    payload = {"name": "test-repo", "private": False, "auto_init": False}
    target = "user/test-repo"

    result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create", request_payload=payload, target_identity=target
    )

    assert result.outcome == ConsumerOutcome.AUTHORIZED.value
    auth_id = result.authorization_id

    _result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=auth_id,
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=target,
    )
    assert _result.outcome == ConsumerOutcome.AUTHORIZED.value


# ═══════════════════════════════════════════════════════════════════════
# ── Validate and Consume — Refusal Paths ───────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_validate_no_authorization_id():
    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id="",
        operation_kind="repo_create",
        request_payload={},
        target_identity="x",
    )
    assert result.outcome == ConsumerOutcome.MISSING_AUTHORIZATION.value


def test_validate_wrong_action():
    payload = {"name": "test-repo", "private": False, "auto_init": False}
    target = "user/test-repo"

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create", request_payload=payload, target_identity=target
    )

    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="issue_create",  # wrong action
        request_payload=payload,
        target_identity=target,
    )
    assert result.outcome == ConsumerOutcome.ACTION_MISMATCH.value


def test_validate_wrong_digest():
    payload = {"name": "repo-a", "private": False, "auto_init": False}
    target = "user/repo-a"

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create", request_payload=payload, target_identity=target
    )

    wrong_payload = {"name": "repo-b", "private": False, "auto_init": False}
    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="repo_create",
        request_payload=wrong_payload,
        target_identity=target,
    )
    assert result.outcome == ConsumerOutcome.REQUEST_DIGEST_MISMATCH.value


def test_validate_wrong_target():
    payload = {"name": "repo-x", "private": False, "auto_init": False}
    target = "user/repo-x"

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create", request_payload=payload, target_identity=target
    )

    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="repo_create",
        request_payload=payload,
        target_identity="other/repo-y",  # wrong target
    )
    assert result.outcome == ConsumerOutcome.TARGET_MISMATCH.value


def test_validate_replay_refused():
    """Single-use receipt cannot be consumed twice."""
    payload = {"name": "repo-r", "private": False, "auto_init": False}
    target = "user/repo-r"

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create", request_payload=payload, target_identity=target
    )

    r1 = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=target,
    )
    assert r1.outcome == ConsumerOutcome.AUTHORIZED.value

    r2 = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="repo_create",
        request_payload=payload,
        target_identity=target,
    )
    assert r2.outcome == ConsumerOutcome.ALREADY_CONSUMED.value


# ═══════════════════════════════════════════════════════════════════════
# ── User Profile Update — Fake Endpoint ────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_profile_update_authorized_success(respx_mock: respx.MockRouter):
    """Valid receipt + user token → bounded PATCH + re-read verification."""
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="valid-token")
    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})

    patch_payload = {f: v for f, v in proposal.after_values.items() if v is not None}
    prior_digest = profile._evidence_digest()

    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="profile_update",
        request_payload=patch_payload,
        target_identity=proposal.login,
        prior_evidence_digest=prior_digest,
    )

    respx_mock.patch(f"{GITHUB_API_BASE}/user").respond(json={"name": "New Name"})
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        json={
            "login": "test-user",
            "id": 1,
            "name": "New Name",
            "bio": "Old bio",
            "email": "test@example.com",
        }
    )

    result = await adapter.execute_profile_change(
        proposal,
        authorization_id=issue_result.authorization_id,
        prior_evidence_digest=prior_digest,
    )
    assert result.status == "executed"
    assert result.verification_match is True


@pytest.mark.asyncio
async def test_profile_update_refuses_without_authorization():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "New"})

    result = await adapter.execute_profile_change(proposal, authorization_id="")
    assert result.status == "authorization_required"


@pytest.mark.asyncio
async def test_profile_update_refuses_wrong_action():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "New"})

    patch_payload = {f: v for f, v in proposal.after_values.items() if v is not None}

    # Issue a receipt for repo_create, not profile_update — but use repo payload
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload={"name": "repo", "private": False, "auto_init": False},
        target_identity="user/repo",
    )

    result = await adapter.execute_profile_change(
        proposal, authorization_id=issue_result.authorization_id
    )
    assert result.status == "refused"


@pytest.mark.asyncio
async def test_profile_update_no_http_when_refused():
    """No HTTP request emitted when authorization is refused."""
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "New"})

    # No mocks set up — if HTTP is called, respx will error
    result = await adapter.execute_profile_change(proposal, authorization_id="")
    assert result.status == "authorization_required"
    assert not hasattr(result, "response_status_code")


# ═══════════════════════════════════════════════════════════════════════
# ── Repo Create — Fake Endpoint ────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_repo_create_authorized_success(respx_mock: respx.MockRouter):
    adapter = GitHubBootstrapAdapter(user_token="valid-token")
    plan = adapter.build_bootstrap_plan(
        purpose="ordinary", proposed_name="my-repo", proposed_description="A repo"
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
            "id": 99,
            "name": "my-repo",
            "full_name": "user/my-repo",
            "html_url": "url",
        }
    )

    result = await adapter.create_repository(
        plan, authorization_id=issue_result.authorization_id
    )
    assert result.status == "executed"
    assert result.repository_name == "my-repo"


@pytest.mark.asyncio
async def test_repo_create_refuses_wrong_digest():
    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(purpose="ordinary", proposed_name="my-repo")

    # Issue receipt for different payload
    wrong_payload = {"name": "other-repo", "private": False, "auto_init": False}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=wrong_payload,
        target_identity=f"user/my-repo",
    )

    result = await adapter.create_repository(
        plan, authorization_id=issue_result.authorization_id
    )
    assert result.status == "refused"


@pytest.mark.asyncio
async def test_repo_create_refuses_without_authorization():
    adapter = GitHubBootstrapAdapter(user_token="token")
    plan = adapter.build_bootstrap_plan(purpose="ordinary", proposed_name="repo")
    result = await adapter.create_repository(plan, authorization_id="")
    assert result.status == "authorization_required"


# ═══════════════════════════════════════════════════════════════════════
# ── Pages Configure — Fake Endpoint ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def pages_token_manager():
    mgr = MagicMock()
    mgr.get_token.return_value = "test-installation-token"
    return mgr


@pytest.mark.asyncio
async def test_pages_configure_authorized_success(
    respx_mock: respx.MockRouter, pages_token_manager
):
    adapter = GitHubPagesAdapter(token_getter=pages_token_manager)

    payload = {"source": {"branch": "main", "path": "/"}}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="pages_configure",
        request_payload=payload,
        target_identity="owner/repo",
        prior_evidence_digest="sha256:pages-prior-evidence",
    )

    respx_mock.put(f"{GITHUB_API_BASE}/repos/owner/repo/pages").respond(204)
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/pages").respond(
        json={
            "source": {"branch": "main", "path": "/"},
            "status": "built",
            "html_url": "https://owner.github.io/repo",
        }
    )

    result = await adapter.configure_pages(
        "owner",
        "repo",
        "main",
        authorization_id=issue_result.authorization_id,
        prior_evidence_digest="sha256:pages-prior-evidence",
    )
    assert result.status == "executed"
    assert result.site_url is not None


@pytest.mark.asyncio
async def test_pages_configure_refuses_without_authorization(pages_token_manager):
    adapter = GitHubPagesAdapter(token_getter=pages_token_manager)
    result = await adapter.configure_pages("owner", "repo", "main", authorization_id="")
    assert result.status == "authorization_required"


# ═══════════════════════════════════════════════════════════════════════
# ── Distinct Action Binding ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_profile_receipt_cannot_authorize_pages():
    """A repo_create receipt cannot authorize pages_configure."""
    payload = {"name": "repo", "private": False, "auto_init": False}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=payload,
        target_identity="user/repo",
    )

    pages_payload = {"source": {"branch": "main", "path": "/"}}
    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="pages_configure",
        request_payload=pages_payload,
        target_identity="owner/repo",
    )
    assert result.outcome == ConsumerOutcome.ACTION_MISMATCH.value


def test_repo_receipt_cannot_authorize_profile():
    """A repo_create receipt cannot authorize profile_update."""
    payload = {"name": "repo", "private": False, "auto_init": False}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="repo_create",
        request_payload=payload,
        target_identity="user/repo",
    )

    profile_payload = {"name": "X"}
    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id=issue_result.authorization_id,
        operation_kind="profile_update",
        request_payload=profile_payload,
        target_identity="test-user",
    )
    assert result.outcome == ConsumerOutcome.ACTION_MISMATCH.value


# ═══════════════════════════════════════════════════════════════════════
# ── Token Non-Disclosure ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_consumer_result_no_token_leakage():
    """ConsumerResult must never contain raw tokens."""
    result = GitHubAuthorizationConsumer.validate_and_consume(
        authorization_id="",
        operation_kind="profile_update",
        request_payload={},
        target_identity="x",
    )
    serialized = result.model_dump_json()
    assert "ghp_" not in serialized
    assert "ghs_" not in serialized
    assert "bearer" not in serialized.lower()


# ═══════════════════════════════════════════════════════════════════════
# ── Replay Refusal — End-to-End ────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_profile_update_replay_refused(respx_mock: respx.MockRouter):
    """Receipt consumed once; second attempt refused."""
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "New"})

    patch_payload = {f: v for f, v in proposal.after_values.items() if v is not None}
    issue_result = GitHubAuthorizationConsumer.issue_authorization(
        operation_kind="profile_update",
        request_payload=patch_payload,
        target_identity=proposal.login,
        prior_evidence_digest="sha256:any",
    )

    # First execution — consumes receipt
    respx_mock.patch(f"{GITHUB_API_BASE}/user").respond(json={"name": "New"})
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        json={"login": "test-user", "id": 1, "name": "New", "email": "test@test.com"}
    )

    r1 = await adapter.execute_profile_change(
        proposal,
        authorization_id=issue_result.authorization_id,
        prior_evidence_digest="sha256:any",
    )
    assert r1.status == "executed"

    # Second execution with same receipt — refused
    r2 = await adapter.execute_profile_change(
        proposal,
        authorization_id=issue_result.authorization_id,
        prior_evidence_digest="sha256:any",
    )
    assert r2.status == "refused"


# ═══════════════════════════════════════════════════════════════════════
# ── Capability Contracts ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def test_all_contracts_consume_lane_a():
    from rig_relay.integrations.github_provider._authorization_consumer import (
        all_github_capability_contracts,
    )

    contracts = all_github_capability_contracts()
    assert len(contracts) == 10
    for c in contracts:
        assert c.consumes_lane_a_authority is True
        assert c.lane_a_integrated is True


def test_contract_has_action_class():
    from rig_relay.integrations.github_provider._authorization_consumer import (
        get_github_capability_contract,
    )

    c = get_github_capability_contract("profile_update")
    assert c is not None
    assert c.lane_a_action_class == RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value
    assert c.requires_freshness is True
    assert c.token_type == "user_access_token"
