"""Google Workspace Provider v1 — typed models, content-light.

No raw tokens, private keys, client secrets, OAuth codes, JWT assertions,
email addresses, or domain names in any model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class GoogleWorkspaceAuthMode(StrEnum):
    NONE = "none"
    OAUTH_USER = "oauth_user"
    OAUTH_DESKTOP_DEFERRED = "oauth_desktop_deferred"
    SERVICE_ACCOUNT = "service_account"
    SERVICE_ACCOUNT_DOMAIN_WIDE_DELEGATION = "service_account_domain_wide_delegation"
    WORKSPACE_MARKETPLACE_DEFERRED = "workspace_marketplace_deferred"
    API_KEY_PUBLIC = "api_key_public"


class GoogleWorkspaceAuthStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class GoogleWorkspaceProduct(StrEnum):
    GMAIL = "gmail"
    DRIVE = "drive"
    CALENDAR = "calendar"
    DOCS = "docs"
    SHEETS = "sheets"
    CONTACTS = "contacts"
    ADMIN_DIRECTORY = "admin_directory"
    CHAT = "chat"
    TASKS = "tasks"
    KEEP_FUTURE = "keep_future"


class GoogleWorkspaceOperationClass(StrEnum):
    PUBLIC_READ = "public_read"
    USER_READ = "user_read"
    USER_METADATA_READ = "user_metadata_read"
    DOMAIN_READ = "domain_read"
    SAFE_LOCAL_MUTATION = "safe_local_mutation"
    USER_MUTATION = "user_mutation"
    DOMAIN_MUTATION = "domain_mutation"
    DESTRUCTIVE_MUTATION = "destructive_mutation"
    CREDENTIALED_LIVE_OPERATION = "credentialed_live_operation"


class GoogleWorkspaceScopeSensitivity(StrEnum):
    NON_SENSITIVE = "non_sensitive"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    ADMIN_RESTRICTED = "admin_restricted"
    UNKNOWN = "unknown"


class GoogleWorkspaceBoundaryKind(StrEnum):
    USER_SUBJECT = "user_subject"
    CUSTOMER = "customer"
    DOMAIN = "domain"
    DRIVE_FILE = "drive_file"
    CALENDAR = "calendar"
    GMAIL_LABEL = "gmail_label"
    GMAIL_MESSAGE = "gmail_message"
    ADMIN_DIRECTORY_USER = "admin_directory_user"
    CHAT_SPACE = "chat_space"
    NONE = "none"
    UNKNOWN = "unknown"


class GoogleWorkspaceGrantStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class GoogleWorkspaceVerdict(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    FAILED = "failed"
    COMPLETED = "completed"


class GoogleWorkspaceTokenStorageAuthority(StrEnum):
    NONE = "none"
    ENVIRONMENT = "environment"
    KEYCHAIN_FUTURE = "keychain_future"
    USER_SUPPLIED_RUNTIME = "user_supplied_runtime"
    FORBIDDEN_JSON_FILE = "forbidden_json_file"


class GoogleWorkspaceRedactionStatus(StrEnum):
    CLEAN = "clean"
    REDACTED = "redacted"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class GoogleWorkspaceScopeGrant:
    scope_id: str
    scope_sensitivity: GoogleWorkspaceScopeSensitivity | str
    grant_status: GoogleWorkspaceGrantStatus | str = GoogleWorkspaceGrantStatus.ACTIVE
    access_level: str = "read"
    grant_hash: str = ""
    granted_at: str = field(default_factory=_now_iso)
    expires_at: str = ""


@dataclass
class GoogleWorkspaceAuthState:
    provider_id: str = "google_workspace"
    auth_mode: GoogleWorkspaceAuthMode | str = "none"
    auth_status: GoogleWorkspaceAuthStatus | str = "unauthenticated"
    account_hash: str = ""
    customer_hash: str = ""
    domain_hash: str = ""
    subject_hashes: list[str] = field(default_factory=list)
    domain_wide_delegation_authorized: bool = False
    scope_grants: list[GoogleWorkspaceScopeGrant] = field(default_factory=list)
    token_storage_authority: GoogleWorkspaceTokenStorageAuthority | str = "none"
    token_material_present: bool = False
    token_material_stored: bool = False
    generated_at: str = field(default_factory=_now_iso)
    redaction_status: str = "clean"

    def is_authenticated(self) -> bool:
        return str(self.auth_status) == "authenticated"

    def is_usable(self) -> bool:
        return self.is_authenticated() and self.token_material_stored is False

    def active_grants(self) -> list[GoogleWorkspaceScopeGrant]:
        return [g for g in self.scope_grants if str(g.grant_status) == "active"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.google_workspace.auth_state.v1",
            "provider_id": self.provider_id,
            "auth_mode": str(self.auth_mode),
            "auth_status": str(self.auth_status),
            "account_hash": self.account_hash,
            "customer_hash": self.customer_hash,
            "domain_hash": self.domain_hash,
            "subject_hashes": list(self.subject_hashes),
            "domain_wide_delegation_authorized": self.domain_wide_delegation_authorized,
            "scope_grants": [
                {
                    "scope_id": g.scope_id,
                    "scope_sensitivity": str(g.scope_sensitivity),
                    "grant_status": str(g.grant_status),
                    "access_level": g.access_level,
                    "grant_hash": g.grant_hash,
                    "granted_at": g.granted_at,
                    "expires_at": g.expires_at,
                }
                for g in self.scope_grants
            ],
            "token_storage_authority": str(self.token_storage_authority),
            "token_material_present": self.token_material_present,
            "token_material_stored": self.token_material_stored,
            "generated_at": self.generated_at,
            "redaction_status": str(self.redaction_status),
        }

    @classmethod
    def unauthenticated(cls) -> GoogleWorkspaceAuthState:
        return cls()

    @classmethod
    def authenticated_oauth_user(
        cls,
        account_hash: str,
        scope_grants: list[GoogleWorkspaceScopeGrant] | None = None,
    ) -> GoogleWorkspaceAuthState:
        return cls(
            auth_mode=GoogleWorkspaceAuthMode.OAUTH_USER,
            auth_status=GoogleWorkspaceAuthStatus.AUTHENTICATED,
            account_hash=account_hash,
            scope_grants=scope_grants or [],
            token_material_present=True,
        )


@dataclass
class GoogleWorkspaceCapability:
    capability_id: str
    product: GoogleWorkspaceProduct | str
    operation_kind: str = ""
    operation_class: GoogleWorkspaceOperationClass | str = "public_read"
    required_scopes: list[str] = field(default_factory=list)
    required_auth_modes: list[str] = field(default_factory=list)
    required_boundary: GoogleWorkspaceBoundaryKind | str = "none"
    scope_sensitivity: GoogleWorkspaceScopeSensitivity | str = "non_sensitive"
    default_allowed: bool = False
    mutation_class: str = "none"
    refusal_codes: list[str] = field(default_factory=list)
    requires_domain_wide_delegation: bool = False
    requires_user_subject: bool = False
    requires_customer_boundary: bool = False
    local_fixture_supported: bool = False
    local_fixture_hashed_output: bool = True


@dataclass
class GoogleWorkspaceCapabilityManifest:
    provider_id: str = "google_workspace"
    capabilities: dict[str, GoogleWorkspaceCapability] = field(default_factory=dict)

    def get_capability(self, capability_id: str) -> GoogleWorkspaceCapability | None:
        return self.capabilities.get(capability_id)


@dataclass
class GoogleWorkspaceDecision:
    capability_id: str
    verdict: GoogleWorkspaceVerdict | str
    refusal_code: str = ""
    reason: str = ""

    @property
    def is_allowed(self) -> bool:
        return str(self.verdict) == "allowed"

    @property
    def is_refused(self) -> bool:
        return str(self.verdict) == "refused"


@dataclass
class GoogleWorkspaceOperationRequest:
    operation_id: str
    capability_id: str
    operation_kind: str = ""
    operation_class: str = "public_read"
    auth_state: GoogleWorkspaceAuthState = field(
        default_factory=GoogleWorkspaceAuthState
    )
    subject_hash: str = ""
    customer_hash: str = ""
    resource_hash: str = ""


@dataclass
class GoogleWorkspaceOperationReceipt:
    operation_id: str
    capability_id: str
    product: str = ""
    operation_kind: str = ""
    operation_class: str = ""
    auth_mode: str = ""
    auth_state_hash: str = ""
    request_hash: str = ""
    response_hash: str = ""
    subject_hash: str = ""
    customer_hash: str = ""
    resource_hash: str = ""
    scope_grant_hashes: list[str] = field(default_factory=list)
    verdict: str = ""
    refusal_code: str = ""
    redaction_status: str = "clean"
    content_light: bool = True
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.google_workspace.operation_receipt.v1",
            "provider_id": "google_workspace",
            "operation_id": self.operation_id,
            "capability_id": self.capability_id,
            "product": self.product,
            "operation_kind": self.operation_kind,
            "operation_class": self.operation_class,
            "auth_mode": self.auth_mode,
            "auth_state_hash": self.auth_state_hash,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "subject_hash": self.subject_hash,
            "customer_hash": self.customer_hash,
            "resource_hash": self.resource_hash,
            "scope_grant_hashes": self.scope_grant_hashes,
            "verdict": self.verdict,
            "refusal_code": self.refusal_code,
            "redaction_status": self.redaction_status,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }
