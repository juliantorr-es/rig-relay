"""Google Workspace Provider v1 — local-first, credential-safe, refusal-first.

No live Google API calls. No raw token/private-key/client-secret storage.
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
from rig_relay.integrations.google_workspace._receipts import (
    build_workspace_receipt,
    validate_receipt,
)

__all__ = [
    "MODULE_DOC",
    "FakeGoogleDomainWideDelegation",
    "FakeGoogleJwtSigner",
    "FakeGoogleServiceAccountAuth",
    "FakeGoogleTokenEndpoint",
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
    "build_workspace_receipt",
    "evaluate_workspace_capability",
    "load_capability_manifest",
    "read_workspace_auth_state",
    "validate_manifest",
    "validate_receipt",
    "write_workspace_auth_state",
]
