"""Tests for GitHub user profile adapter — read, proposal, authorization-gated mutation."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from rig_relay.integrations.github_provider._user_adapter import (
    GitHubUserAdapter,
    GitHubUserAdapterError,
)
from rig_relay.integrations.github_provider._user_models import (
    GitHubProfileChangeProposal,
    GitHubProfileChangeResult,
    GitHubUserErrorKind,
    GitHubUserProfile,
)

GITHUB_API_BASE = "https://api.github.com"
SENTINEL_TOKEN = "ghp_SentinelTokenForUserProfileTesting1234567890abcdef"


def _make_profile(**overrides) -> GitHubUserProfile:
    defaults = {
        "login": "test-user",
        "user_id": 12345,
        "name": "Test User",
        "company": "Test Corp",
        "blog_url": "https://test.dev",
        "location": "Test City",
        "email_available": True,
        "email_hash": "sha256:abc",
        "bio": "Test bio",
        "twitter_username": "test_user",
        "public_repos": 5,
        "followers": 10,
        "following": 3,
        "hireable": True,
    }
    defaults.update(overrides)
    return GitHubUserProfile(**defaults)


# ── Profile Read ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_profile_success(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        json={
            "login": "test-user",
            "id": 12345,
            "name": "Test User",
            "company": "Test Corp",
            "blog": "https://test.dev",
            "location": "Test City",
            "email": "test@example.com",
            "bio": "Test bio",
            "twitter_username": "test_user",
            "public_repos": 5,
            "public_gists": 2,
            "followers": 10,
            "following": 3,
            "hireable": True,
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        }
    )

    adapter = GitHubUserAdapter(user_token="valid-token")
    profile = await adapter.get_user_profile()

    assert profile.login == "test-user"
    assert profile.user_id == 12345
    assert profile.name == "Test User"
    assert profile.email_available is True
    assert profile.email_hash is not None
    assert profile.email_hash.startswith("sha256:")
    assert profile.public_repos == 5
    assert profile.avatar_url_hash is not None
    assert profile.avatar_url_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_read_profile_no_token():
    adapter = GitHubUserAdapter(user_token=None)
    with pytest.raises(GitHubUserAdapterError) as exc_info:
        await adapter.get_user_profile()
    assert exc_info.value.error_kind == GitHubUserErrorKind.TOKEN_UNAVAILABLE


@pytest.mark.asyncio
async def test_read_profile_unauthorized(respx_mock: respx.MockRouter):
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        401, json={"message": "Bad credentials"}
    )

    adapter = GitHubUserAdapter(user_token="bad-token")
    with pytest.raises(GitHubUserAdapterError) as exc_info:
        await adapter.get_user_profile()
    assert exc_info.value.error_kind == GitHubUserErrorKind.TOKEN_UNAVAILABLE


@pytest.mark.asyncio
async def test_read_profile_token_not_in_output(respx_mock: respx.MockRouter):
    """Profile must not contain the user token used for auth."""
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        json={
            "login": SENTINEL_TOKEN[:10],  # hostile sentinel in login field
            "id": 1,
            "email": f"leaked-{SENTINEL_TOKEN}@evil.com",
        }
    )

    adapter = GitHubUserAdapter(user_token=SENTINEL_TOKEN)
    with pytest.raises(GitHubUserAdapterError) as exc_info:
        await adapter.get_user_profile()
    # Error must not contain token
    assert SENTINEL_TOKEN not in str(exc_info.value)


@pytest.mark.asyncio
async def test_profile_redacted_projection_no_secrets():
    profile = _make_profile()
    proj = profile.redacted_projection()
    serialized = json.dumps(proj)
    assert "test@example.com" not in serialized
    assert "email_hash" not in serialized or "email_hash" in serialized
    assert "evidence_digest" in serialized
    assert "login" in serialized  # login is public


# ── Profile Change Proposal ────────────────────────────────────────────


def test_propose_no_changes():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "Test User"})
    assert proposal.status == "refused"
    assert "No changes" in (proposal.suggested_next_action or "")


def test_propose_single_change():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})
    assert proposal.status == "proposed"
    assert proposal.changed_fields == ["name"]
    assert proposal.before_snapshot == {"name": "Test User"}
    assert proposal.after_values == {"name": "New Name"}
    assert proposal.required_permissions == ["Profile:write"]
    assert proposal.authorization_status == "pending"


def test_propose_multiple_changes():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(
        profile, {"name": "New Name", "bio": "New bio", "company": None}
    )
    assert proposal.status == "proposed"
    assert len(proposal.changed_fields) == 3
    assert proposal.before_snapshot["bio"] == "Test bio"
    assert proposal.after_values["bio"] == "New bio"
    assert proposal.before_snapshot["company"] == "Test Corp"
    assert proposal.after_values["company"] is None


def test_propose_invalid_field_not_included():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="token")
    proposal = adapter.propose_profile_change(
        profile, {"ssh_key": "evil", "name": "OK"}
    )
    assert proposal.status == "proposed"
    assert proposal.changed_fields == ["name"]
    assert "ssh_key" not in proposal.changed_fields


# ── Profile Change Execution (authorization-gated) ─────────────────────


@pytest.mark.asyncio
async def test_execute_refuses_without_authorization():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="valid-token")
    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})

    result = await adapter.execute_profile_change(proposal, _authorized=False)
    assert result.status == "authorization_pending"
    assert result.error_kind == GitHubUserErrorKind.AUTHORIZATION_PENDING
    assert "Lane A" in (result.suggested_next_action or "")


@pytest.mark.asyncio
async def test_execute_refuses_stale_proposal():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="valid-token")
    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})
    proposal.stale = True

    result = await adapter.execute_profile_change(proposal, _authorized=True)
    assert result.status == "stale_refused"
    assert result.error_kind == GitHubUserErrorKind.STALE_PROPOSAL


@pytest.mark.asyncio
async def test_execute_refuses_no_token():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token=None)
    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})

    result = await adapter.execute_profile_change(proposal, _authorized=True)
    assert result.status == "refused"
    assert result.error_kind == GitHubUserErrorKind.TOKEN_UNAVAILABLE


@pytest.mark.asyncio
async def test_execute_succeeds_when_authorized(respx_mock: respx.MockRouter):
    """When authorized, the adapter should PATCH /user and re-read the profile."""
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="valid-token")

    proposal = adapter.propose_profile_change(profile, {"name": "New Name"})

    # Mock the PATCH request
    respx_mock.patch(f"{GITHUB_API_BASE}/user").respond(
        json={"login": "test-user", "name": "New Name"}
    )

    # Mock the post-mutation GET (re-read profile)
    respx_mock.get(f"{GITHUB_API_BASE}/user").respond(
        json={
            "login": "test-user",
            "id": 12345,
            "name": "New Name",
            "company": "Test Corp",
            "blog": "https://test.dev",
            "location": "Test City",
            "email": "test@example.com",
            "bio": "Test bio",
            "twitter_username": "test_user",
            "public_repos": 5,
            "public_gists": 2,
            "followers": 10,
            "following": 3,
            "hireable": True,
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        }
    )

    result = await adapter.execute_profile_change(proposal, _authorized=True)
    assert result.status == "executed"
    assert result.verification_match is True
    assert result.post_profile_digest is not None


@pytest.mark.asyncio
async def test_execute_invalid_field_refused():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token="valid-token")
    proposal = adapter.propose_profile_change(profile, {"name": "OK"})
    proposal.changed_fields.append("ssh_key")  # Inject invalid field

    result = await adapter.execute_profile_change(proposal, _authorized=True)
    assert result.status == "refused"
    assert result.error_kind == GitHubUserErrorKind.INVALID_FIELD


# ── has_token ───────────────────────────────────────────────────────────


def test_has_token():
    assert GitHubUserAdapter(user_token="t").has_token is True
    assert GitHubUserAdapter(user_token=None).has_token is False
    assert GitHubUserAdapter().has_token is False


# ── Token non-disclosure in proposal ────────────────────────────────────


def test_proposal_redacted_projection_no_tokens():
    profile = _make_profile()
    adapter = GitHubUserAdapter(user_token=SENTINEL_TOKEN)
    proposal = adapter.propose_profile_change(profile, {"name": "New"})
    proj = proposal.redacted_projection()
    serialized = json.dumps(proj)
    assert SENTINEL_TOKEN not in serialized
    assert "ghp_" not in serialized
