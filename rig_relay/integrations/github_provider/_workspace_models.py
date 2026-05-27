"""Developer GitHub workspace domain models — Lane J0.

Typed, content-light models for the developer GitHub workspace corridor:
installation identity, repository discovery, intake lifecycle, permission
diagnostics, publication readiness, and Gridline projections.

Never persists installation tokens, raw file contents, or secrets.
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import time

from pydantic import BaseModel, ConfigDict, Field


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    TOKEN_EXPIRED = "token_expired"
    ERROR = "error"


class IntakeState(StrEnum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    AVAILABLE = "available"
    SELECTED = "selected"
    IMPORTING = "importing"
    IMPORTED = "imported"
    SYNCED = "synced"
    STALE = "stale"
    FAILED = "failed"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"


class PublicationReadinessState(StrEnum):
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"
    MISSING_PERMISSION = "missing_permission"
    CONFIGURABLE = "configurable"
    CONFIGURED = "configured"
    BUILDING = "building"
    BUILT = "built"
    ERRORED = "errored"


class PagesActionState(StrEnum):
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REFUSED = "refused"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class PagesTargetMode(StrEnum):
    PROJECT_PAGE = "project_page"
    PORTFOLIO_SITE = "portfolio_site"


class WorkspaceErrorKind:
    INSTALLATION_MISSING = "github.workspace.installation_missing"
    TOKEN_EXPIRED = "github.workspace.token_expired"
    TOKEN_ACQUISITION_FAILED = "github.workspace.token_acquisition_failed"
    API_UNAVAILABLE = "github.workspace.api_unavailable"
    REPOSITORY_INACCESSIBLE = "github.workspace.repository_inaccessible"
    PERMISSION_MISSING = "github.workspace.permission_missing"
    NOT_SELECTED = "github.workspace.not_selected"
    ALREADY_IMPORTED = "github.workspace.already_imported"
    IMPORT_FAILED = "github.workspace.import_failed"
    UNSAFE_TARGET = "github.workspace.unsafe_target"
    PAGES_NOT_CONFIGURED = "github.workspace.pages_not_configured"
    PAGES_PERMISSION_MISSING = "github.workspace.pages_permission_missing"
    PUBLICATION_NOT_APPROVED = "github.workspace.publication_not_approved"
    UNKNOWN = "github.workspace.unknown_error"


# ── Connection ────────────────────────────────────────────────────────


class DeveloperGitHubConnection(BaseModel):
    """Content-light installation identity and auth state for the Gridline."""

    model_config = ConfigDict(extra="forbid")

    installation_id_hash: str = ""
    app_id: int = 0
    connection_state: str = ConnectionState.DISCONNECTED.value
    token_available: bool = False
    token_expires_in_seconds: float = 0.0
    repository_selection: str = ""
    accessible_repository_count: int = 0
    permissions_summary: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


# ── Repository Descriptor ─────────────────────────────────────────────


class DeveloperGitHubRepository(BaseModel):
    """Repository descriptor from installation discovery.

    Contains public metadata only. Clone URL is the anonymous HTTPS URL,
    never tokenized. All private details are content-light hashes.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: int = 0
    repository_hash: str = ""
    owner: str = ""
    name: str = ""
    full_name: str = ""
    description_hash: str | None = None
    visibility: str = ""
    default_branch: str = ""
    has_pages: bool = False
    clone_url: str = ""
    html_url: str = ""
    intake_state: str = IntakeState.DISCOVERED.value
    selected: bool = False
    analyzable: bool = False
    private: bool = False
    pushed_at: str | None = None

    def compute_identity_digest(self) -> str:
        raw = f"{self.owner}/{self.name}"
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


# ── Permission Diagnostics ────────────────────────────────────────────


class GitHubPermissionDiagnostic(BaseModel):
    """Per-repository permission inspection against installation token.

    Determines which GitHub API operations are available for a specific
    repository based on the granted installation permissions.
    """

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    permissions: dict[str, str] = Field(default_factory=dict)
    contents_readable: bool = False
    pages_readable: bool = False
    pages_configurable: bool = False
    administration_readable: bool = False
    can_clone: bool = False
    can_inspect_pages: bool = False
    can_configure_pages: bool = False
    missing_for_pages: list[str] = Field(default_factory=list)
    missing_for_clone: list[str] = Field(default_factory=list)
    error_kind: str | None = None


# ── Repository Intake ─────────────────────────────────────────────────


class RepositoryIntakeRequest(BaseModel):
    """Request to import a repository into the local workspace."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    owner: str
    repo: str
    local_workspace_root: str


class RepositoryIntakeResult(BaseModel):
    """Result of importing a repository locally via installation token."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    intake_state: str = ""
    local_path: str | None = None
    workspace_root: str | None = None
    head_sha: str | None = None
    branch: str | None = None
    clone_successful: bool = False
    remote_url_sanitized: bool = False
    error_kind: str | None = None
    error_message: str | None = None


class RepositorySyncRequest(BaseModel):
    """Request to synchronize an imported repository."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    local_path: str
    fetch_only: bool = True


class RepositorySyncResult(BaseModel):
    """Result of synchronizing a local repository with remote."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    synced: bool = False
    local_head_before: str | None = None
    remote_head: str | None = None
    branch: str | None = None
    commits_behind: int = 0
    commits_ahead: int = 0
    error_kind: str | None = None


# ── Publication Readiness ─────────────────────────────────────────────


class PublicationReadiness(BaseModel):
    """Pages/publication capability inspection for a repository.

    Determines whether this repo can host GitHub Pages, what permissions
    are available, and what additional permissions or configuration are
    needed before a publication action can execute.
    """

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    has_pages: bool = False
    pages_build_status: str | None = None
    pages_html_url: str | None = None
    cname: str | None = None
    source_branch: str | None = None
    source_path: str | None = None
    https_enforced: bool = False
    public: bool = False
    can_configure_pages: bool = False
    publication_eligible: bool = False
    requires_additional_permissions: list[str] = Field(default_factory=list)
    readiness_state: str = PublicationReadinessState.UNKNOWN.value
    blockers: list[str] = Field(default_factory=list)
    evidence_digest: str | None = None


# ── Pages Action Preparation ──────────────────────────────────────────


class PagesActionPreparation(BaseModel):
    """Prepared but not yet approved GitHub Pages action.

    Represents a planned Pages configuration or publication action that
    requires explicit developer approval before execution. Never executes
    silently.
    """

    model_config = ConfigDict(extra="forbid")

    action_id: str = ""
    repository_hash: str = ""
    owner: str = ""
    repo: str = ""
    target_type: str = PagesTargetMode.PROJECT_PAGE.value
    action_type: str = ""
    source_branch: str = ""
    source_path: str = "/"
    requires_approval: bool = True
    approval_status: str = PagesActionState.PLANNED.value
    required_permissions: list[str] = Field(default_factory=list)
    will_mutate_remote: bool = False
    suggested_next_action: str | None = None
    blockers: list[str] = Field(default_factory=list)


class LocalWorkspaceRegistration(BaseModel):
    """Registration of a GitHub-imported repository in local workspace."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    owner: str = ""
    repo: str = ""
    local_path: str = ""
    head_sha: str = ""
    branch: str = ""
    imported_at: str = ""
    last_synced_at: str | None = None
    registered: bool = False


# ── Gridline Projection ───────────────────────────────────────────────


class GitHubWorkspaceProjection(BaseModel):
    """Gridline-consumable projection of the developer GitHub workspace.

    Content-light: no installation tokens, raw file contents, prompts,
    or private code. Safe for frontend consumption, WebSocket streaming,
    and evidence capture.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.developer_github_workspace.v1"
    connection: DeveloperGitHubConnection | None = None
    repositories: list[DeveloperGitHubRepository] = Field(default_factory=list)
    selected_count: int = 0
    imported_count: int = 0
    analyzed_count: int = 0
    publishable_count: int = 0
    total_discovered: int = 0
    errors: list[str] = Field(default_factory=list)
    generated_at: str = ""

    def compute_digest(self) -> str:
        raw = self.model_dump_json(exclude={"generated_at"})
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


# ── Discovery Result ──────────────────────────────────────────────────


class RepositoryDiscoveryResult(BaseModel):
    """Result of listing repositories accessible to an installation."""

    model_config = ConfigDict(extra="forbid")

    total_count: int = 0
    repositories: list[DeveloperGitHubRepository] = Field(default_factory=list)
    repository_selection: str = ""
    error_kind: str | None = None
    errors: list[str] = Field(default_factory=list)


# ── Selection Result ──────────────────────────────────────────────────


class RepositorySelectionResult(BaseModel):
    """Result of selecting/deselecting a repository for local intake."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = ""
    selected: bool = False
    intake_state: str = ""
    error_kind: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────


def _workspace_action_id() -> str:
    return f"ws-{int(time.time())}-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"


__all__ = [
    "ConnectionState",
    "DeveloperGitHubConnection",
    "DeveloperGitHubRepository",
    "GitHubPermissionDiagnostic",
    "GitHubWorkspaceProjection",
    "IntakeState",
    "LocalWorkspaceRegistration",
    "PagesActionPreparation",
    "PagesActionState",
    "PagesTargetMode",
    "PublicationReadiness",
    "PublicationReadinessState",
    "RepositoryDiscoveryResult",
    "RepositoryIntakeRequest",
    "RepositoryIntakeResult",
    "RepositorySelectionResult",
    "RepositorySyncRequest",
    "RepositorySyncResult",
    "WorkspaceErrorKind",
]
