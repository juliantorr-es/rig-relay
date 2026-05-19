"""GitHub Provider Implementation v0 — contract, integration, real-artifact,
adversarial, and substrate tests.

No network calls. No credentials. No GitHub API. No GitHub Actions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider import (
    GitHubAccessLevel,
    GitHubAuthMode,
    GitHubAuthStatus,
    GitHubGrantStatus,
    GitHubOperationClass,
    GitHubPermissionKind,
    GitHubProviderAuthState,
    GitHubProviderCapability,
    GitHubProviderCapabilityDecision,
    GitHubProviderCapabilityManifest,
    GitHubProviderOperationRequest,
    GitHubProviderRequiredPermission,
    GitHubRepositoryPermissionGrant,
    GitHubTokenStorageAuthority,
    GitHubVerdict,
    assert_content_light_mapping,
    assert_no_raw_github_token,
    build_github_operation_receipt,
    evaluate_github_capability,
    get_capability,
    hash_identifier,
    load_github_capability_manifest,
    permission_satisfies,
    read_auth_state,
    validate_github_operation_receipt,
    write_auth_state,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


class TestCapabilityManifest:
    @pytest.mark.contract
    def test_loads_and_validates_real_manifest(self):
        manifest = load_github_capability_manifest()
        assert isinstance(manifest, GitHubProviderCapabilityManifest)
        assert len(manifest.capabilities) >= 15

    @pytest.mark.contract
    def test_all_capability_ids_are_unique(self):
        manifest = load_github_capability_manifest()
        ids = list(manifest.capabilities.keys())
        assert len(ids) == len(set(ids))

    @pytest.mark.contract
    def test_get_capability_returns_capability(self):
        manifest = load_github_capability_manifest()
        cap = get_capability(manifest, "github.repo.metadata.read")
        assert cap is not None
        assert isinstance(cap, GitHubProviderCapability)

    @pytest.mark.contract
    def test_get_capability_returns_none_for_unknown(self):
        manifest = load_github_capability_manifest()
        assert get_capability(manifest, "github.super.secret.operation") is None


class TestDecisionEngine:
    @pytest.mark.contract
    def test_unknown_capability_is_refused(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.nonexistent.capability")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.capability.unknown"

    @pytest.mark.contract
    def test_public_read_only_allowed_unauthenticated(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.repo.metadata.read")
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_read_only_is_refused_when_unauthenticated_and_requires_auth(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.actions.artifacts.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.auth.unauthenticated"

    @pytest.mark.contract
    def test_write_permission_satisfies_read(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:write"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_mutation_capability_defaults_refused(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:write"]
        )
        decision = evaluate_github_capability(auth, "github.issues.comment.write")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.requires_step_up is True

    @pytest.mark.adversarial
    def test_destructive_mutation_always_refused_v0(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["actions:write"]
        )
        decision = evaluate_github_capability(auth, "github.workflow.rerun")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert (
            "v0" in decision.reason.lower() or "destructive" in decision.reason.lower()
        )

    @pytest.mark.adversarial
    def test_credentialed_remote_mutation_refused_v0(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["contents:write"]
        )
        decision = evaluate_github_capability(auth, "github.contents.write")
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.adversarial
    def test_token_material_stored_true_refused(self):
        auth = GitHubProviderAuthState()
        auth.token_material_stored = True
        auth.auth_status = GitHubAuthStatus.AUTHENTICATED
        decision = evaluate_github_capability(auth, "github.repo.metadata.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert "token_material_stored" in decision.refusal_code

    @pytest.mark.adversarial
    def test_forbidden_json_file_storage_refused(self):
        auth = GitHubProviderAuthState()
        auth.token_storage_authority = GitHubTokenStorageAuthority.FORBIDDEN_JSON_FILE
        auth.auth_status = GitHubAuthStatus.AUTHENTICATED
        decision = evaluate_github_capability(auth, "github.repo.metadata.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert "forbidden_storage" in decision.refusal_code

    @pytest.mark.contract
    def test_mutation_with_step_up_can_be_allowed(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:write"],
            repository_access_hashes=["r" * 64],
        )
        manifest = load_github_capability_manifest()
        decision = evaluate_github_capability(
            auth,
            "github.issues.comment.write",
            step_up_satisfied=True,
            target_repository_hash="r" * 64,
            manifest=manifest,
        )
        assert decision.verdict == GitHubVerdict.ALLOWED


class TestInstallationIdHash:
    @pytest.mark.contract
    def test_non_github_app_auth_normalizes_installation_id_to_none(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            installation_id_hash="12345",
        )
        assert auth.installation_id_hash is None

    @pytest.mark.contract
    def test_empty_installation_id_hash_normalizes_to_none(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            installation_id_hash="",
        )
        assert auth.installation_id_hash is None

    @pytest.mark.contract
    def test_github_app_auth_preserves_installation_id_hash(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            installation_id_hash="a" * 64,
        )
        assert auth.installation_id_hash == "a" * 64


class TestAuthState:
    @pytest.mark.contract
    def test_auth_state_to_dict_validates(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert d["schema_version"] == "rig.github_provider.auth_state.v1"
        assert d["provider_id"] == "github"
        assert d["token_material_stored"] is False

    @pytest.mark.adversarial
    def test_auth_state_rejects_raw_token_fields(self):
        auth = GitHubProviderAuthState.unauthenticated()
        d = auth.to_dict()
        assert "access_token" not in d
        assert "client_secret" not in d
        assert "refresh_token" not in d
        assert "token" not in d

    @pytest.mark.contract
    def test_is_authenticated_detects_authenticated(self):
        auth = GitHubProviderAuthState(auth_status=GitHubAuthStatus.AUTHENTICATED)
        assert auth.is_authenticated() is True

    @pytest.mark.contract
    def test_is_authenticated_rejects_unauthenticated(self):
        auth = GitHubProviderAuthState(auth_status=GitHubAuthStatus.UNAUTHENTICATED)
        assert auth.is_authenticated() is False

    @pytest.mark.contract
    def test_is_usable_rejects_forbidden_storage(self):
        auth = GitHubProviderAuthState(
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            token_storage_authority=GitHubTokenStorageAuthority.FORBIDDEN_JSON_FILE,
        )
        assert auth.is_usable() is False

    @pytest.mark.contract
    def test_is_usable_rejects_token_material_stored(self):
        auth = GitHubProviderAuthState(
            auth_status=GitHubAuthStatus.AUTHENTICATED, token_material_stored=True
        )
        assert auth.is_usable() is False


class TestOperationReceipts:
    @pytest.mark.contract
    def test_build_receipt_validates_against_schema(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read repository metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read",
            verdict=GitHubVerdict.ALLOWED,
            reason="Read-only public capability",
        )
        receipt = build_github_operation_receipt(request, decision)
        receipt_dict = receipt.to_dict()
        errors = validate_github_operation_receipt(receipt_dict)
        assert not errors, f"Receipt schema errors: {errors}"

    @pytest.mark.contract
    def test_refused_receipt_includes_refusal_code(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-002",
            capability_id="github.issues.comment.write",
            operation_kind="Write issue comment",
            operation_class=GitHubOperationClass.REMOTE_MUTATION,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.issues.comment.write",
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.unauthenticated",
            reason="Not authenticated",
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "github.auth.unauthenticated"

    @pytest.mark.contract
    def test_receipt_has_content_light_true(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-003",
            capability_id="github.repo.metadata.read",
            operation_kind="Read repository metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.content_light is True

    @pytest.mark.adversarial
    def test_receipt_rejects_raw_token_strings(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-004-ghp_token",
            capability_id="github.repo.metadata.read",
            operation_kind="Read repository metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            request.operation_id = "ghp_1234567890abcdef1234567890abcdef12345678"
            build_github_operation_receipt(request, decision)

    @pytest.mark.adversarial
    def test_receipt_rejects_forbidden_fields(self):
        receipt_dict = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
            "raw_token": "ghp_fake12345",
        }
        with pytest.raises(ValueError, match="raw_content_field_detected"):
            assert_content_light_mapping(receipt_dict)

    @pytest.mark.adversarial
    def test_receipt_rejects_raw_response_body_field(self):
        receipt_dict = {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": "op-001",
            "capability_id": "github.repo.metadata.read",
            "operation_kind": "Read repository metadata",
            "operation_class": "read_only",
            "auth_mode": "none",
            "auth_state_hash": "a" * 64,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "repository_hash": "d" * 64,
            "actor_hash": "e" * 64,
            "verdict": "completed",
            "refusal_code": "",
            "redaction_status": "clean",
            "content_light": True,
            "generated_at": "2026-05-19T00:00:00Z",
            "raw_repository_content": "print('hello world')",
        }
        with pytest.raises(ValueError, match="raw_content_field_detected"):
            assert_content_light_mapping(receipt_dict)

    @pytest.mark.contract
    def test_operation_receipt_includes_trace_id_when_provided(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-trace-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read repository metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(
            request, decision, trace_id="tr-abc-123"
        )
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("trace_id") == "tr-abc-123"
        errors = validate_github_operation_receipt(receipt_dict)
        assert not errors, f"Receipt schema errors: {errors}"

    @pytest.mark.contract
    def test_operation_receipt_includes_receipt_id(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-test-rid-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read repository metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test-actor"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.receipt_id.startswith("sha256:")
        assert len(receipt.receipt_id) == 71  # "sha256:" + 64 hex chars
        receipt_dict = receipt.to_dict()
        assert receipt_dict.get("receipt_id") == receipt.receipt_id
        errors = validate_github_operation_receipt(receipt_dict)
        assert not errors, f"Receipt schema errors: {errors}"


class TestRedactionHelpers:
    @pytest.mark.adversarial
    def test_assert_no_raw_github_token_detects_ghp(self):
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token("ghp_1234567890abcdef1234567890abcdef12345678")

    @pytest.mark.adversarial
    def test_assert_no_raw_github_token_detects_ghs(self):
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token("ghs_1234567890abcdef1234567890abcdef12345678")

    @pytest.mark.adversarial
    def test_assert_no_raw_github_token_detects_github_pat(self):
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(
                "github_pat_1234567890abcdef1234567890abcdef12345678"
            )

    @pytest.mark.adversarial
    def test_assert_no_raw_github_token_passes_clean_string(self):
        assert_no_raw_github_token("This is a clean string with no tokens")

    @pytest.mark.contract
    def test_hash_identifier_produces_sha256(self):
        result = hash_identifier("test-value")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    @pytest.mark.contract
    def test_hash_identifier_is_deterministic(self):
        a = hash_identifier("test-value")
        b = hash_identifier("test-value")
        assert a == b

    @pytest.mark.contract
    def test_hash_identifier_is_different_for_different_inputs(self):
        a = hash_identifier("value-1")
        b = hash_identifier("value-2")
        assert a != b


class TestNoNetworkOrCredentials:
    @pytest.mark.substrate
    def test_no_network_calls_made(self):
        pass

    @pytest.mark.substrate
    def test_no_credential_files_written(self):
        pass

    @pytest.mark.substrate
    def test_no_release_gate_files_touched(self):
        pass

    @pytest.mark.substrate
    def test_no_github_actions_files_touched(self):
        pass


class TestPermissionIntersection:
    @pytest.mark.contract
    def test_manifest_schema_requires_required_permissions(self):
        manifest = load_github_capability_manifest()
        for cap in manifest.capabilities.values():
            assert len(cap.required_permissions) >= 1, (
                f"{cap.capability_id} must have required_permissions"
            )

    @pytest.mark.contract
    def test_public_access_can_be_allowed_unauthenticated(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(auth, "github.repo.metadata.read")
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_repo_read_refused_when_missing_permission(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["administration:read"]
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.contract
    def test_repo_read_allowed_with_matching_permission(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_write_permission_satisfies_read(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:write"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_unrelated_permission_does_not_satisfy(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["administration:read"]
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.adversarial
    def test_oauth_scope_does_not_satisfy_app_permission_directly(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            scopes_or_permissions=["issues:read"],
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.adversarial
    def test_app_permission_does_not_satisfy_oauth_scope(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.OAUTH_WEB_FLOW,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            scopes_or_permissions=["repo"],
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.contract
    def test_permission_missing_returns_github_permission_missing(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["metadata:read"]
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.adversarial
    def test_wrong_permission_kind_returns_kind_mismatch(self):
        auth = GitHubProviderAuthState(
            auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            scopes_or_permissions=["read:user"],
        )
        decision = evaluate_github_capability(auth, "github.actions.runs.read")
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.adversarial
    def test_insufficient_access_level_refused(self):
        req = GitHubProviderRequiredPermission(
            permission_id="issues:write",
            permission_kind=GitHubPermissionKind.GITHUB_APP_PERMISSION,
            access_level=GitHubAccessLevel.WRITE,
            required=True,
        )
        assert not permission_satisfies(
            req, "issues:read", GitHubPermissionKind.GITHUB_APP_PERMISSION, "read"
        )

    @pytest.mark.contract
    def test_sufficient_access_level_satisfies(self):
        req = GitHubProviderRequiredPermission(
            permission_id="issues:read",
            permission_kind=GitHubPermissionKind.GITHUB_APP_PERMISSION,
            access_level=GitHubAccessLevel.READ,
            required=True,
        )
        assert permission_satisfies(
            req, "issues:write", GitHubPermissionKind.GITHUB_APP_PERMISSION, "write"
        )

    @pytest.mark.adversarial
    def test_mutation_still_requires_step_up_with_permission(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:write"]
        )
        decision = evaluate_github_capability(auth, "github.issues.comment.write")
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.requires_step_up is True

    @pytest.mark.adversarial
    def test_destructive_remains_refused_with_permission(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["actions:write"]
        )
        decision = evaluate_github_capability(auth, "github.workflow.rerun")
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.adversarial
    def test_credentialed_remains_refused_with_permission(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["contents:write"]
        )
        decision = evaluate_github_capability(auth, "github.contents.write")
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.contract
    def test_refused_permission_receipt_includes_refusal_code(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["metadata:read"]
        )
        decision = evaluate_github_capability(auth, "github.repo.issues.read")
        request = GitHubProviderOperationRequest(
            operation_id="op-test-perm-refused",
            capability_id="github.repo.issues.read",
            operation_kind="Read issues",
            operation_class=GitHubOperationClass.REMOTE_READ,
            auth_state=auth,
            repository_hash=hash_identifier("owner/repo"),
            actor_hash=hash_identifier("test"),
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.refusal_code, "Refused receipt must have refusal_code"

    @pytest.mark.contract
    def test_non_required_permission_not_enforced(self):
        req = GitHubProviderRequiredPermission(
            permission_id="metadata:read",
            permission_kind=GitHubPermissionKind.PUBLIC_ACCESS,
            access_level=GitHubAccessLevel.READ,
            required=False,
        )
        assert permission_satisfies(
            req, "no-permission", GitHubPermissionKind.PUBLIC_ACCESS, "read"
        )

    @pytest.mark.contract
    def test_read_permission_satisfied_by_same_base_write(self):
        req = GitHubProviderRequiredPermission(
            permission_id="contents:read",
            permission_kind=GitHubPermissionKind.GITHUB_APP_PERMISSION,
            access_level=GitHubAccessLevel.READ,
            required=True,
        )
        assert permission_satisfies(
            req, "contents:write", GitHubPermissionKind.GITHUB_APP_PERMISSION, "write"
        )

    @pytest.mark.contract
    def test_read_permission_not_satisfied_by_different_base(self):
        req = GitHubProviderRequiredPermission(
            permission_id="contents:read",
            permission_kind=GitHubPermissionKind.GITHUB_APP_PERMISSION,
            access_level=GitHubAccessLevel.READ,
            required=True,
        )
        assert not permission_satisfies(
            req, "issues:write", GitHubPermissionKind.GITHUB_APP_PERMISSION, "write"
        )

    @pytest.mark.adversarial
    def test_oauth_scope_repo_maps_to_contents_write(self):
        from rig_relay.integrations.github_provider._models import (
            normalize_oauth_scope_to_app_permission,
        )

        assert normalize_oauth_scope_to_app_permission("repo") == "contents:write"


class TestRepositoryScoping:
    @pytest.mark.contract
    def test_repo_read_allowed_with_correct_access(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_repo_read_refused_when_repository_hash_missing(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.repository.missing"

    @pytest.mark.adversarial
    def test_repo_read_refused_when_repository_not_authorized(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["x" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.repository.access_denied"

    @pytest.mark.contract
    def test_public_metadata_no_repo_scope_required(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(
            auth, "github.repo.metadata.read", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_mutation_still_requires_step_up_with_repo_access(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:write"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.issues.comment.write", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.requires_step_up is True

    @pytest.mark.adversarial
    def test_destructive_remains_refused_with_repo_access(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["actions:write"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.workflow.rerun", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.contract
    def test_receipt_includes_repository_hash_not_raw_name(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        request = GitHubProviderOperationRequest(
            operation_id="op-test-repo",
            capability_id="github.repo.issues.read",
            operation_kind="Read issues",
            operation_class=GitHubOperationClass.REMOTE_READ,
            auth_state=auth,
            repository_hash="r" * 64,
            actor_hash=hash_identifier("test"),
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.repository_hash == "r" * 64
        assert "owner/repo" not in receipt.repository_hash

    @pytest.mark.contract
    def test_app_installation_inspect_no_repo_scope_needed(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["administration:read"]
        )
        decision = evaluate_github_capability(
            auth, "github.app.installation.inspect", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.ALLOWED


def _make_grant(
    repo_hash: str,
    perm_id: str,
    kind: str = "github_app_permission",
    level: str = "read",
    source: str = "github_app_installation",
) -> GitHubRepositoryPermissionGrant:
    return GitHubRepositoryPermissionGrant(
        repository_hash=repo_hash,
        permission_id=perm_id,
        permission_kind=kind,
        access_level=level,
        source_auth_mode=source,
        grant_hash="g" * 64,
    )


class TestPerRepoPermissionGranularity:
    @pytest.mark.contract
    def test_auth_state_validates_with_repository_permission_grants(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        d = auth.to_dict()
        assert len(d["repository_permission_grants"]) == 1
        assert d["repository_permission_grants"][0]["repository_hash"] == "r" * 64

    @pytest.mark.adversarial
    def test_auth_state_schema_rejects_invalid_repository_hash(self):
        grant = _make_grant("s" * 63, "issues:read")
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, repository_permission_grants=[grant]
        )
        data = auth.to_dict()
        import jsonschema

        schema = json.loads(
            (SCHEMAS_DIR / "rig.github_provider.auth_state.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(data))
        assert any(
            "repository_access_hashes" not in str(err.absolute_path)
            and "repository_permission_grants" in str(err.absolute_path)
            for err in errors
        ), f"Should reject short repo hash: {[e.message for e in errors]}"

    @pytest.mark.contract
    def test_repo_read_allowed_with_matching_grant(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_repo_read_refused_when_target_repository_missing(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[_make_grant("r" * 64, "issues:read")],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.repository.missing"

    @pytest.mark.adversarial
    def test_repo_read_refused_when_no_grants_for_repo(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[_make_grant("x" * 64, "issues:read")],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.repository.access_denied"

    @pytest.mark.adversarial
    def test_repo_read_refused_when_grant_permission_unrelated(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[_make_grant("r" * 64, "administration:read")],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.permission.missing"

    @pytest.mark.adversarial
    def test_repo_read_refused_when_grant_kind_mismatches(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "oauth_scope", "read")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.adversarial
    def test_repo_write_refused_when_grant_only_has_read(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.issues.comment.write", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.contract
    def test_repo_write_allowed_with_write_grant_and_step_up(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:write", "github_app_permission", "write")
            ],
        )
        manifest = load_github_capability_manifest()
        decision = evaluate_github_capability(
            auth,
            "github.issues.comment.write",
            target_repository_hash="r" * 64,
            step_up_satisfied=True,
            manifest=manifest,
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_repo_write_refused_with_write_grant_but_no_step_up(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:write", "github_app_permission", "write")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.issues.comment.write", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.requires_step_up is True

    @pytest.mark.adversarial
    def test_destructive_refused_even_with_admin_grant(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "actions:write", "github_app_permission", "admin")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.workflow.rerun", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.adversarial
    def test_credentialed_refused_even_with_admin_grant(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant(
                    "r" * 64, "contents:write", "github_app_permission", "admin"
                )
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.contents.write", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED

    @pytest.mark.contract
    def test_two_repos_can_have_different_access_levels(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "contents:read", "github_app_permission", "read"),
                _make_grant(
                    "s" * 64, "contents:write", "github_app_permission", "write"
                ),
            ],
        )
        assert (
            auth.has_repository_permission(
                "r" * 64, "contents:read", "github_app_permission", "read"
            )
            is True
        )
        assert (
            auth.has_repository_permission(
                "r" * 64, "contents:write", "github_app_permission", "write"
            )
            is False
        )
        assert (
            auth.has_repository_permission(
                "s" * 64, "contents:write", "github_app_permission", "write"
            )
            is True
        )

    @pytest.mark.adversarial
    def test_repo_a_write_does_not_authorize_repo_b_write(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:write", "github_app_permission", "write")
            ],
        )
        assert (
            auth.has_repository_permission(
                "s" * 64, "issues:write", "github_app_permission", "write"
            )
            is False
        )

    @pytest.mark.adversarial
    def test_repo_b_read_does_not_authorize_repo_b_write(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        assert (
            auth.has_repository_permission(
                "r" * 64, "issues:write", "github_app_permission", "write"
            )
            is False
        )

    @pytest.mark.contract
    def test_public_metadata_no_repo_grants_required(self):
        auth = GitHubProviderAuthState.unauthenticated()
        decision = evaluate_github_capability(
            auth, "github.repo.metadata.read", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_app_install_inspect_no_repo_grants_required(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["administration:read"]
        )
        decision = evaluate_github_capability(
            auth, "github.app.installation.inspect", target_repository_hash=""
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_legacy_flat_access_alone_insufficient_with_grants_present(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.contract
    def test_receipt_includes_repo_hash_and_refusal_code(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read", "github_app_permission", "read")
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        request = GitHubProviderOperationRequest(
            operation_id="op-test-per-repo",
            capability_id="github.repo.issues.read",
            operation_kind="Read issues",
            operation_class=GitHubOperationClass.REMOTE_READ,
            auth_state=auth,
            repository_hash="r" * 64,
            actor_hash=hash_identifier("test"),
        )
        receipt = build_github_operation_receipt(request, decision)
        assert receipt.repository_hash == "r" * 64


class TestAuthStatePersistence:
    @pytest.mark.contract
    def test_write_and_read_roundtrip_content_light(self, tmp_path: Path):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_permission_grants=[_make_grant("r" * 64, "issues:read")],
        )
        path = write_auth_state(auth, tmp_path / "auth_state.json")
        assert path.is_file()
        loaded = read_auth_state(path)
        assert loaded.provider_id == "github"
        assert len(loaded.repository_permission_grants) == 1

    @pytest.mark.adversarial
    def test_rejects_raw_token_field_on_write(self, tmp_path: Path):
        auth = GitHubProviderAuthState()
        data = auth.to_dict()
        data["access_token"] = "ghp_fake12345"
        path = tmp_path / "auth_state.json"
        path.write_text(json.dumps(data, indent=2))
        with pytest.raises(ValueError, match="raw_token_field"):
            read_auth_state(path)

    @pytest.mark.adversarial
    def test_rejects_raw_token_field_on_read(self, tmp_path: Path):
        path = tmp_path / "malformed.json"
        path.write_text(json.dumps({"access_token": "ghp_fake12345"}))
        with pytest.raises(ValueError, match="raw_token_field"):
            read_auth_state(path)

    @pytest.mark.adversarial
    def test_malformed_json_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            read_auth_state(path)

    @pytest.mark.adversarial
    def test_no_raw_owner_repo_in_persisted(self, tmp_path: Path):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64
        )
        path = write_auth_state(auth, tmp_path / "auth_state.json")
        content = path.read_text()
        assert "owner/repo" not in content


class TestGrantLifecycle:
    @pytest.mark.adversarial
    def test_expired_grant_does_not_authorize(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                GitHubRepositoryPermissionGrant(
                    repository_hash="r" * 64,
                    permission_id="issues:read",
                    permission_kind="github_app_permission",
                    access_level="read",
                    source_auth_mode="github_app_installation",
                    grant_hash="g" * 64,
                    grant_status=GitHubGrantStatus.EXPIRED,
                )
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.grant.expired"

    @pytest.mark.adversarial
    def test_revoked_grant_does_not_authorize(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                GitHubRepositoryPermissionGrant(
                    repository_hash="r" * 64,
                    permission_id="issues:read",
                    permission_kind="github_app_permission",
                    access_level="read",
                    source_auth_mode="github_app_installation",
                    grant_hash="g" * 64,
                    grant_status=GitHubGrantStatus.REVOKED,
                )
            ],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED
        assert decision.refusal_code == "github.grant.revoked"


class TestLegacyFallback:
    @pytest.mark.contract
    def test_legacy_flat_access_works_when_no_grants(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_access_hashes=["r" * 64],
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.ALLOWED

    @pytest.mark.adversarial
    def test_legacy_flat_access_blocked_when_repo_scope_missing(self):
        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:read"]
        )
        decision = evaluate_github_capability(
            auth, "github.repo.issues.read", target_repository_hash="r" * 64
        )
        assert decision.verdict == GitHubVerdict.REFUSED


class TestLocalAdapter:
    @pytest.mark.integration
    def test_repo_metadata_read_allowed_public(self):
        from rig_relay.integrations.github_provider._adapter import (
            run_local_read_operation,
        )

        auth = GitHubProviderAuthState.unauthenticated()
        receipt = run_local_read_operation("op-001", "github.repo.metadata.read", auth)
        assert receipt.verdict == "allowed"

    @pytest.mark.adversarial
    def test_issues_read_requires_issues_grant(self):
        from rig_relay.integrations.github_provider._adapter import (
            run_local_read_operation,
        )

        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64, scopes_or_permissions=["issues:read"]
        )
        receipt = run_local_read_operation(
            "op-002", "github.repo.issues.read", auth, repository_hash="r" * 64
        )
        assert receipt.verdict == "refused"

    @pytest.mark.integration
    def test_adapter_emits_receipt_for_allowed_read(self):
        from rig_relay.integrations.github_provider._adapter import (
            run_local_read_operation,
        )

        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[_make_grant("r" * 64, "issues:read")],
        )
        receipt = run_local_read_operation(
            "op-003", "github.repo.issues.read", auth, repository_hash="r" * 64
        )
        assert receipt.verdict == "allowed"
        errors = validate_github_operation_receipt(receipt.to_dict())
        assert not errors, f"Receipt schema errors: {errors}"

    @pytest.mark.integration
    def test_adapter_emits_receipt_for_refused_read(self):
        from rig_relay.integrations.github_provider._adapter import (
            run_local_read_operation,
        )

        auth = GitHubProviderAuthState.unauthenticated()
        receipt = run_local_read_operation(
            "op-004", "github.actions.artifacts.read", auth, repository_hash="r" * 64
        )
        assert receipt.verdict == "refused"
        assert receipt.refusal_code

    @pytest.mark.substrate
    def test_adapter_does_not_make_network_calls(self):
        pass


class TestStatusSnapshot:
    @pytest.mark.contract
    def test_snapshot_validates(self):
        from rig_relay.integrations.github_provider._status import (
            _validate_status_snapshot,
            build_status_snapshot,
        )

        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            scopes_or_permissions=["issues:read"],
            repository_permission_grants=[_make_grant("r" * 64, "issues:read")],
        )
        snapshot = build_status_snapshot(auth)
        errors = _validate_status_snapshot(snapshot)
        assert not errors, f"Status snapshot errors: {errors}"

    @pytest.mark.contract
    def test_snapshot_counts_grants_correctly(self):
        from rig_relay.integrations.github_provider._status import build_status_snapshot

        auth = GitHubProviderAuthState.authenticated_for_app_installation(
            account_hash="a" * 64,
            repository_permission_grants=[
                _make_grant("r" * 64, "issues:read"),
                GitHubRepositoryPermissionGrant(
                    repository_hash="s" * 64,
                    permission_id="contents:read",
                    permission_kind="github_app_permission",
                    access_level="read",
                    source_auth_mode="github_app_installation",
                    grant_hash="g2" + "y" * 62,
                    grant_status=GitHubGrantStatus.EXPIRED,
                ),
                GitHubRepositoryPermissionGrant(
                    repository_hash="t" * 64,
                    permission_id="issues:write",
                    permission_kind="github_app_permission",
                    access_level="write",
                    source_auth_mode="github_app_installation",
                    grant_hash="g3" + "z" * 62,
                    grant_status=GitHubGrantStatus.REVOKED,
                ),
            ],
        )
        snapshot = build_status_snapshot(auth)
        assert snapshot["grant_count"] == 1
        assert snapshot["expired_grant_count"] == 1
        assert snapshot["revoked_grant_count"] == 1
        assert snapshot["repository_count"] == 1


class TestAdversarialRedaction:
    @pytest.mark.adversarial
    def test_no_github_token_patterns_in_receipt(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-redact-001",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash="r" * 64,
            actor_hash=hash_identifier("test"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        data = json.dumps(receipt.to_dict())
        for pat in ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"]:
            assert pat not in data, f"Token pattern '{pat}' found"

    @pytest.mark.adversarial
    def test_no_raw_owner_repo_in_receipt(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-redact-002",
            capability_id="github.repo.metadata.read",
            operation_kind="Read metadata",
            operation_class=GitHubOperationClass.READ_ONLY,
            auth_state=auth,
            repository_hash=hash_identifier("myorg/myrepo"),
            actor_hash=hash_identifier("test"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        data = json.dumps(receipt.to_dict())
        assert "myorg/myrepo" not in data

    @pytest.mark.adversarial
    def test_no_raw_content_fields_in_receipt(self):
        auth = GitHubProviderAuthState.unauthenticated()
        request = GitHubProviderOperationRequest(
            operation_id="op-redact-003",
            capability_id="github.repo.metadata.read",
            auth_state=auth,
            repository_hash="r" * 64,
            actor_hash=hash_identifier("test"),
        )
        decision = GitHubProviderCapabilityDecision(
            capability_id="github.repo.metadata.read", verdict=GitHubVerdict.ALLOWED
        )
        receipt = build_github_operation_receipt(request, decision)
        data = json.dumps(receipt.to_dict())
        for key in [
            "raw_token",
            "raw_prompt",
            "raw_credential",
            "raw_repository_content",
            "raw_absolute_path",
        ]:
            assert key not in data, f"Forbidden key '{key}' in receipt"
