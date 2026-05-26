"""Operator evidence projection tests — content-light, no secrets, progressive disclosure.

Proves that operator dashboard projections never contain raw tokens, secrets,
private paths, or unredacted metadata. Tests all projection models and the
dashboard builder.
"""

from __future__ import annotations

import json

from rig_relay.desktop.github_truth_projection import (
    _STATUS_LABELS,
    CIStateProjection,
    GitHubConnectionProjection,
    PublicationStatusProjection,
    RepositoryProjection,
    assert_projection_content_light,
    build_operator_dashboard,
)
from rig_relay.integrations.github_provider._truth_models import (
    GitHubCIStatusEvidence,
    GitHubInstallationAccess,
    GitHubPublicationVerification,
    GitHubRepositoryIdentity,
    GitHubTokenStatus,
    GitHubVerificationStatus,
)

SENTINEL_GHP_TOKEN = "ghp_SentinelTokenThatShouldNeverAppearInEvidence1a2b3c4d5e6f7g8h"
SENTINEL_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpASentinelThatShouldNeverLeak\n-----END RSA PRIVATE KEY-----"


def _install_access(token_status: str = GitHubTokenStatus.AVAILABLE):
    return GitHubInstallationAccess(
        installation_hash="abc",
        app_id=123,
        installation_id_hash="def",
        token_status=token_status,
        token_expires_in_seconds=3000,
        granted_permissions=["contents:read", "metadata:read"],
        granted_repository_hashes=["repo_hash_1"],
    )


def _publication_verification():
    return GitHubPublicationVerification(
        repository_hash="repo_hash",
        expected_sha="a" * 40,
        ref="main",
        verification_status=GitHubVerificationStatus.ACCEPTED_WITH_FOLLOW_ON,
        remote_head_sha="b" * 40,
        accepted_head_present=True,
        follow_on_commits_count=2,
        follow_on_head_sha="b" * 40,
        ci_state="success",
        ci_evidence=GitHubCIStatusEvidence(
            repository_hash="repo_hash",
            commit_sha="b" * 40,
            overall_state="success",
            passed_count=5,
            failed_count=0,
            pending_count=0,
            total_count=5,
            suggested_next_action="All checks passed",
        ),
        suggested_next_action="Follow-on commits present; review changes",
    )


def _repository():
    return GitHubRepositoryIdentity(
        owner="owner",
        repo="repo",
        repository_hash="repo_hash",
        visibility="public",
        default_branch="main",
    )


# ── Connection Projection ──────────────────────────────────────────────


def test_connection_projection_available():
    access = _install_access()
    proj = GitHubConnectionProjection.from_installation_access(access)
    assert proj.connected
    assert proj.token_status == "available"
    assert proj.token_expires_in_seconds == 3000
    assert proj.permissions_granted_count == 2
    assert proj.app_id == 123
    assert proj.evidence_digest is not None
    assert proj.evidence_digest.startswith("sha256:")


def test_connection_projection_expired():
    access = _install_access(token_status=GitHubTokenStatus.EXPIRED)
    proj = GitHubConnectionProjection.from_installation_access(access)
    assert not proj.connected
    assert proj.token_status == "expired"


def test_connection_projection_no_tokens():
    proj = GitHubConnectionProjection.from_installation_access(_install_access())
    serialized = proj.model_dump_json()
    assert "token" not in serialized.lower() or "token_status" in serialized
    assert SENTINEL_GHP_TOKEN not in serialized
    assert SENTINEL_PRIVATE_KEY not in serialized


# ── Publication Projection ─────────────────────────────────────────────


def test_publication_projection_follow_on():
    ver = _publication_verification()
    proj = PublicationStatusProjection.from_verification(ver)
    assert proj.verification_status == "accepted_with_follow_on_commits"
    assert "follow-on" in proj.status_label
    assert proj.accepted_head_present
    assert proj.follow_on_commits_count == 2
    assert proj.ci_state == "success"
    assert proj.suggested_next_action is not None


def test_publication_projection_all_labels():
    for status, label in _STATUS_LABELS.items():
        ver = GitHubPublicationVerification(
            repository_hash="rh",
            expected_sha="a" * 40,
            verification_status=status,
            remote_head_sha="b" * 40,
            accepted_head_present=status == "exact_promoted",
        )
        proj = PublicationStatusProjection.from_verification(ver)
        assert proj.status_label == label


# ── CI State Projection ────────────────────────────────────────────────


def test_ci_projection():
    ci = CIStateProjection(
        overall_state="failure",
        passed=3,
        failed=2,
        pending=0,
        total=5,
        suggested_next_action="Inspect failed checks",
    )
    assert ci.state_label == "Checks failing"
    assert ci.failed == 2
    assert ci.passed == 3


# ── Repository Projection ──────────────────────────────────────────────


def test_repository_projection():
    repo = _repository()
    proj = RepositoryProjection.from_identity(repo)
    assert proj.repository_hash == "repo_hash"
    assert proj.visibility == "public"
    assert proj.default_branch_available is True
    assert proj.evidence_digest is not None


def test_repository_projection_no_raw_branch():
    """Default branch value must not appear raw in projection."""
    repo = GitHubRepositoryIdentity(
        owner="o",
        repo="r",
        repository_hash="rh",
        default_branch=f"secret-{SENTINEL_GHP_TOKEN[:10]}",
    )
    proj = RepositoryProjection.from_identity(repo)
    serialized = proj.model_dump_json()
    assert SENTINEL_GHP_TOKEN[:10] not in serialized


# ── Dashboard Builder ──────────────────────────────────────────────────


def test_dashboard_builds_complete():
    dashboard = build_operator_dashboard(
        installation_access=_install_access(),
        publication=_publication_verification(),
        repository=_repository(),
        pending_authorizations=["native_validate_sandbox", "disclosure_authority"],
        parked_dependencies=[
            "Lane A: disclosure authorization",
            "Lane C: ACP protocol",
        ],
    )

    assert dashboard.connection.connected
    assert dashboard.publication is not None
    assert (
        dashboard.publication.verification_status == "accepted_with_follow_on_commits"
    )
    assert dashboard.repository is not None
    assert dashboard.ci is not None
    assert dashboard.ci.passed == 5
    assert dashboard.ci.failed == 0
    assert len(dashboard.pending_authorizations) == 2
    assert len(dashboard.parked_dependencies) == 2
    assert dashboard.dashboard_digest is not None
    assert dashboard.dashboard_digest.startswith("sha256:")


def test_dashboard_no_secrets():
    dashboard = build_operator_dashboard(
        installation_access=_install_access(), publication=_publication_verification()
    )
    serialized = dashboard.model_dump_json()
    assert SENTINEL_GHP_TOKEN not in serialized
    assert SENTINEL_PRIVATE_KEY not in serialized
    assert "-----BEGIN" not in serialized
    assert "ghp_" not in serialized


def test_dashboard_content_light_assertion():
    dashboard = build_operator_dashboard(installation_access=_install_access())
    assert_projection_content_light(dashboard)


def test_dashboard_minimal():
    dashboard = build_operator_dashboard()
    assert dashboard.connection.connected is False
    assert dashboard.publication is None
    assert dashboard.repository is None
    assert dashboard.dashboard_digest is not None


def test_dashboard_digest_stable():
    """Same evidence produces stable dashboard digest."""
    d1 = build_operator_dashboard(installation_access=_install_access())
    d2 = build_operator_dashboard(installation_access=_install_access())
    assert d1.dashboard_digest == d2.dashboard_digest


def test_dashboard_digest_changes_with_state():
    """Different evidence produces different dashboard digest."""
    d1 = build_operator_dashboard(
        installation_access=_install_access(GitHubTokenStatus.AVAILABLE)
    )
    d2 = build_operator_dashboard(
        installation_access=_install_access(GitHubTokenStatus.EXPIRED)
    )
    assert d1.dashboard_digest != d2.dashboard_digest


def test_projection_serializes_to_json():
    dashboard = build_operator_dashboard(
        installation_access=_install_access(), publication=_publication_verification()
    )
    dumped = dashboard.model_dump()
    json_str = json.dumps(dumped, sort_keys=True)
    parsed = json.loads(json_str)
    assert parsed["schema_version"] == "rig.relay.github_operator_projection.v1"
    assert parsed["connection"]["connected"] is True
