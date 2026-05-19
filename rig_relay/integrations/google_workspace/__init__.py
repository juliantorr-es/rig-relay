"""Google Workspace Provider v1 — local-first, credential-safe, refusal-first.

Live auth support is available via _live_auth and _pkce modules
when RIG_GOOGLE_CLIENT_ID and related env vars are set.
No raw token/private-key/client-secret storage.
No mutation operations. All identifiers are SHA-256 hashes.
"""

from __future__ import annotations

from rig_relay.integrations.google_workspace._auth_state_store import (
    read_workspace_auth_state,
    write_workspace_auth_state,
)
from rig_relay.integrations.google_workspace._capabilities import (
    evaluate_workspace_capability,
    load_capability_manifest,
    validate_manifest,
)
from rig_relay.integrations.google_workspace._fake_auth import (
    MODULE_DOC,
    FakeGoogleDomainWideDelegation,
    FakeGoogleJwtSigner,
    FakeGoogleServiceAccountAuth,
    FakeGoogleTokenEndpoint,
)
from rig_relay.integrations.google_workspace._live_adapter import (
    _REQUIRED_API_SCOPES,
    run_live_workspace_read,
    should_skip_live_tests,
)
from rig_relay.integrations.google_workspace._live_auth import (
    GoogleLiveAuthConfig,
    GoogleLiveReadOnlySmoke,
    GoogleLiveTokenExchanger,
)
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthMode,
    GoogleWorkspaceAuthState,
    GoogleWorkspaceAuthStatus,
    GoogleWorkspaceBoundaryKind,
    GoogleWorkspaceCapability,
    GoogleWorkspaceCapabilityManifest,
    GoogleWorkspaceDecision,
    GoogleWorkspaceGrantStatus,
    GoogleWorkspaceOperationClass,
    GoogleWorkspaceOperationReceipt,
    GoogleWorkspaceOperationRequest,
    GoogleWorkspaceProduct,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceScopeSensitivity,
    GoogleWorkspaceVerdict,
)
from rig_relay.integrations.google_workspace._pkce import (
    PKCEParams,
    create_pkce_params,
    generate_code_challenge,
    generate_code_verifier,
    validate_code_challenge,
    validate_verifier_length,
)
from rig_relay.integrations.google_workspace._receipts import (
    build_workspace_receipt,
    validate_receipt,
)

__all__ = [
    "MODULE_DOC",
    "_REQUIRED_API_SCOPES",
    "FakeGoogleDomainWideDelegation",
    "FakeGoogleJwtSigner",
    "FakeGoogleServiceAccountAuth",
    "FakeGoogleTokenEndpoint",
    "GoogleLiveAuthConfig",
    "GoogleLiveReadOnlySmoke",
    "GoogleLiveTokenExchanger",
    "GoogleWorkspaceAuthMode",
    "GoogleWorkspaceAuthState",
    "GoogleWorkspaceAuthStatus",
    "GoogleWorkspaceBoundaryKind",
    "GoogleWorkspaceCapability",
    "GoogleWorkspaceCapabilityManifest",
    "GoogleWorkspaceDecision",
    "GoogleWorkspaceGrantStatus",
    "GoogleWorkspaceOperationClass",
    "GoogleWorkspaceOperationReceipt",
    "GoogleWorkspaceOperationRequest",
    "GoogleWorkspaceProduct",
    "GoogleWorkspaceScopeGrant",
    "GoogleWorkspaceScopeSensitivity",
    "GoogleWorkspaceVerdict",
    "PKCEParams",
    "build_workspace_receipt",
    "create_pkce_params",
    "evaluate_workspace_capability",
    "generate_code_challenge",
    "generate_code_verifier",
    "load_capability_manifest",
    "read_workspace_auth_state",
    "run_live_workspace_read",
    "should_skip_live_tests",
    "validate_code_challenge",
    "validate_manifest",
    "validate_receipt",
    "validate_verifier_length",
    "write_workspace_auth_state",
]
