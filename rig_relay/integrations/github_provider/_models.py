"""GitHub Provider models — typed representations of auth state, capabilities,
operation requests, receipts, and decisions.

Content-light by design: no raw API keys, tokens, secrets, private file
contents, prompts, or repository content in any model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class GitHubAuthMode(StrEnum):
    NONE = "none"
    DEVICE_FLOW = "device_flow"
    OAUTH_WEB_FLOW = "oauth_web_flow"
    GITHUB_APP_INSTALLATION = "github_app_installation"
    GITHUB_APP_USER = "github_app_user"
    PAT_MANUAL_IMPORT = "personal_access_token_manual_import"


class GitHubAuthStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    UNAUTHENTICATED = "unauthenticated"
    PENDING_USER_ACTION = "pending_user_action"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class GitHubTokenStorageAuthority(StrEnum):
    NONE = "none"
    ENVIRONMENT = "environment"
    KEYCHAIN_FUTURE = "keychain_future"
    USER_SUPPLIED_RUNTIME = "user_supplied_runtime"
    FORBIDDEN_JSON_FILE = "forbidden_json_file"


class GitHubRedactionStatus(StrEnum):
    CLEAN = "clean"
    REDACTED = "redacted"
    NOT_APPLICABLE = "not_applicable"


_GITHUB_APP_AUTH_MODES = frozenset({
    GitHubAuthMode.GITHUB_APP_INSTALLATION,
    GitHubAuthMode.GITHUB_APP_USER,
})


@dataclass
class GitHubProviderAuthState:
    provider_id: str = "github"
    auth_mode: GitHubAuthMode = GitHubAuthMode.NONE
    auth_status: GitHubAuthStatus = GitHubAuthStatus.UNAUTHENTICATED
    account_hash: str = ""
    installation_id_hash: str | None = None
    scopes_or_permissions: list[str] = field(default_factory=list)
    token_storage_authority: GitHubTokenStorageAuthority = (
        GitHubTokenStorageAuthority.NONE
    )
    token_material_present: bool = False
    token_material_stored: bool = False
    expires_at: str = ""
    generated_at: str = field(default_factory=_now_iso)
    redaction_status: GitHubRedactionStatus = GitHubRedactionStatus.CLEAN

    def __post_init__(self) -> None:
        if self.auth_mode not in _GITHUB_APP_AUTH_MODES:
            self.installation_id_hash = None
        elif (
            self.installation_id_hash is not None
            and len(self.installation_id_hash) == 0
        ):
            self.installation_id_hash = None

    def is_authenticated(self) -> bool:
        return self.auth_status in {GitHubAuthStatus.AUTHENTICATED}

    def is_usable(self) -> bool:
        return (
            self.is_authenticated()
            and self.token_storage_authority
            != GitHubTokenStorageAuthority.FORBIDDEN_JSON_FILE
            and self.token_material_stored is False
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "rig.github_provider.auth_state.v1",
            "provider_id": self.provider_id,
            "auth_mode": self.auth_mode.value,
            "auth_status": self.auth_status.value,
            "account_hash": self.account_hash,
            "installation_id_hash": self.installation_id_hash or "",
            "scopes_or_permissions": list(self.scopes_or_permissions),
            "token_storage_authority": self.token_storage_authority.value,
            "token_material_present": self.token_material_present,
            "token_material_stored": self.token_material_stored,
            "expires_at": self.expires_at,
            "generated_at": self.generated_at,
            "redaction_status": self.redaction_status.value,
        }
        return result

    @classmethod
    def unauthenticated(cls) -> GitHubProviderAuthState:
        return cls(auth_status=GitHubAuthStatus.UNAUTHENTICATED)

    @classmethod
    def authenticated_for_app_installation(
        cls,
        account_hash: str,
        installation_id_hash: str | None = None,
        scopes_or_permissions: list[str] | None = None,
    ) -> GitHubProviderAuthState:
        return cls(
            auth_mode=GitHubAuthMode.GITHUB_APP_INSTALLATION,
            auth_status=GitHubAuthStatus.AUTHENTICATED,
            account_hash=account_hash,
            installation_id_hash=installation_id_hash,
            scopes_or_permissions=scopes_or_permissions or [],
            token_material_present=True,
        )


class GitHubOperationClass(StrEnum):
    READ_ONLY = "read_only"
    SAFE_LOCAL_MUTATION = "safe_local_mutation"
    REMOTE_READ = "remote_read"
    REMOTE_MUTATION = "remote_mutation"
    CREDENTIALED_REMOTE_MUTATION = "credentialed_remote_mutation"
    DESTRUCTIVE_REMOTE_MUTATION = "destructive_remote_mutation"


class GitHubVerdict(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    FAILED = "failed"
    COMPLETED = "completed"


class GitHubPermissionKind(StrEnum):
    OAUTH_SCOPE = "oauth_scope"
    GITHUB_APP_PERMISSION = "github_app_permission"
    PUBLIC_ACCESS = "public_access"
    FUTURE = "future"


class GitHubAccessLevel(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


@dataclass
class GitHubProviderRequiredPermission:
    permission_id: str
    permission_kind: GitHubPermissionKind | str
    access_level: GitHubAccessLevel | str
    required: bool = True


_PERMISSION_ACCESS_ORDER: dict[str, int] = {
    "none": 0,
    "read": 1,
    "write": 2,
    "admin": 3,
}


def permission_satisfies(
    required: GitHubProviderRequiredPermission,
    granted: str,
    granted_kind: GitHubPermissionKind | str,
    granted_access: GitHubAccessLevel | str = "read",
) -> bool:
    if not required.required:
        return True
    if str(required.permission_kind) != str(granted_kind):
        return False
    required_base = required.permission_id.rsplit(":", 1)[0]
    granted_base = (
        str(granted).rsplit(":", 1)[0] if ":" in str(granted) else str(granted)
    )
    if granted_base != required_base:
        return False
    if ":" in str(granted):
        _, granted_level = str(granted).rsplit(":", 1)
        granted_order = _PERMISSION_ACCESS_ORDER.get(granted_level, 0)
    else:
        granted_order = _PERMISSION_ACCESS_ORDER.get(str(granted_access), 0)
    required_order = _PERMISSION_ACCESS_ORDER.get(str(required.access_level), 0)
    return granted_order >= required_order


_OAUTH_TO_APP_PERMISSION_MAP: dict[str, str] = {
    "repo": "contents:write",
    "public_repo": "contents:read",
    "read:user": "metadata:read",
    "user:email": "metadata:read",
    "read:org": "administration:read",
    "read:discussions": "discussions:read",
}


def normalize_oauth_scope_to_app_permission(scope: str) -> str:
    return _OAUTH_TO_APP_PERMISSION_MAP.get(scope, scope)


@dataclass
class GitHubProviderCapability:
    capability_id: str
    operation_kind: str
    operation_class: GitHubOperationClass | str
    required_auth_modes: list[str] = field(default_factory=list)
    required_permissions: list[GitHubProviderRequiredPermission] = field(
        default_factory=list
    )
    requires_step_up: bool = False
    requires_receipt: bool = True
    stores_raw_content: bool = False
    content_light_output: bool = True
    default_allowed: bool = False
    refusal_code_when_denied: str = ""

    @property
    def is_read_only(self) -> bool:
        return self.operation_class in {
            GitHubOperationClass.READ_ONLY,
            GitHubOperationClass.REMOTE_READ,
        }

    @property
    def is_mutation(self) -> bool:
        return self.operation_class in {
            GitHubOperationClass.REMOTE_MUTATION,
            GitHubOperationClass.CREDENTIALED_REMOTE_MUTATION,
            GitHubOperationClass.DESTRUCTIVE_REMOTE_MUTATION,
        }

    @property
    def is_destructive(self) -> bool:
        return self.operation_class == GitHubOperationClass.DESTRUCTIVE_REMOTE_MUTATION

    @property
    def is_credentialed(self) -> bool:
        return self.operation_class == GitHubOperationClass.CREDENTIALED_REMOTE_MUTATION

    def allows_auth_mode(self, auth_mode: str) -> bool:
        return auth_mode in self.required_auth_modes


@dataclass
class GitHubProviderCapabilityManifest:
    provider_id: str = "github"
    capabilities: dict[str, GitHubProviderCapability] = field(default_factory=dict)

    def get_capability(self, capability_id: str) -> GitHubProviderCapability | None:
        return self.capabilities.get(capability_id)


@dataclass
class GitHubProviderOperationRequest:
    operation_id: str
    capability_id: str
    operation_kind: str = ""
    operation_class: GitHubOperationClass | str = GitHubOperationClass.READ_ONLY
    auth_state: GitHubProviderAuthState = field(default_factory=GitHubProviderAuthState)
    repository_hash: str = ""
    actor_hash: str = ""


@dataclass
class GitHubProviderCapabilityDecision:
    capability_id: str
    verdict: GitHubVerdict
    refusal_code: str = ""
    reason: str = ""
    requires_step_up: bool = False
    step_up_satisfied: bool = False

    @property
    def is_allowed(self) -> bool:
        return self.verdict == GitHubVerdict.ALLOWED

    @property
    def is_refused(self) -> bool:
        return self.verdict == GitHubVerdict.REFUSED


@dataclass
class GitHubProviderOperationReceipt:
    operation_id: str
    capability_id: str
    operation_kind: str
    operation_class: str
    auth_mode: str
    auth_state_hash: str
    request_hash: str
    response_hash: str
    repository_hash: str
    actor_hash: str
    verdict: str
    refusal_code: str
    redaction_status: str = "clean"
    content_light: bool = True
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.github_provider.operation_receipt.v1",
            "provider_id": "github",
            "operation_id": self.operation_id,
            "capability_id": self.capability_id,
            "operation_kind": self.operation_kind,
            "operation_class": self.operation_class,
            "auth_mode": self.auth_mode,
            "auth_state_hash": self.auth_state_hash,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "repository_hash": self.repository_hash,
            "actor_hash": self.actor_hash,
            "verdict": self.verdict,
            "refusal_code": self.refusal_code,
            "redaction_status": self.redaction_status,
            "content_light": self.content_light,
            "generated_at": self.generated_at,
        }
