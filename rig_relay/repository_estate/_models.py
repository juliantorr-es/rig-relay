"""Repository estate domain models.

Typed, content-light models for repository registration, observation,
change detection, and projection. All identity fields are digests or
counts — never raw file contents, raw paths, or secrets.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ── Schema version constants ──────────────────────────────────────────

_REGISTRATION_SCHEMA = "rig.relay.repository_estate_registration.v1"
_OBSERVATION_SCHEMA = "rig.relay.repository_estate_observation.v1"


# ── Enums ──────────────────────────────────────────────────────────────


class RepositoryKind(StrEnum):
    LOCAL_ONLY = "local_only"
    GITHUB_BACKED = "github_backed"


class ObservationStatus(StrEnum):
    REGISTERED = "registered"
    OBSERVED = "observed"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    INACCESSIBLE = "inaccessible"
    NOT_A_REPOSITORY = "not_a_repository"
    DISAPPEARED = "disappeared"
    IDENTITY_MISMATCH = "identity_mismatch"


class ChangeKind(StrEnum):
    HEAD_CHANGED = "head_changed"
    BRANCH_CHANGED = "branch_changed"
    DETACHED_STATE_CHANGED = "detached_state_changed"
    DIRTY_STATE_CHANGED = "dirty_state_changed"
    TRACKED_FILE_COUNT_CHANGED = "tracked_file_count_changed"
    REMOTES_CHANGED = "remotes_changed"
    COMMON_DIR_CHANGED = "common_dir_changed"
    BECAME_INACCESSIBLE = "became_inaccessible"
    BECAME_NOT_A_REPOSITORY = "became_not_a_repository"
    REPOSITORY_DISAPPEARED = "repository_disappeared"
    INSTRUCTION_FILES_CHANGED = "instruction_files_changed"


class ProvenanceClass(StrEnum):
    CANONICAL_FACT = "canonical_fact"
    DERIVED_PROJECTION = "derived_projection"
    CORRUPT_UNTRUSTED = "corrupt_untrusted"
    REFUSED = "refused"
    MISSING = "missing"


class AuthorityState(StrEnum):
    CANONICAL_LIVE = "canonical_live"
    DEGRADED = "degraded"
    CONTROLLED_BOUNDARY = "controlled_boundary"
    MISSING = "missing"
    CORRUPT = "corrupt"
    STALE = "stale"
    REFUSED = "refused"


# ── Core domain models ────────────────────────────────────────────────


class DirtyCounts(BaseModel):
    """Git worktree dirty state as counts (never raw paths)."""

    model_config = ConfigDict(extra="forbid")

    modified: int = 0
    staged: int = 0
    untracked: int = 0
    deleted: int = 0
    conflicted: int = 0


class InstructionFilePresence(BaseModel):
    """Content-light presence record for a discovered instruction file.

    Stores only the kind label and SHA256 digests of path and content.
    Never stores raw paths or file contents.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        description="Instruction file kind label (e.g. agents_md, readme)."
    )
    path_digest: str = Field(description="SHA256 hex digest of the file path.")
    content_sha256: str = Field(description="SHA256 hex digest of the file content.")


class RemoteRecord(BaseModel):
    """Content-light git remote record. URL digest only, never raw URL."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Remote name (e.g. 'origin').")
    url_digest: str = Field(description="SHA256 hex digest of the remote URL.")
    host: str = Field(description="Classified host: github.com, gitlab.com, other.")


class GitIdentityBundle(BaseModel):
    """Operational git facts captured during a single observation.

    All fields are content-light: digests, counts, labels — never raw
    file contents, raw paths, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    head_sha: str | None = Field(default=None, description="Full SHA of HEAD commit.")
    branch: str | None = Field(
        default=None, description="Branch name, None if detached."
    )
    is_detached: bool = Field(default=False, description="Whether HEAD is detached.")
    dirty_counts: DirtyCounts = Field(
        default_factory=DirtyCounts, description="Git dirty state counts."
    )
    tracked_file_count: int = Field(
        default=0, description="Count of tracked files (git ls-files)."
    )
    is_github_backed: bool = Field(
        default=False, description="Whether at least one remote is github.com."
    )
    is_local_only: bool = Field(
        default=True, description="Whether no remotes are configured."
    )
    remotes: list[RemoteRecord] = Field(
        default_factory=list, description="Git remote records (url_digest only)."
    )
    git_common_dir_digest: str | None = Field(
        default=None,
        description="Content-based digest of .git/common directory for worktree correlation.",
    )
    instruction_files: list[InstructionFilePresence] = Field(
        default_factory=list,
        description="Instruction file presence records (digests only).",
    )


# ── Registration model ───────────────────────────────────────────────


class RegisteredRepository(BaseModel):
    """Durable repository registration record stored in append-only evidence.

    Stable identity across HEAD/dirty state changes. Re-registration of
    the same repository (same git_common_dir_digest) is idempotent and
    updates last_registered_at without creating a duplicate record.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_REGISTRATION_SCHEMA, frozen=True)

    repository_hash: str = Field(
        description="Stable opaque repository identifier. Derived from path digest + common-dir digest for local-only repos; remote-derived for GitHub-backed."
    )
    repository_label: str = Field(
        description="Human-readable label (directory name or GitHub owner/repo)."
    )
    repository_kind: RepositoryKind = Field(description="local_only or github_backed.")
    root_path_digest: str = Field(
        description="SHA256 hex digest of the resolved repository root path."
    )
    git_common_dir_digest: str | None = Field(
        default=None,
        description="Content-based digest of .git/common directory. Primary correlation signal for idempotent re-registration.",
    )
    remote_identity_digest: str | None = Field(
        default=None,
        description="Remote-derived digest for GitHub-backed repos. Stable reconciliation signal.",
    )
    registered_at: str = Field(
        description="ISO 8601 timestamp of initial registration."
    )
    last_registered_at: str = Field(
        description="ISO 8601 timestamp of most recent registration or reconciliation."
    )
    latest_observation_digest: str | None = Field(
        default=None,
        description="SHA256 hex digest of the most recent observation payload.",
    )
    latest_observation_at: str | None = Field(
        default=None, description="ISO 8601 timestamp of the most recent observation."
    )


# ── Observation model ────────────────────────────────────────────────


class RepositoryObservation(BaseModel):
    """A single repository observation event emitted as append-only evidence.

    Chainable via previous_observation_digest for integrity verification.
    Self-hashing via observation_digest for tamper detection.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_OBSERVATION_SCHEMA, frozen=True)

    observation_id: str = Field(
        description="Unique observation event identifier (UUID4)."
    )
    repository_hash: str = Field(
        description="The registered repository this observation belongs to."
    )
    observed_at: str = Field(description="ISO 8601 timestamp of observation.")
    status: ObservationStatus = Field(
        description="Observation outcome: registered, observed, unchanged, changed, inaccessible, not_a_repository, disappeared."
    )

    root_path_digest: str = Field(
        description="SHA256 hex digest of the resolved repository root path at observation time."
    )
    git_facts: GitIdentityBundle = Field(
        default_factory=GitIdentityBundle,
        description="Content-light git operational facts.",
    )

    previous_observation_digest: str | None = Field(
        default=None,
        description="SHA256 hex digest of the previous observation for this repository. None for first observation.",
    )
    observation_digest: str = Field(
        description="SHA256 hex digest of this observation (canonical JSON hash excluding this field)."
    )
    content_light_guarantee: bool = Field(
        default=True, description="This observation contains only content-light data."
    )


# ── Change detection model ───────────────────────────────────────────


class RepositoryObservationChange(BaseModel):
    """Detected changes between two observations of the same repository.

    Fields that changed are listed in change_kinds. A zero-length change_kinds
    list means no observable change was detected — the repository is unchanged
    since the previous observation.
    """

    model_config = ConfigDict(extra="forbid")

    repository_hash: str = Field(description="The registered repository.")
    from_observation_id: str = Field(description="Previous observation event ID.")
    to_observation_id: str = Field(description="Current observation event ID.")
    from_observation_digest: str | None = Field(
        default=None, description="SHA256 hex digest of previous observation."
    )
    to_observation_digest: str = Field(
        description="SHA256 hex digest of current observation."
    )
    changed: bool = Field(description="True when at least one change was detected.")
    change_kinds: list[ChangeKind] = Field(
        default_factory=list,
        description="Kinds of changes detected between the two observations.",
    )


# ── Projection model ──────────────────────────────────────────────────


class RegisteredRepositorySummary(BaseModel):
    """Content-light summary of a registered repository for projection output."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.CANONICAL_FACT
    repository_hash: str = ""
    repository_label: str = ""
    repository_kind: RepositoryKind = RepositoryKind.LOCAL_ONLY
    root_path_digest: str = ""
    registered_at: str = ""
    last_registered_at: str = ""
    latest_observation_digest: str | None = None
    latest_observation_at: str | None = None
    latest_status: ObservationStatus = ObservationStatus.REGISTERED
    latest_head_sha: str | None = None
    latest_branch: str | None = None
    is_detached: bool = False
    is_dirty: bool = False
    dirty_modified: int = 0
    dirty_untracked: int = 0
    tracked_file_count: int = 0
    is_github_backed: bool = False
    is_local_only: bool = True
    instruction_file_count: int = 0
    remote_count: int = 0
    degraded_reason: str = ""


class RecentChangeEvent(BaseModel):
    """Content-light summary of a detected change between two observations."""

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    repository_hash: str = ""
    repository_label: str = ""
    detected_at: str = ""
    change_kinds: list[ChangeKind] = Field(default_factory=list)
    from_observation_id: str = ""
    to_observation_id: str = ""


class CorruptionEvent(BaseModel):
    """Content-light record of evidence that failed validation during reconstruction.

    Corruption events carry enough metadata to diagnose which evidence stream
    failed and why, without exposing raw private content.
    """

    model_config = ConfigDict(extra="forbid")

    provenance: ProvenanceClass = ProvenanceClass.CORRUPT_UNTRUSTED
    event_kind: str = Field(
        description="Evidence stream kind: registration, observation."
    )
    event_id: str = Field(
        default="", description="Event ID of the corrupted evidence record."
    )
    reason: str = Field(
        description="Human-readable reason: malformed, digest_mismatch, model_validation_failed, chain_broken."
    )
    repository_hash: str = ""
    observation_id: str = ""


class RepositoryEstateProjection(BaseModel):
    """Content-light projection of the repository estate for PostgreSQL/Gridline.

    Reconstructable from canonical registration and observation evidence.
    Never contains raw file contents, raw paths, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.repository_estate_projection.v1", frozen=True
    )

    provenance: ProvenanceClass = ProvenanceClass.DERIVED_PROJECTION
    authority_state: AuthorityState = AuthorityState.MISSING
    degraded_reason: str = ""
    available: bool = False

    registered_repositories: list[RegisteredRepositorySummary] = Field(
        default_factory=list, description="Content-light summaries of registered repos."
    )
    total_registered: int = Field(
        default=0, description="Total count of registered repositories."
    )
    local_only_count: int = Field(
        default=0, description="Count of local-only (no remotes) repos."
    )
    github_backed_count: int = Field(
        default=0, description="Count of GitHub-backed repos."
    )
    dirty_count: int = Field(
        default=0,
        description="Count of repos with dirty working trees at latest observation.",
    )
    inaccessible_count: int = Field(
        default=0,
        description="Count of repos that were inaccessible at latest observation.",
    )

    recent_changes: list[RecentChangeEvent] = Field(
        default_factory=list,
        description="Recent observation-to-observation change events.",
    )
    total_observations: int = Field(
        default=0,
        description="Total count of observation events in the evidence store.",
    )

    corrupt_registration_count: int = Field(
        default=0, description="Count of registration events that failed validation."
    )
    corrupt_observation_count: int = Field(
        default=0, description="Count of observation events that failed validation."
    )
    corrupt_chain_links: int = Field(
        default=0,
        description="Count of observation chain digest links that are broken.",
    )
    corruption_events: list[CorruptionEvent] = Field(
        default_factory=list,
        description="Metadata for corrupted evidence records, content-light only.",
    )

    content_light_guarantee: bool = True
    projection_digest: str = ""


__all__ = [
    "AuthorityState",
    "ChangeKind",
    "CorruptionEvent",
    "DirtyCounts",
    "GitIdentityBundle",
    "InstructionFilePresence",
    "ObservationStatus",
    "ProvenanceClass",
    "RecentChangeEvent",
    "RegisteredRepository",
    "RegisteredRepositorySummary",
    "RemoteRecord",
    "RepositoryEstateProjection",
    "RepositoryKind",
    "RepositoryObservation",
    "RepositoryObservationChange",
]
