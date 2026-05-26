"""GitHub Provider Implementation v0 — contract models and capability-gate enforcement.

No live GitHub OAuth. No GitHub App JWT. No token exchange. No webhooks.
No GitHub API network calls. No credential storage.
No raw tokens, private keys, or secrets in any exported model.

Provides:
- Typed models for auth state, capabilities, operation requests, receipts, decisions
- Capability manifest loading and validation
- Capability decision engine with refuse-default mutation policy
- Content-light operation receipt building
- Token detection and redaction helpers
- Bounded GitHub truth evidence models (v1)
- Read-only GitHub Repository Truth Adapter (v1)

Usage:
    from rig_relay.integrations.github_provider import (
        GitHubProviderAuthState,
        load_github_capability_manifest,
        evaluate_github_capability,
        build_github_operation_receipt,
    )
"""

from __future__ import annotations

from rig_relay.integrations.github_provider._auth_state_store import (
    read_auth_state,
    write_auth_state,
)
from rig_relay.integrations.github_provider._capabilities import (
    evaluate_github_capability,
    get_capability,
    load_github_capability_manifest,
    validate_github_capability_manifest,
)
from rig_relay.integrations.github_provider._fake_auth import (
    FakeGitHubAppAuth,
    FakeGitHubJwtSigner,
    FakeGitHubTokenEndpoint,
    is_test_token,
)
from rig_relay.integrations.github_provider._live_adapter import run_live_read_operation
from rig_relay.integrations.github_provider._live_auth import (
    GitHubLiveAuthConfig,
    GitHubLiveAuthError,
    GitHubLiveJwtSigner,
    GitHubLiveReadOnlySmoke,
    GitHubLiveTokenExchanger,
)
from rig_relay.integrations.github_provider._models import (
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
    GitHubProviderOperationReceipt,
    GitHubProviderOperationRequest,
    GitHubProviderRequiredPermission,
    GitHubRedactionStatus,
    GitHubRepositoryPermissionGrant,
    GitHubTokenStorageAuthority,
    GitHubVerdict,
    normalize_oauth_scope_to_app_permission,
    permission_satisfies,
)
from rig_relay.integrations.github_provider._operating_picture import (
    GitHubOperatingPictureError,
    build_github_operating_picture,
    build_github_operating_picture_from_paths,
    write_github_operating_picture,
)
from rig_relay.integrations.github_provider._permission_posture import (
    GitHubPermissionPostureError,
    build_github_permission_posture_report,
    build_github_permission_posture_report_from_paths,
)
from rig_relay.integrations.github_provider._publish_pr import (
    GitHubPublishPrConfig,
    GitHubPublishPrError,
    build_github_publish_pr,
)
from rig_relay.integrations.github_provider._receipts import (
    build_github_operation_receipt,
    validate_github_operation_receipt,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    assert_no_raw_github_token,
    hash_identifier,
    scan_for_tokens,
)
from rig_relay.integrations.github_provider._security_intake import (
    GitHubSecurityIntakeCollector,
    build_github_security_intake_report,
)
from rig_relay.integrations.github_provider._security_mission_candidates import (
    GitHubSecurityMissionCandidateRoutingError,
    route_github_security_work_items,
    route_github_security_work_items_from_path,
)
from rig_relay.integrations.github_provider._security_mission_packets import (
    GitHubSecurityMissionPacketError,
    project_github_security_mission_packets,
    project_github_security_mission_packets_from_path,
)
from rig_relay.integrations.github_provider._security_packet_runner import (
    GitHubSecurityPacketRunnerError,
    GitHubSecurityPacketRunnerPlan,
    build_github_security_packet_runner_plan,
)
from rig_relay.integrations.github_provider._security_work_items import (
    GitHubSecurityWorkItemProjectionError,
    project_github_security_work_items,
    project_github_security_work_items_from_path,
)
from rig_relay.integrations.github_provider._surface_audit import (
    GitHubSurfaceAuditError,
    GitHubSurfaceStewardAudit,
    build_github_surface_audit,
)
from rig_relay.integrations.github_provider._surface_preview import (
    GitHubSurfacePreview,
    GitHubSurfacePreviewError,
    build_github_surface_preview,
)
from rig_relay.integrations.github_provider._truth_adapter import (
    GitHubTruthAdapter,
    GitHubTruthAdapterError,
    create_truth_adapter,
)
from rig_relay.integrations.github_provider._truth_models import (
    GitHubCheckRunEvidence,
    GitHubCIStatusEvidence,
    GitHubCommitPresence,
    GitHubCommitRelationship,
    GitHubCompareResult,
    GitHubInstallationAccess,
    GitHubPublicationVerification,
    GitHubRemoteRefObservation,
    GitHubRepositoryIdentity,
    GitHubTokenStatus,
    GitHubTruthErrorKind,
    GitHubVerificationStatus,
)

__all__ = [
    "FakeGitHubAppAuth",
    "FakeGitHubJwtSigner",
    "FakeGitHubTokenEndpoint",
    "GitHubAccessLevel",
    "GitHubAuthMode",
    "GitHubAuthStatus",
    "GitHubCIStatusEvidence",
    "GitHubCheckRunEvidence",
    "GitHubCommitPresence",
    "GitHubCommitRelationship",
    "GitHubCompareResult",
    "GitHubGrantStatus",
    "GitHubInstallationAccess",
    "GitHubLiveAuthConfig",
    "GitHubLiveAuthError",
    "GitHubLiveJwtSigner",
    "GitHubLiveReadOnlySmoke",
    "GitHubLiveTokenExchanger",
    "GitHubOperatingPictureError",
    "GitHubOperationClass",
    "GitHubPermissionKind",
    "GitHubPermissionPostureError",
    "GitHubProviderAuthState",
    "GitHubProviderCapability",
    "GitHubProviderCapabilityDecision",
    "GitHubProviderCapabilityManifest",
    "GitHubProviderOperationReceipt",
    "GitHubProviderOperationRequest",
    "GitHubProviderRequiredPermission",
    "GitHubPublicationVerification",
    "GitHubPublishPrConfig",
    "GitHubPublishPrError",
    "GitHubRedactionStatus",
    "GitHubRemoteRefObservation",
    "GitHubRepositoryIdentity",
    "GitHubRepositoryPermissionGrant",
    "GitHubSecurityIntakeCollector",
    "GitHubSecurityMissionCandidateRoutingError",
    "GitHubSecurityMissionPacketError",
    "GitHubSecurityPacketRunnerError",
    "GitHubSecurityPacketRunnerPlan",
    "GitHubSecurityWorkItemProjectionError",
    "GitHubSurfaceAuditError",
    "GitHubSurfacePreview",
    "GitHubSurfacePreviewError",
    "GitHubSurfaceStewardAudit",
    "GitHubTokenStatus",
    "GitHubTokenStorageAuthority",
    "GitHubTruthAdapter",
    "GitHubTruthAdapterError",
    "GitHubTruthErrorKind",
    "GitHubVerdict",
    "GitHubVerificationStatus",
    "assert_content_light_mapping",
    "assert_no_raw_github_token",
    "build_github_operating_picture",
    "build_github_operating_picture_from_paths",
    "build_github_operation_receipt",
    "build_github_permission_posture_report",
    "build_github_permission_posture_report_from_paths",
    "build_github_publish_pr",
    "build_github_security_intake_report",
    "build_github_security_packet_runner_plan",
    "build_github_surface_audit",
    "build_github_surface_preview",
    "create_truth_adapter",
    "evaluate_github_capability",
    "get_capability",
    "hash_identifier",
    "is_test_token",
    "load_github_capability_manifest",
    "normalize_oauth_scope_to_app_permission",
    "permission_satisfies",
    "project_github_security_mission_packets",
    "project_github_security_mission_packets_from_path",
    "project_github_security_work_items",
    "project_github_security_work_items_from_path",
    "read_auth_state",
    "route_github_security_work_items",
    "route_github_security_work_items_from_path",
    "run_live_read_operation",
    "scan_for_tokens",
    "validate_github_capability_manifest",
    "validate_github_operation_receipt",
    "write_auth_state",
    "write_github_operating_picture",
]
