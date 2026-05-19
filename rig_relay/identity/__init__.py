"""rig_relay.identity — Identity provider scaffold for Rig Relay.

Separate from governance (authority), desktop (UI), and coordination (leases).
Identity answers *who* the user is, not *what* they may do.

Identity does not grant:
    - Mutation authority (authorization receipts)
    - Telemetry consent
    - Drive access
    - GitHub repo access

Supported providers:
    - GitHub (identity-only scopes: read:user, user:email)
    - Google (identity/OIDC scopes: openid, email, profile)

Token storage:
    - DevFileTokenStore (dev-only, temporary plaintext)
    - MacKeychainTokenStore (future)

Credential store:
    - CredentialStore (ABC protocol)
    - InMemoryCredentialStore (testing)
    - KeychainBackedCredentialStore (macOS keychain)
    - NoOpCredentialStore (intentionally unavailable)

See ``docs/governance/identity-provider-policy.md``.
"""

from __future__ import annotations

from rig_relay.identity._credential_store import (
    CredentialMetadata,
    CredentialStore,
    InMemoryCredentialStore,
    KeychainBackedCredentialStore,
    NoOpCredentialStore,
    assert_no_secrets_in_json,
    get_credential_store,
    scan_raw_json_for_secrets,
)
from rig_relay.identity.auth_session_manager import (
    AuthSession,
    AuthSessionManager,
    AuthSessionStatus,
    get_auth_session_manager,
)
from rig_relay.identity.models import (
    IdentityAccountSummary,
    IdentityProviderKind,
    IdentitySessionStatus,
    OAuthCallbackReceipt,
    OAuthStartRequest,
    OAuthStartResult,
    TokenBundleMetadata,
)
from rig_relay.identity.providers import IdentityProvider
from rig_relay.identity.token_store import (
    DevFileTokenStore,
    TokenStore,
    enable_dev_file_token_store,
    is_dev_store_enabled,
)

__all__ = [
    "AuthSession",
    "AuthSessionManager",
    "AuthSessionStatus",
    "CredentialMetadata",
    "CredentialStore",
    "DevFileTokenStore",
    "IdentityAccountSummary",
    "IdentityProvider",
    "IdentityProviderKind",
    "IdentitySessionStatus",
    "InMemoryCredentialStore",
    "KeychainBackedCredentialStore",
    "NoOpCredentialStore",
    "OAuthCallbackReceipt",
    "OAuthStartRequest",
    "OAuthStartResult",
    "TokenBundleMetadata",
    "TokenStore",
    "assert_no_secrets_in_json",
    "enable_dev_file_token_store",
    "get_auth_session_manager",
    "get_credential_store",
    "is_dev_store_enabled",
    "scan_raw_json_for_secrets",
]
