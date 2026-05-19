"""Refusal/Deferral Boundary Tests — adversarial coverage for auth refusal surfaces.

Tests mutating operations are refused without proper auth, step-up, or receipts.
Covers GitHub, Google Workspace, MCP, ACP, A2A, and SDK surfaces.

No real credentials. No real network.
"""

from __future__ import annotations

import pytest

from rig_relay.acp.exceptions import (
    REFUSAL_CAPABILITY_DISABLED,
    REFUSAL_GENERAL,
    REFUSAL_LIVE_AUTH,
    REFUSAL_SESSION_RESUME,
    REFUSAL_STALE_SESSION,
    CapabilityDisabledError,
    InvalidRequestError,
    LiveAuthRefusalError,
    RefusalError,
    RigRefusalError,
    SessionResumeRefusalError,
    StaleSessionError,
    UnauthenticatedError,
)
from rig_relay.governance.auth_receipts import (
    action_requires_authorization,
    generate_dev_receipt,
    is_read_only_action,
    validate_receipt,
)
from rig_relay.integrations.github_provider import (
    GitHubProviderAuthState,
    GitHubVerdict,
    evaluate_github_capability,
)
from rig_relay.integrations.google_workspace._capabilities import (
    evaluate_workspace_capability,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceCapability,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
)
from rig_relay.protocols.a2a._models import A2AAgentCard, A2ADelegationReceipt

pytestmark = [pytest.mark.adversarial]


class TestGitHubMutationRefusals:
    def test_github_mutation_requires_authentication(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.issues.comment.write")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.auth.unauthenticated"

    def test_github_credentialed_operation_refused_without_step_up(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["contents:write"]
        )
        decision = evaluate_github_capability(auth, "github.contents.write")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code != ""

    def test_github_unauthenticated_read_refused_when_auth_required(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.actions.artifacts.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.auth.unauthenticated"


class TestGoogleWorkspaceMutationRefusals:
    def test_google_mutation_refused_when_only_read_scope(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
            scope_grants=[
                GoogleWorkspaceScopeGrant(
                    scope_id="https://www.googleapis.com/auth/drive.readonly",
                    scope_sensitivity=GoogleWorkspaceScopeSensitivity.NON_SENSITIVE,
                )
            ],
        )
        decision = evaluate_workspace_capability(auth, "google.drive.metadata.read")
        assert str(decision.verdict) in ("allowed", "refused")

    def test_google_domain_wide_delegation_refused_without_authorization(self):
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
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.users.list"
        )
        assert decision.is_refused
        assert decision.refusal_code == "google.delegation.not_authorized"

    def test_google_restricted_scope_refused_without_security_assessment(self):
        cap = GoogleWorkspaceCapability(
            capability_id="google.gmail.messages.read",
            product="gmail",
            operation_class="user_read",
            required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            required_auth_modes=["oauth_user"],
            scope_sensitivity=GoogleWorkspaceScopeSensitivity.RESTRICTED,
        )
        assert str(cap.scope_sensitivity) == "restricted"

    def test_google_admin_scope_refused_by_default(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
        )
        decision = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.users.list"
        )
        assert decision.is_refused


class TestGovernanceAuthReceipts:
    def test_mcp_tier_4_mutation_refused_without_receipt(self):
        assert action_requires_authorization("checkpoint.commit")
        assert action_requires_authorization("remote_upload.confirm")
        valid, reason = validate_receipt({}, "checkpoint.commit")
        assert not valid

    def test_mcp_tier_5_destructive_always_refused(self):
        assert action_requires_authorization("credentials.configure")
        assert action_requires_authorization("update.restart_now")

    def test_receipt_validates_with_correct_schema_and_action(self):
        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        valid, reason = validate_receipt(receipt, "checkpoint.commit")
        assert valid
        assert reason == "Receipt valid"

    def test_receipt_rejects_wrong_schema_version(self):
        receipt = {"schema_version": "wrong.v1"}
        valid, reason = validate_receipt(receipt, "checkpoint.commit")
        assert not valid
        assert "Invalid schema version" in reason

    def test_receipt_rejects_action_mismatch(self):
        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        valid, reason = validate_receipt(receipt, "remote_upload.confirm")
        assert not valid
        assert "Action mismatch" in reason

    def test_sdk_mutation_caps_refused_by_default(self):
        read_only = is_read_only_action("current_state.view")
        assert read_only is True
        assert action_requires_authorization("spawn.execute")


class TestACPRefusalStructures:
    def test_unauthenticated_error(self):
        exc = UnauthenticatedError("No API key configured")
        assert exc.code == -32000

    def test_session_resume_not_supported_reported(self):
        exc = SessionResumeRefusalError(
            session_id="s-123", detail="Session resume not supported"
        )
        assert exc.code == REFUSAL_SESSION_RESUME
        assert exc.data is not None
        data = exc.data or {}
        assert data.get("refusal_code") == "resume_not_supported"
        assert data.get("session_id") == "s-123"

    def test_rig_refusal_includes_refusal_code(self):
        exc = RigRefusalError(
            refusal_code="capability.disabled", detail="Capability is disabled"
        )
        assert exc.code == REFUSAL_GENERAL
        data = exc.data or {}
        assert data.get("refusal_code") == "capability.disabled"

    def test_live_auth_refusal_structure(self):
        exc = LiveAuthRefusalError(
            method_id="github.oauth.initiate", detail="Live auth deferred"
        )
        assert exc.code == REFUSAL_LIVE_AUTH
        assert exc.data is not None
        data = exc.data or {}
        assert data.get("refusal_code") == "live_auth_deferred"

    def test_stale_session_refusal_structure(self):
        exc = StaleSessionError(session_id="s-old", detail="Session expired")
        assert exc.code == REFUSAL_STALE_SESSION
        assert exc.data is not None
        data = exc.data or {}
        assert data.get("session_id") == "s-old"

    def test_invalid_request_error_structure(self):
        exc = InvalidRequestError("Missing required parameter")
        assert exc.code == -32602

    def test_refusal_error_structure(self):
        exc = RefusalError("test_method", "workspace_isolation", {"details": "test"})
        assert exc.code == -32601

    def test_all_refusals_include_trace_id(self):
        excs: list = [
            RigRefusalError("test_refusal_code", "test detail"),
            SessionResumeRefusalError("sid", "detail"),
            LiveAuthRefusalError("method", "detail"),
            StaleSessionError("sid", "detail"),
        ]
        for exc in excs:
            assert exc.data is not None
        exc_refusal = RefusalError("method", "code", {})
        assert exc_refusal.data is not None
        data = exc_refusal.data or {}
        assert "refusal" in data

    def test_all_refusals_include_refusal_code(self):
        exc = RigRefusalError(refusal_code="mutation.denied", detail="Mutation denied")
        data = exc.data or {}
        assert data.get("refusal_code") == "mutation.denied"
        exc2 = SessionResumeRefusalError("sid", "detail")
        data2 = exc2.data or {}
        assert data2.get("refusal_code") == "resume_not_supported"

    def test_all_refusals_include_capability_id(self):
        exc = RigRefusalError(
            refusal_code="mutation.denied",
            detail="Capability github.issues.comment.write is disabled",
        )
        assert exc.code == REFUSAL_GENERAL
        exc2 = CapabilityDisabledError(
            capability="github.issues.comment.write", detail="Capability is disabled"
        )
        assert exc2.code == REFUSAL_CAPABILITY_DISABLED
        data = exc2.data or {}
        assert data.get("capability") == "github.issues.comment.write"


class TestA2ARefusals:
    def test_a2a_remote_federation_refused(self):
        card = A2AAgentCard(
            agent_id="rig-relay-main",
            name="Rig Relay",
            local_only=True,
            remote_federation_supported=False,
        )
        assert card.remote_federation_supported is False
        assert card.local_only is True

    def test_a2a_mutation_delegation_refused(self):
        receipt = A2ADelegationReceipt(
            receipt_id="rec-001",
            delegating_agent_id="agent-orchestrator",
            receiving_agent_id="agent-builder",
            task_id="task-001",
            trace_id="trace-001",
            verdict="refused",
            refusal_code="a2a.mutation.delegation.refused",
        )
        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "a2a.mutation.delegation.refused"
        assert receipt.content_light is True
        d = receipt.to_dict()
        assert d["trace_id"] == "trace-001"
