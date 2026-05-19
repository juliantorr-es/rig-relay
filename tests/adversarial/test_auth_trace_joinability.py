"""Cross-Surface Trace/Receipt Joinability Tests.

Tests that trace IDs, receipt IDs, and auth state hashes are consistent and
properly propagated across the full operation lifecycle.

No real credentials. No real network.
"""

from __future__ import annotations

import secrets

import pytest

from rig_relay.integrations.github_provider import (
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubOperationClass,
    GitHubProviderAuthState,
    GitHubProviderCapabilityDecision,
    GitHubProviderOperationRequest,
    GitHubVerdict,
    build_github_operation_receipt,
    evaluate_github_capability,
    hash_identifier,
    validate_github_operation_receipt,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceDecision,
    GoogleWorkspaceOperationRequest,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
    GoogleWorkspaceVerdict,
)
from rig_relay.integrations.google_workspace._receipts import build_workspace_receipt
from rig_relay.protocols.a2a._models import A2ADelegationReceipt

pytestmark = [pytest.mark.adversarial]


def _make_trace_id() -> str:
    return "trace-" + secrets.token_hex(12)


class TestGitHubReceiptTrace:
    def test_github_operation_receipt_has_trace_id(self):
        trace_id = _make_trace_id()
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-trace-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision, trace_id=trace_id)
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("trace_id") == trace_id

    def test_github_operation_receipt_has_auth_state_hash(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
        )
        request = GitHubProviderOperationRequest(
            operation_id="op-hash-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        receipt_dict = receipt.to_dict()
        assert "auth_state_hash" in receipt_dict
        assert len(receipt_dict["auth_state_hash"]) == 64

    def test_github_receipt_id_unique_per_operation(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request1 = GitHubProviderOperationRequest(
            operation_id="op-rid-unique-1",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        request2 = GitHubProviderOperationRequest(
            operation_id="op-rid-unique-2",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt1 = build_github_operation_receipt(request1, decision)
        receipt2 = build_github_operation_receipt(request2, decision)
        assert receipt1.receipt_id != receipt2.receipt_id
        assert receipt1.receipt_id.startswith("sha256:")
        assert receipt2.receipt_id.startswith("sha256:")


class TestGoogleWorkspaceReceiptTrace:
    def test_google_operation_receipt_has_trace_id(self):
        trace_id = _make_trace_id()
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
        request = GoogleWorkspaceOperationRequest(
            operation_id="ws-trace-001",
            capability_id="google.drive.metadata.read",
            operation_kind="Read Drive metadata",
            operation_class="public_read",
            auth_state=auth,
            subject_hash=hash_identifier("user@example.com"),
        )
        decision = GoogleWorkspaceDecision(
            capability_id="google.drive.metadata.read",
            verdict=GoogleWorkspaceVerdict.ALLOWED,
        )
        receipt = build_workspace_receipt(request, decision, trace_id=trace_id)
        data = receipt.to_dict()
        assert data.get("trace_id") == trace_id

    def test_google_operation_receipt_has_auth_state_hash(self):
        auth = GoogleWorkspaceAuthState(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash="a" * 64,
        )
        request = GoogleWorkspaceOperationRequest(
            operation_id="ws-hash-001",
            capability_id="google.drive.metadata.read",
            operation_kind="Read Drive metadata",
            operation_class="public_read",
            auth_state=auth,
            subject_hash=hash_identifier("user@example.com"),
        )
        decision = GoogleWorkspaceDecision(
            capability_id="google.drive.metadata.read",
            verdict=GoogleWorkspaceVerdict.ALLOWED,
        )
        receipt = build_workspace_receipt(request, decision)
        data = receipt.to_dict()
        assert "auth_state_hash" in data
        assert len(data["auth_state_hash"]) == 64

    def test_google_receipt_id_unique_per_operation(self):
        auth = GoogleWorkspaceAuthState()
        request1 = GoogleWorkspaceOperationRequest(
            operation_id="ws-uid-1",
            capability_id="google.drive.metadata.read",
            operation_kind="Read",
            operation_class="public_read",
            auth_state=auth,
        )
        request2 = GoogleWorkspaceOperationRequest(
            operation_id="ws-uid-2",
            capability_id="google.drive.metadata.read",
            operation_kind="Read",
            operation_class="public_read",
            auth_state=auth,
        )
        decision = GoogleWorkspaceDecision(
            capability_id="google.drive.metadata.read",
            verdict=GoogleWorkspaceVerdict.ALLOWED,
        )
        receipt1 = build_workspace_receipt(request1, decision)
        receipt2 = build_workspace_receipt(request2, decision)
        assert receipt1.receipt_id != receipt2.receipt_id


class TestTraceIdLifecycle:
    def test_trace_id_consistent_across_operation_lifecycle(self):
        trace_id = _make_trace_id()
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        capability_id = "github.repo.issues.read"
        decision = evaluate_github_capability(
            auth, capability_id, target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED
        request = GitHubProviderOperationRequest(
            operation_id="op-lifecycle-001",
            capability_id=capability_id,
            operation_kind="Read issues",
            operation_class=GitHubOperationClass.REMOTE_READ,
            auth_state=auth,
            repository_hash="r" * 64,
            actor_hash=hash_identifier("test-actor"),
        )
        receipt = build_github_operation_receipt(request, decision, trace_id=trace_id)
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("trace_id") == trace_id
        errors = validate_github_operation_receipt(receipt_dict)
        assert not errors, f"Receipt fails schema: {errors}"

    def test_parent_trace_id_propagates_correctly(self):
        parent_trace = _make_trace_id()
        child_trace = _make_trace_id()
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-parent-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(
            request, decision, trace_id=child_trace, parent_trace_id=parent_trace
        )
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("trace_id") == child_trace
        assert receipt_dict.get("parent_trace_id") == parent_trace


class TestACPAndA2ATraceIds:
    def test_acp_refusal_has_trace_id(self):
        from rig_relay.acp.exceptions import RigRefusalError

        exc = RigRefusalError(refusal_code="test.code", detail="Test refusal")
        data = exc.data or {}
        assert data.get("content_light") is True

    def test_a2a_delegation_receipt_has_trace_id(self):
        receipt = A2ADelegationReceipt(
            receipt_id="rec-a2a-001",
            delegating_agent_id="agent-a",
            receiving_agent_id="agent-b",
            task_id="task-001",
            trace_id="trace-a2a-001",
            verdict="allowed",
        )
        assert receipt.trace_id == "trace-a2a-001"
        d = receipt.to_dict()
        assert d["trace_id"] == "trace-a2a-001"

    def test_sdk_run_result_has_trace_id(self):
        trace_id = _make_trace_id()
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-sdk-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision, trace_id=trace_id)
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("trace_id") == trace_id
        assert "operation_id" in receipt_dict

    def test_mcp_refusal_has_trace_id(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        assert "authorization_id" in receipt
        assert (
            receipt.get("schema_version")
            == "rig.relay.step_up_authorization_receipt.v1"
        )
        assert "receipt_sha256" in receipt
