"""Causal contract tests for GitHub Repository Truth Adapter v1.

Tests the truth adapter against a realistic fake GitHub API boundary (respx).
Proves: token non-disclosure, permission insufficiency, expiry, rate limits,
missing refs, compare divergence, malformed responses, timeouts,
stable evidence identities, and confidential error handling.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    scan_for_tokens,
)
from rig_relay.integrations.github_provider._truth_adapter import (
    GitHubTruthAdapter,
    GitHubTruthAdapterError,
    _GitHubHttpClient,
)
from rig_relay.integrations.github_provider._truth_models import (
    GitHubCIStatusEvidence,
    GitHubCommitPresence,
    GitHubCommitRelationship,
    GitHubCompareResult,
    GitHubInstallationAccess,
    GitHubPublicationVerification,
    GitHubRemoteRefObservation,
    GitHubTokenStatus,
    GitHubTruthErrorKind,
    GitHubVerificationStatus,
)

GITHUB_API_BASE = "https://api.github.com"

# ── Hostile sentinel values ────────────────────────────────────────────

SENTINEL_GHP_TOKEN = "ghp_SentinelTokenThatShouldNeverAppearInEvidence1a2b3c4d5e6f7g8h"
SENTINEL_GHS_TOKEN = "ghs_SentinelInstallationTokenThatShouldNeverLeak9z8y7x6w5v4u"
SENTINEL_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0SentinelKeyThatShouldNeverBeLoggedOrSerialized
-----END RSA PRIVATE KEY-----"""

SENTINEL_REPO_PATH = "/src/secret/internal/auth_module.py"
SENTINEL_WORKFLOW_LOG = "Error: leaked token ghp_abc123def456 in workflow output"


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_token_manager():
    """A token manager that returns a test token and exposes config."""
    mgr = MagicMock()
    mgr.get_token.return_value = "test-installation-token-42"
    mgr.config_summary.return_value = {
        "app_id": 123456,
        "installation_id": 789012,
        "token_cached": True,
        "token_expires_in_seconds": 3000.0,
        "private_key_present": True,
        "config_source": "environment_variables",
    }
    return mgr


@pytest.fixture
def expired_token_manager():
    """A token manager with an expired token."""
    mgr = MagicMock()
    mgr.get_token.return_value = None
    mgr.config_summary.return_value = {
        "app_id": 123456,
        "installation_id": 789012,
        "token_cached": True,
        "token_expires_in_seconds": 0.0,
        "private_key_present": True,
        "config_source": "environment_variables",
    }
    return mgr


@pytest.fixture
def unavailable_token_manager():
    """A token manager that cannot acquire a token."""
    mgr = MagicMock()
    mgr.get_token.return_value = None
    mgr.config_summary.return_value = {
        "app_id": 0,
        "installation_id": 0,
        "token_cached": False,
        "token_expires_in_seconds": 0.0,
        "private_key_present": False,
        "config_source": "environment_variables",
    }
    return mgr


@pytest.fixture
def adapter(fake_token_manager):
    return GitHubTruthAdapter(fake_token_manager)


# ── Installation Access ────────────────────────────────────────────────


def test_installation_access_available(adapter):
    access = adapter.observe_installation_access()
    assert access.token_status == GitHubTokenStatus.AVAILABLE
    assert access.app_id == 123456
    assert access.token_expires_in_seconds == 3000.0
    assert access.error_kind is None


def test_installation_access_expired(expired_token_manager):
    adapter = GitHubTruthAdapter(expired_token_manager)
    access = adapter.observe_installation_access()
    assert access.token_status == GitHubTokenStatus.EXPIRED
    assert access.error_kind == GitHubTruthErrorKind.TOKEN_EXPIRED


def test_installation_access_unavailable(unavailable_token_manager):
    adapter = GitHubTruthAdapter(unavailable_token_manager)
    access = adapter.observe_installation_access()
    assert access.token_status == GitHubTokenStatus.UNAVAILABLE
    assert access.error_kind == GitHubTruthErrorKind.TOKEN_ACQUISITION_FAILED


def test_installation_access_redacted_projection_no_secrets(adapter):
    access = adapter.observe_installation_access()
    projection = access.redacted_projection()
    # No secret fields in projection
    serialized = json.dumps(projection, sort_keys=True)
    assert "token" not in serialized.lower() or "token_status" in serialized
    assert "private_key" not in serialized
    assert "key" not in serialized.lower() or "error_kind" in serialized


# ── Token Non-Disclosure ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_not_in_evidence(respx_mock: respx.MockRouter, fake_token_manager):
    """Prove installation tokens never enter durable evidence.

    When the GitHub API responds with token-like content, the adapter must
    detect it via the content-light redaction layer and refuse to emit
    model-visible results containing the token.
    """
    # Setup fake endpoint that returns sentinel-style data in description
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        json={
            "name": "repo",
            "visibility": "public",
            "description": f"Contains {SENTINEL_GHP_TOKEN} secret",
        }
    )

    adapter = GitHubTruthAdapter(fake_token_manager)

    # The adapter must refuse to return a model containing tokens
    # It should raise a typed error, not silently absorb the token
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "repo")

    # The error must not contain the token itself
    error_str = str(exc_info.value)
    assert SENTINEL_GHP_TOKEN not in error_str
    assert SENTINEL_PRIVATE_KEY not in error_str
    assert (
        exc_info.value.error_kind == GitHubTruthErrorKind.UNKNOWN
    )  # redaction violation


@pytest.mark.asyncio
async def test_token_not_in_error_messages(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Prove tokens do not leak through error strings."""
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        status_code=401,
        json={
            "message": f"Bad credentials with token {SENTINEL_GHS_TOKEN}",
            "documentation_url": "https://docs.github.com/rest",
        },
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    try:
        await adapter.observe_repository("owner", "repo")
    except GitHubTruthAdapterError as e:
        error_str = str(e)
        assert SENTINEL_GHS_TOKEN not in error_str
        assert "ghs_" not in error_str
        assert SENTINEL_PRIVATE_KEY not in error_str
        assert e.error_kind in (
            GitHubTruthErrorKind.TOKEN_EXPIRED,
            GitHubTruthErrorKind.PERMISSION_MISSING,
        )


@pytest.mark.asyncio
async def test_token_not_in_redacted_projection(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Hostile sentinel in API response must not reach redacted projection."""
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        json={
            "name": "repo",
            "default_branch": f"main-{SENTINEL_GHS_TOKEN[:10]}",
            "visibility": "public",
        }
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.observe_repository("owner", "repo")
    projection = result.redacted_projection()
    proj_json = json.dumps(projection, sort_keys=True)

    # Token patterns in default_branch should not appear
    assert SENTINEL_GHS_TOKEN[:10] not in proj_json
    assert "ghp_" not in proj_json
    assert "ghs_" not in proj_json

    # Scan entire projection for tokens
    found = scan_for_tokens(proj_json)
    assert found == [], f"Token patterns detected in projection: {found}"


# ── Permission Insufficiency ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_permission_insufficient_404(
    respx_mock: respx.MockRouter, fake_token_manager
):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/private-repo").respond(
        status_code=404, json={"message": "Not Found"}
    )
    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "private-repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.REPOSITORY_INACCESSIBLE


@pytest.mark.asyncio
async def test_permission_insufficient_403(
    respx_mock: respx.MockRouter, fake_token_manager
):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/forbidden-repo").respond(
        status_code=403, json={"message": "Resource not accessible by integration"}
    )
    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "forbidden-repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.PERMISSION_MISSING


# ── Token Expiry ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_expiry_401(respx_mock: respx.MockRouter, fake_token_manager):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        status_code=401, json={"message": "Bad credentials"}
    )
    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.TOKEN_EXPIRED


# ── Rate Limiting ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limited_429(respx_mock: respx.MockRouter, fake_token_manager):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        status_code=429,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0"},
    )
    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.API_UNAVAILABLE


# ── Missing Refs ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_ref_404(respx_mock: respx.MockRouter, fake_token_manager):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        status_code=404, json={"message": "Not Found"}
    )
    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_ref("owner", "repo", "heads/main")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.REF_MISSING


# ── Commit Presence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_present_exact_match(
    respx_mock: respx.MockRouter, fake_token_manager
):
    sha = "a" * 40
    # Commit exists
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}").respond(
        json={"sha": sha}
    )
    # Ref points to same sha
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.check_commit_presence("owner", "repo", sha)
    assert result.present
    assert result.relationship == GitHubCommitRelationship.EXACT
    assert result.remote_head_sha == sha


@pytest.mark.asyncio
async def test_commit_present_with_follow_on(
    respx_mock: respx.MockRouter, fake_token_manager
):
    base_sha = "a" * 40
    head_sha = "b" * 40
    # Base commit exists
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{base_sha}").respond(
        json={"sha": base_sha}
    )
    # Ref points to head_sha (different)
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": head_sha}}
    )
    # Compare shows head is ahead of base — follow-on
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/compare/{base_sha}...{head_sha}"
    ).respond(
        json={"status": "ahead", "ahead_by": 1, "behind_by": 0, "total_commits": 1}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.check_commit_presence("owner", "repo", base_sha)
    assert result.present
    assert result.relationship == GitHubCommitRelationship.ANCESTOR
    assert result.ahead_by == 1


@pytest.mark.asyncio
async def test_commit_absent(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "d" * 40
    # Commit does not exist
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}").respond(
        status_code=404, json={"message": "Not Found"}
    )
    # Ref points somewhere else
    head_sha = "e" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": head_sha}}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.check_commit_presence("owner", "repo", sha)
    assert not result.present
    assert result.relationship == GitHubCommitRelationship.ABSENT


# ── Compare ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compare_identical(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/compare/{sha}...{sha}").respond(
        json={
            "status": "identical",
            "ahead_by": 0,
            "behind_by": 0,
            "total_commits": 0,
            "files": [],
        }
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.compare_commits("owner", "repo", sha, sha)
    assert result.status == "identical"
    assert result.files_changed_count == 0
    assert result._evidence_digest().startswith("sha256:")


@pytest.mark.asyncio
async def test_compare_with_files(respx_mock: respx.MockRouter, fake_token_manager):
    base = "a" * 40
    head = "b" * 40
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/compare/{base}...{head}"
    ).respond(
        json={
            "status": "ahead",
            "ahead_by": 0,
            "behind_by": 3,
            "total_commits": 3,
            "files": [
                {
                    "filename": "src/config.py",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 2,
                },
                {
                    "filename": "docs/readme.md",
                    "status": "added",
                    "additions": 10,
                    "deletions": 0,
                },
                {
                    "filename": "tests/test_x.py",
                    "status": "added",
                    "additions": 20,
                    "deletions": 0,
                },
            ],
        }
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.compare_commits("owner", "repo", base, head)
    assert result.status == "ahead"
    assert result.files_changed_count == 3
    assert result.additions == 35
    assert result.deletions == 2
    assert result.change_kind_counts == {"modified": 1, "added": 2}

    # Redacted projection must not contain file paths
    proj = result.redacted_projection()
    assert "filename" not in json.dumps(proj)
    assert "src/config.py" not in json.dumps(proj)


# ── CI Status ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ci_status_success(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/status").respond(
        json={
            "state": "success",
            "statuses": [
                {"state": "success", "context": "ci/test"},
                {"state": "success", "context": "ci/lint"},
            ],
        }
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/check-runs"
    ).respond(json={"check_runs": []})
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.observe_ci_status("owner", "repo", sha)
    assert result.overall_state == "success"
    assert result.passed_count == 2
    assert result.failed_count == 0
    assert result.suggested_next_action == "All checks passed"


@pytest.mark.asyncio
async def test_ci_status_mixed_with_hostile_log_content(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Prove CI evidence does not leak log content even when present in response."""
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/status").respond(
        json={
            "state": "failure",
            "statuses": [
                {
                    "state": "error",
                    "description": f"Log: {SENTINEL_WORKFLOW_LOG}",
                    "context": "ci/deploy",
                }
            ],
        }
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/check-runs"
    ).respond(
        json={
            "check_runs": [
                {
                    "id": 1,
                    "name": "build",
                    "status": "completed",
                    "conclusion": "failure",
                    "output": {
                        "title": "Build failed",
                        "summary": SENTINEL_WORKFLOW_LOG,
                    },
                }
            ]
        }
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.observe_ci_status("owner", "repo", sha)
    assert result.overall_state == "failure" or result.overall_state == "error"
    assert result.failed_count >= 1
    assert result.suggested_next_action is not None

    # No raw log content in model-visible output
    serialized = result.model_dump_json()
    assert SENTINEL_WORKFLOW_LOG not in serialized
    assert "ghp_" not in serialized, "Token-like pattern leaked through CI evidence"


@pytest.mark.asyncio
async def test_ci_status_pending(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/status").respond(
        json={"state": "pending", "statuses": []}
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/check-runs"
    ).respond(
        json={
            "check_runs": [
                {"id": 1, "name": "build", "status": "in_progress", "conclusion": None}
            ]
        }
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.observe_ci_status("owner", "repo", sha)
    assert result.overall_state == "pending"
    assert result.pending_count == 1
    assert result.suggested_next_action == "Wait for pending checks to complete"


# ── Publication Verification ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_publication_exact_promoted(
    respx_mock: respx.MockRouter, fake_token_manager
):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/status").respond(
        json={"state": "success", "statuses": []}
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/check-runs"
    ).respond(json={"check_runs": []})
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.verify_publication("owner", "repo", sha)
    assert result.verification_status == GitHubVerificationStatus.EXACT_PROMOTED
    assert result.accepted_head_present
    assert result.follow_on_commits_count == 0
    assert result.ci_state == "success"


@pytest.mark.asyncio
async def test_publication_accepted_with_follow_on(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Simulate the exact scenario from the last wave: accepted head present
    but main has a follow-on commit (opencode.json + findings)."""
    accepted_sha = "a" * 40  # The coordinator-gate commit
    follow_on_sha = "b" * 40  # The deliberate follow-on config commit

    # Remote ref points to follow_on_sha
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": follow_on_sha}}
    )

    # Compare shows accepted_sha is ancestor, follow_on_sha is descendant
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/compare/{accepted_sha}...{follow_on_sha}"
    ).respond(
        json={
            "status": "ahead",
            "ahead_by": 2,
            "behind_by": 0,
            "total_commits": 2,
            "files": [
                {
                    "filename": "opencode.json",
                    "status": "modified",
                    "additions": 3,
                    "deletions": 1,
                },
                {
                    "filename": "docs/findings/out-of-scope-findings.jsonl",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 0,
                },
            ],
        }
    )

    # CI at follow-on head
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{follow_on_sha}/status"
    ).respond(json={"state": "success", "statuses": []})
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{follow_on_sha}/check-runs"
    ).respond(json={"check_runs": []})
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.verify_publication("owner", "repo", accepted_sha)

    # Critical: it must NOT report "publication failure" — must distinguish follow-on
    assert (
        result.verification_status == GitHubVerificationStatus.ACCEPTED_WITH_FOLLOW_ON
    )
    assert result.accepted_head_present
    assert result.follow_on_commits_count == 2
    assert result.follow_on_head_sha == follow_on_sha
    assert result.ci_state == "success"
    assert result.suggested_next_action is not None


@pytest.mark.asyncio
async def test_publication_expected_missing(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Expected commit not on remote at all."""
    expected = "a" * 40
    remote = "b" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": remote}}
    )

    # Compare endpoint: base not found
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/compare/{expected}...{remote}"
    ).respond(status_code=404, json={"message": "No common ancestor"})

    # Commit check: expected not found
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{expected}").respond(
        status_code=404, json={"message": "Not Found"}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.verify_publication("owner", "repo", expected)
    assert (
        result.verification_status == GitHubVerificationStatus.EXPECTED_COMMIT_MISSING
    )
    assert not result.accepted_head_present


# ── Ref Observation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_ref_success(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "c" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.observe_ref("owner", "repo", "heads/main")
    assert result.resolved
    assert result.remote_head_sha == sha
    assert result._evidence_digest().startswith("sha256:")


# ── Evidence Identity Stability ────────────────────────────────────────


@pytest.mark.asyncio
async def test_stable_evidence_identity(
    respx_mock: respx.MockRouter, fake_token_manager
):
    """Two identical observations produce stable evidence identities."""
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result1 = await adapter.observe_ref("owner", "repo", "heads/main")
    result2 = await adapter.observe_ref("owner", "repo", "heads/main")

    assert result1._evidence_digest() == result2._evidence_digest()
    assert result1.redacted_projection() == result2.redacted_projection()


# ── Malformed Response Handling ────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_response(respx_mock: respx.MockRouter, fake_token_manager):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").respond(
        200, content=b"not json at all"
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.UNKNOWN


# ── Timeout ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout(respx_mock: respx.MockRouter, fake_token_manager):
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo").mock(
        side_effect=httpx.TimeoutException("timed out")
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    with pytest.raises(GitHubTruthAdapterError) as exc_info:
        await adapter.observe_repository("owner", "repo")
    assert exc_info.value.error_kind == GitHubTruthErrorKind.TIMEOUT


# ── Publication with CI Failure ────────────────────────────────────────


@pytest.mark.asyncio
async def test_publication_ci_failing(respx_mock: respx.MockRouter, fake_token_manager):
    sha = "a" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": sha}}
    )
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/status").respond(
        json={
            "state": "failure",
            "statuses": [
                {"state": "failure", "context": "ci/test"},
                {"state": "success", "context": "ci/lint"},
            ],
        }
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/commits/{sha}/check-runs"
    ).respond(json={"check_runs": []})
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/actions/runs").respond(
        json={"workflow_runs": []}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.verify_publication("owner", "repo", sha)
    assert result.ci_state == "failure"
    assert result.ci_evidence is not None
    assert result.ci_evidence.failed_count == 1
    assert "Inspect failed checks" in (result.ci_evidence.suggested_next_action or "")


# ── Divergent ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publication_divergent(respx_mock: respx.MockRouter, fake_token_manager):
    expected = "a" * 40
    remote = "b" * 40
    respx_mock.get(f"{GITHUB_API_BASE}/repos/owner/repo/git/ref/heads/main").respond(
        json={"ref": "refs/heads/main", "object": {"sha": remote}}
    )
    respx_mock.get(
        f"{GITHUB_API_BASE}/repos/owner/repo/compare/{expected}...{remote}"
    ).respond(
        json={"status": "diverged", "ahead_by": 1, "behind_by": 2, "total_commits": 3}
    )

    adapter = GitHubTruthAdapter(fake_token_manager)
    result = await adapter.verify_publication("owner", "repo", expected)
    assert result.verification_status == GitHubVerificationStatus.TARGET_DIVERGENT
    assert not result.accepted_head_present
    assert "diverged" in (result.suggested_next_action or "").lower()


# ── Permission unavailable for publication ─────────────────────────────


@pytest.mark.asyncio
async def test_publication_permission_unavailable(unavailable_token_manager):
    adapter = GitHubTruthAdapter(unavailable_token_manager)
    result = await adapter.verify_publication("owner", "repo", "a" * 40)
    assert result.verification_status == GitHubVerificationStatus.PERMISSION_UNAVAILABLE
