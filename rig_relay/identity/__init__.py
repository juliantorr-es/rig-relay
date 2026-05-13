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

See ``docs/governance/identity-provider-policy.md``.
"""

from __future__ import annotations

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
from rig_relay.identity.token_store import DevFileTokenStore, TokenStore

__all__ = [
    "DevFileTokenStore",
    "IdentityAccountSummary",
    "IdentityProvider",
    "IdentityProviderKind",
    "IdentitySessionStatus",
    "OAuthCallbackReceipt",
    "OAuthStartRequest",
    "OAuthStartResult",
    "TokenBundleMetadata",
    "TokenStore",
]
