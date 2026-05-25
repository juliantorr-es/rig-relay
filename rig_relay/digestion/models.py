"""Digestion models — repository intake, ecosystem, topology, and mission proposal."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EcosystemLanguage(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    RUST = "rust"


class ConfidenceLevel(StrEnum):
    DEFINITE = "definite"
    INFERRED = "inferred"
    INDETERMINATE = "indeterminate"
    NEEDS_CONFIRMATION = "needs_confirmation"


class ProvenanceClass(StrEnum):
    FILESYSTEM_MANIFEST = "filesystem_manifest"
    GIT_STATE = "git_state"
    INSTRUCTION_FILE = "instruction_file"
    CI_WORKFLOW = "ci_workflow"
    STRUCTURAL_INSPECTION = "structural_inspection"
    USER_CONFIRMED = "user_confirmed"
    INDETERMINATE = "indeterminate"


class SafetyClassification(StrEnum):
    READ_ONLY_VALIDATION = "read_only_validation"
    WRITES_WORKSPACE = "writes_workspace"
    UNKNOWN = "unknown"
    NEEDS_CONFIRMATION = "needs_confirmation"


class InstructionKind(StrEnum):
    AGENT_INSTRUCTIONS = "agent_instructions"
    CONTRIBUTOR_GUIDE = "contributor_guide"
    SECURITY_POLICY = "security_policy"
    GOVERNANCE = "governance"
    BUILD_MANIFEST = "build_manifest"
    CI_WORKFLOW = "ci_workflow"
    UNKNOWN = "unknown"


class TopologyKind(StrEnum):
    SOURCE = "source"
    TEST = "test"
    DOCS = "docs"
    SCHEMAS = "schemas"
    SCRIPTS = "scripts"
    CONFIG = "config"
    GENERATED = "generated"
    UNKNOWN = "unknown"


class IdentityStatus(StrEnum):
    UNREGISTERED_LOCAL = "unregistered_local_repository"
    GITHUB_BACKED_CANDIDATE = "github_backed_candidate"
    REGISTERED = "registered"


class CommandKind(StrEnum):
    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    FORMAT = "format"
    BUILD = "build"
    UNKNOWN = "unknown"


class RepositoryIdentityCandidate(BaseModel):
    """Ephemeral identity for preview intake. Not durable until registration in Slice 1B."""

    model_config = ConfigDict(extra="forbid")

    status: IdentityStatus = Field(
        default=IdentityStatus.UNREGISTERED_LOCAL,
        description="Registration status of this repository identity.",
    )
    remote_identity_digest: str | None = Field(
        default=None,
        description="Remote-derived digest when GitHub origin is recognized.",
    )
    worktree_root_digest: str | None = Field(
        default=None,
        description="SHA256 of resolved Git worktree root path — a matching signal, not durable identity.",
    )
    preview_correlation_id: str | None = Field(
        default=None,
        description="Temporary identifier for in-memory preview correlation. Not persisted.",
    )


class OpenedRepository(BaseModel):
    """Read-only reference to the selected user repository. Never mutated by intake."""

    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(
        description="Resolved absolute path to the selected repository root."
    )
    git_root: str | None = Field(
        default=None,
        description="Git worktree root from `git rev-parse --show-toplevel`, None if not a git repo.",
    )
    is_git_repo: bool = Field(
        default=False,
        description="Whether the selected directory is inside a Git worktree.",
    )
    branch: str | None = Field(
        default=None, description="Current branch name, or None for detached HEAD."
    )
    head_sha: str | None = Field(
        default=None, description="Full SHA of HEAD commit, or None if no commits."
    )
    remotes: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of git remotes with keys: name, url_digest, host.",
    )
    is_github_backed: bool = Field(
        default=False, description="True when at least one remote is github.com."
    )
    is_local_only: bool = Field(
        default=True, description="True when no remotes are configured."
    )


class DirtyState(BaseModel):
    """Git worktree dirty state summary."""

    model_config = ConfigDict(extra="forbid")

    modified: int = Field(default=0, description="Count of modified tracked files.")
    staged: int = Field(default=0, description="Count of staged changes.")
    untracked: int = Field(default=0, description="Count of untracked files.")
    deleted: int = Field(default=0, description="Count of deleted tracked files.")
    conflicted: int = Field(
        default=0, description="Count of files with merge conflicts."
    )


class DetectedEcosystem(BaseModel):
    """A detected language ecosystem in the repository."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(description="Detected language: python, typescript, or rust.")
    confidence: str = Field(
        default=ConfidenceLevel.DEFINITE,
        description="Confidence in the detection: definite, inferred, or indeterminate.",
    )
    evidence_files: list[str] = Field(
        default_factory=list, description="Manifest files that evidence this ecosystem."
    )
    package_manager: str | None = Field(
        default=None, description="Detected package manager: uv, npm, cargo, etc."
    )
    build_system: str | None = Field(
        default=None,
        description="Detected build system: hatchling, webpack, cargo, etc.",
    )
    test_frameworks: list[str] = Field(
        default_factory=list,
        description="Detected test frameworks: pytest, jest, cargo-test, etc.",
    )
    lint_tools: list[str] = Field(
        default_factory=list,
        description="Detected lint tools: ruff, eslint, clippy, etc.",
    )
    type_checkers: list[str] = Field(
        default_factory=list, description="Detected type checkers: pyright, tsc, etc."
    )
    formatters: list[str] = Field(
        default_factory=list,
        description="Detected formatters: ruff-format, prettier, cargo-fmt, etc.",
    )
    entry_points: list[str] = Field(
        default_factory=list, description="Detected entry point files."
    )
    provenance: str = Field(
        default=ProvenanceClass.FILESYSTEM_MANIFEST,
        description="Source of detection evidence.",
    )


class InstructionScope(BaseModel):
    """Scoped instruction applicability for an instruction file."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Full path to the instruction file.")
    kind: str = Field(description="Kind of instruction file.")
    scope_root: str = Field(
        description="Directory under which this instruction applies."
    )
    scope_depth: int = Field(
        default=0, description="Depth of scope: 0 = repo root, 1 = subdir, 2+ = nested."
    )
    applies_to_paths: list[str] = Field(
        default_factory=list,
        description="Glob or explicit path patterns this instruction governs.",
    )
    applies_to_kind: str = Field(
        default="all",
        description="What kind of code this instruction applies to: all, source, tests, docs, schemas, config, or pattern.",
    )
    parent_instruction_path: str | None = Field(
        default=None,
        description="Path to parent instruction file in the scope chain, or None for root-level.",
    )
    has_agent_guidance: bool = Field(
        default=False,
        description="Whether the instruction file contains agent behavior guidance.",
    )
    has_validation_commands: bool = Field(
        default=False,
        description="Whether the instruction file contains validation command references.",
    )


class InstructionFile(BaseModel):
    """A discovered instruction or governance file with applicability scope."""

    model_config = ConfigDict(extra="forbid")

    scope: InstructionScope = Field(description="Scoped instruction applicability.")
    nested_instructions: list[str] = Field(
        default_factory=list,
        description="Paths to nested instruction files within this scope.",
    )


class DetectedCommand(BaseModel):
    """A detected build, test, lint, or validation command candidate."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(description="The detected command string.")
    kind: str = Field(
        default=CommandKind.UNKNOWN,
        description="Command kind: test, lint, typecheck, format, build, or unknown.",
    )
    safety_classification: str = Field(
        default=SafetyClassification.NEEDS_CONFIRMATION,
        description="Safety classification: read_only_validation, writes_workspace, unknown, or needs_confirmation.",
    )
    provenance: str = Field(
        default=ProvenanceClass.FILESYSTEM_MANIFEST,
        description="Where the command was detected: manifest, CI workflow, convention, or user_confirmed.",
    )
    source_file: str | None = Field(
        default=None, description="Path to the file where this command was found."
    )
    confidence: str = Field(
        default=ConfidenceLevel.INFERRED,
        description="Confidence: definite, inferred, or needs_confirmation.",
    )


class TopologyEntry(BaseModel):
    """A subsystem or directory in the repository topology."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Directory name under repo root.")
    kind: str = Field(
        default=TopologyKind.UNKNOWN,
        description="Topology classification: source, test, docs, schemas, scripts, config, generated, or unknown.",
    )
    file_count: int = Field(
        default=0, description="Number of tracked files in this directory."
    )
    dominant_language: str | None = Field(
        default=None, description="Dominant programming language, if determinable."
    )
    contains_entry_points: bool = Field(
        default=False,
        description="Whether this subsystem contains detected entry points.",
    )
    provenance: str = Field(
        default=ProvenanceClass.FILESYSTEM_MANIFEST,
        description="Source of topology evidence.",
    )


class DigestionFreshness(BaseModel):
    """Freshness markers for the operating picture."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str = Field(description="ISO 8601 timestamp of digestion.")
    head_sha: str | None = Field(
        default=None, description="HEAD SHA at digestion time. Changes on every commit."
    )
    dirty_state_digest: str | None = Field(
        default=None, description="SHA256 digest of canonical dirty file list."
    )
    manifest_digests: dict[str, str] = Field(
        default_factory=dict, description="Map of manifest path to SHA256 digest."
    )
    instruction_file_digests: dict[str, str] = Field(
        default_factory=dict,
        description="Map of instruction file path to SHA256 digest.",
    )
    stale: bool = Field(
        default=False, description="True if any input has changed since last digestion."
    )
    invalidation_reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable list of what changed since last digestion.",
    )
    freshness_ttl_seconds: int = Field(
        default=300, description="Soft TTL in seconds before suggesting re-digestion."
    )


class MissionProposalInput(BaseModel):
    """Mission proposal derived from operating picture. User admits or rejects."""

    model_config = ConfigDict(extra="forbid")

    source_candidates: list[str] = Field(
        default_factory=list,
        description="Primary source directories proposed for writable scope.",
    )
    paired_test_candidates: list[str] = Field(
        default_factory=list,
        description="Test directories conventionally paired with source candidates.",
    )
    doc_candidates: list[str] = Field(
        default_factory=list, description="Documentation directories."
    )
    config_surfaces_requiring_expansion: list[str] = Field(
        default_factory=list,
        description="Config/schema/CI files that need explicit scope expansion.",
    )
    generated_output_candidates: list[str] = Field(
        default_factory=list,
        description="Generated or build output directories — generally excluded from scope.",
    )
    suggested_validation_commands: list[str] = Field(
        default_factory=list,
        description="Validation commands safe to propose as normal-work validators.",
    )
    potentially_mutating_commands: list[str] = Field(
        default_factory=list,
        description="Validation commands that may write workspace files.",
    )
    checkpoint_supported: bool = Field(
        default=False,
        description="Whether the repo is a valid git worktree where governed checkpoints are supported in principle.",
    )
    indeterminate_items: list[str] = Field(
        default_factory=list,
        description="Indeterminate facts requiring user confirmation.",
    )
    requires_user_confirmation: list[str] = Field(
        default_factory=list,
        description="Items explicitly flagged for user confirmation before admission.",
    )
    ci_workflow_command_extraction: str = Field(
        default="deferred",
        description="Status of CI workflow command extraction: deferred or not_evaluated.",
    )


class StructuralCapabilities(BaseModel):
    """Available structural inspection capabilities in the current environment."""

    model_config = ConfigDict(extra="forbid")

    ast_grep_available: bool = Field(
        default=False,
        description="Whether native ast_grep capability (ast_grep_py) is available.",
    )
    inspect_structure_available: bool = Field(
        default=False,
        description="Whether native inspect_structure recipes are available.",
    )
    python_ast_available: bool = Field(
        default=False,
        description="Whether Python AST (stdlib ast module) is importable.",
    )


class LocalRepositoryOperatingPicture(BaseModel):
    """Full-fidelity local operating picture. Never sent to telemetry or external evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.local_repository_operating_picture.v1",
        description="Schema version identifier.",
    )
    repository: OpenedRepository = Field(
        description="Read-only reference to the opened repository."
    )
    identity_candidate: RepositoryIdentityCandidate = Field(
        description="Ephemeral identity candidate — not durable until registration in Slice 1B."
    )
    dirty_state: DirtyState = Field(
        default_factory=DirtyState, description="Git worktree dirty state summary."
    )
    detected_ecosystems: list[DetectedEcosystem] = Field(
        default_factory=list, description="Detected language ecosystems."
    )
    detected_commands: list[DetectedCommand] = Field(
        default_factory=list,
        description="Detected build, test, lint, and validation command candidates.",
    )
    instruction_files: list[InstructionFile] = Field(
        default_factory=list,
        description="Discovered instruction and governance files with scoped applicability.",
    )
    topology: list[TopologyEntry] = Field(
        default_factory=list, description="Repository subsystem topology map."
    )
    structural_capabilities: StructuralCapabilities = Field(
        default_factory=StructuralCapabilities,
        description="Available structural inspection capabilities.",
    )
    freshness: DigestionFreshness = Field(
        default_factory=DigestionFreshness,
        description="Freshness markers and invalidation inputs.",
    )
    mission_proposal: MissionProposalInput = Field(
        default_factory=MissionProposalInput,
        description="Proposed mission scope and validation candidates.",
    )
    known_gaps: list[str] = Field(
        default_factory=list,
        description="Known information gaps in this operating picture.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommendations explicitly marked as recommendations, not facts.",
    )
