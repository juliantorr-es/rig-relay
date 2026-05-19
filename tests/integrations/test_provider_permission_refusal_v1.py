from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rig_relay.integrations.github_provider._live_adapter import (
    _check_required_scopes,
    run_live_read_operation,
)
from rig_relay.integrations.github_provider._models import (
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubProviderAuthState,
    GitHubTokenStorageAuthority,
    GitHubVerdict,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier
from rig_relay.integrations.google_workspace._capabilities import (
    evaluate_workspace_capability,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
    GoogleWorkspaceVerdict,
)

pytestmark = [pytest.mark.asyncio]


class TestGitHubPermissionRefusal:
    async def test_missing_contents_read_scope_refused(self) -> None:
        """Repo metadata read requires repo or public_repo scope."""
        token = "ghp_test_refusal_scope"
        with patch(
            "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
            AsyncMock(return_value=["read:user", "user:email"]),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=token,
                repository_owner="example",
                repository_name="test",
            )
        assert result["verdict"] == "refused"
        assert result.get("refusal_code") == "github.scope.insufficient"

    async def test_repo_not_in_grant_refused(self) -> None:
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.PAT_MANUAL_IMPORT,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scopes_or_permissions=[],
            repository_access_hashes=[hash_identifier("other/repo")],
            token_storage_authority=GitHubTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
            token_material_present=True,
        )
        from rig_relay.integrations.github_provider._capabilities import (
            evaluate_github_capability,
        )

        decision = evaluate_github_capability(
            auth,
            "github.repo.issues.read",
            target_repository_hash=hash_identifier("unlisted/repo"),
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code in {
            "github.permission.missing",
            "github.repository.access_denied",
        }

    async def test_actions_permission_missing_refused(self) -> None:
        token = "ghp_test_actions_refusal"
        with patch(
            "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
            AsyncMock(return_value=["repo"]),
        ):
            result = await run_live_read_operation(
                capability_id="github.actions.runs.read",
                token=token,
                repository_owner="example",
                repository_name="test",
            )
        assert result["verdict"] == "refused"
        assert result.get("refusal_code") in {
            "github.scope.insufficient",
            "github.permission.missing",
        }

    async def test_private_repo_read_without_repo_scope_refused(self) -> None:
        token = "ghp_test_public_only"
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.PAT_MANUAL_IMPORT,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash=hash_identifier(token),
            scopes_or_permissions=["public_repo", "read:user"],
            repository_access_hashes=[hash_identifier("private-org/secret-repo")],
            token_storage_authority=GitHubTokenStorageAuthority.USER_SUPPLIED_RUNTIME,
            token_material_present=True,
        )
        from rig_relay.integrations.github_provider._capabilities import (
            evaluate_github_capability,
        )

        decision = evaluate_github_capability(
            auth,
            "github.repo.contents.read",
            target_repository_hash=hash_identifier("private-org/secret-repo"),
        )
        assert decision.verdict == GitHubVerdict.ALLOWED
        assert decision.refusal_code == ""

    async def test_scope_probe_http_error_yields_failure(self) -> None:
        token = "ghp_test_probe_fail"
        with patch(
            "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.metadata.read",
                token=token,
                repository_owner="example",
                repository_name="test",
            )
        assert result["verdict"] == "failed"
        assert "error" in result

    async def test_scope_check_returns_insufficient_for_empty_scopes(self) -> None:
        refusal = _check_required_scopes("github.actions.runs.read", [])
        assert refusal != ""
        assert "github.scope.insufficient" not in refusal

        refusal2 = _check_required_scopes("github.repo.metadata.read", ["read:user"])
        assert refusal2 != ""

    async def test_unknown_capability_yields_error_result(self) -> None:
        token = "ghp_test_unknown"
        with patch(
            "rig_relay.integrations.github_provider._live_adapter._probe_github_token_scopes",
            AsyncMock(return_value=["repo"]),
        ):
            result = await run_live_read_operation(
                capability_id="github.repo.secrets.read",
                token=token,
                repository_owner="example",
                repository_name="test",
            )
        assert result["verdict"] == "refused"
        assert result.get("refusal_code") == "github.capability.no_live_path"


class TestGoogleWorkspacePermissionRefusal:
    async def test_missing_gmail_scope_refused(self) -> None:
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/calendar.readonly",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.NON_SENSITIVE,
                )
            ],
            token_material_present=True,
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.gmail.labels.list"
        )
        assert decision.refusal_code == "google.scope.missing"

    async def test_restricted_drive_scope_flagged(self) -> None:
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/drive.readonly",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.RESTRICTED,
                )
            ],
            token_material_present=True,
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.drive.files.list"
        )
        assert (
            decision.refusal_code
            == "google.scope.restricted_security_assessment_required"
        )

    async def test_admin_directory_refused_without_domain_delegation(self) -> None:
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.SERVICE_ACCOUNT_DOMAIN_WIDE_DELEGATION,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            domain_wide_delegation_authorized=False,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/admin.directory.user.readonly",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.SENSITIVE,
                )
            ],
            token_material_present=True,
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.users.list"
        )
        assert decision.refusal_code == "google.delegation.not_authorized"

    async def test_overbroad_scope_flagged(self) -> None:
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/drive",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.RESTRICTED,
                )
            ],
            token_material_present=True,
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.drive.files.list"
        )
        assert decision.verdict == GoogleWorkspaceVerdict.REFUSED
        assert decision.refusal_code != ""

    async def test_unauthenticated_gmail_profile_refused(self) -> None:
        auth = GoogleWorkspaceAuthState()
        decision = evaluate_workspace_capability(
            auth, "google_workspace.gmail.profile.get"
        )
        assert decision.verdict == GoogleWorkspaceVerdict.REFUSED
        assert decision.refusal_code != ""
        assert decision.refusal_code in {
            "google.auth.unauthenticated",
            "google.scope.restricted_security_assessment_required",
        }
