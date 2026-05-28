from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.digestion.risk_assessor import ExecutionRiskReport


class RepositoryLifecycleState(StrEnum):
    REMOTE_SELECTED = auto()
    CLONED_QUARANTINED = auto()
    INSTRUCTIONS_DISCOVERED = auto()
    STRUCTURE_INDEXED = auto()
    DEPENDENCIES_CLASSIFIED = auto()
    EXECUTION_RISKS_REVIEWED = auto()
    SAFE_VALIDATION_PROBED = auto()
    CONTEXT_RELEASED = auto()
    WORKSPACE_ELIGIBLE = auto()
    DEGRADED = auto()


class QuarantineInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quarantine_path: Path = Field(
        description="Absolute path where the repository was cloned into quarantine."
    )
    cloned_at: datetime = Field(
        description="ISO 8601 timestamp when the clone completed."
    )
    source_url: str | None = Field(
        default=None, description="Remote URL the repository was cloned from."
    )
    source_branch: str | None = Field(
        default=None, description="Branch cloned from the remote."
    )
    source_head_sha: str = Field(description="Full SHA of the commit at clone time.")
    is_read_only_intended: bool = Field(
        default=True,
        description="Best-effort permission hint; not a security boundary. .git directory content may remain writable. Subject to OS-level permission enforcement.",
    )


class InstructionMapDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction_file_count: int = Field(
        default=0, description="Total count of instruction files discovered."
    )
    nested_instruction_count: int = Field(
        default=0, description="Count of nested instruction files within scope chains."
    )
    rule_directory_count: int = Field(
        default=0, description="Count of rule directories discovered."
    )
    scope_conflicts: int = Field(
        default=0, description="Number of instruction scope conflicts detected."
    )
    top_level_kinds: dict[str, int] = Field(
        default_factory=dict,
        description="Count of each InstructionKind among top-level instruction files.",
    )
    map_sha256: str = Field(
        default="", description="SHA256 hex digest of the canonical instruction map."
    )


class StructuralIndexDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_count: int = Field(default=0, description="Total number of modules indexed.")
    symbol_count: int = Field(default=0, description="Total number of symbols indexed.")
    exported_symbol_count: int = Field(
        default=0, description="Total number of exported symbols across all modules."
    )
    language_counts: dict[str, int] = Field(
        default_factory=dict, description="Module count per language kind."
    )
    parser_errors: int = Field(
        default=0, description="Total count of module files that failed to parse."
    )
    index_digest: str = Field(
        default="",
        description="Matches StructuralIndex.index_digest for the index this digest represents.",
    )


class DependencyRiskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_dependencies: int = Field(
        default=0, description="Total dependency count across all dependency sets."
    )
    production_count: int = Field(
        default=0, description="Count of production dependencies."
    )
    dev_count: int = Field(default=0, description="Count of development dependencies.")
    risk_count: int = Field(
        default=0, description="Count of dependencies classified with risk above NONE."
    )
    package_managers: list[str] = Field(
        default_factory=list, description="Detected package manager kinds."
    )
    classification_digest: str = Field(
        default="", description="Matches ClassifiedDependencies.classification_digest."
    )


class ExecutionRiskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_scripts_assessed: int = Field(
        default=0, description="Total number of scripts and manifests assessed."
    )
    blocked_count: int = Field(
        default=0, description="Number of assessments that are blocked from execution."
    )
    dangerous_count: int = Field(
        default=0,
        description="Number of assessments with DANGEROUS or REJECTED risk level.",
    )
    safe_count: int = Field(
        default=0,
        description="Number of assessments with SAFE risk level and no detections.",
    )
    report_digest: str = Field(
        default="", description="Matches ExecutionRiskReport.report_digest."
    )


class SafeValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(
        description="The admitted validation command that was executed."
    )
    exit_code: int = Field(description="Exit code of the executed command.")
    output_digest: str = Field(
        description="SHA256 hex digest of combined stdout and stderr."
    )
    latency_ms: int = Field(description="Wall-clock execution latency in milliseconds.")
    passed: bool = Field(
        description="True when the command exited successfully with expected output."
    )


class WorkspaceEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool = Field(
        description="True when the repository meets all workspace eligibility criteria."
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons blocking workspace eligibility.",
    )
    recommended_workspace_kind: str | None = Field(
        default=None,
        description="Recommended workspace kind: read_only, managed_write, etc.",
    )
    path_policy: dict[str, str] | None = Field(
        default=None,
        description="Per-path policy mapping: path -> read, write, or forbidden.",
    )


class RepositoryContextRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.repository_context_release.v1",
        description="Schema version identifier.",
    )
    release_id: str = Field(description="Unique identifier for this context release.")
    repository_root: Path = Field(description="Absolute path to the repository root.")
    lifecycle_state: RepositoryLifecycleState = Field(
        default=RepositoryLifecycleState.REMOTE_SELECTED,
        description="Current lifecycle state of the repository context pipeline.",
    )
    quarantine: QuarantineInfo | None = Field(
        default=None, description="Quarantine metadata; None for local repositories."
    )
    instruction_map_digest: InstructionMapDigest | None = Field(
        default=None,
        description="Instruction map digest; set after INSTRUCTIONS_DISCOVERED.",
    )
    structural_index_digest: StructuralIndexDigest | None = Field(
        default=None,
        description="Structural index digest; set after STRUCTURE_INDEXED.",
    )
    dependency_risk_summary: DependencyRiskSummary | None = Field(
        default=None,
        description="Dependency risk summary; set after DEPENDENCIES_CLASSIFIED.",
    )
    execution_risk_summary: ExecutionRiskSummary | None = Field(
        default=None,
        description="Execution risk summary; set after EXECUTION_RISKS_REVIEWED.",
    )
    execution_risk_report: ExecutionRiskReport | None = Field(
        default=None,
        description="Full per-script risk assessment detail. Stored alongside the summary for downstream query. Requires ExecutionRiskAssessor to have run.",
    )
    safe_validation_results: list[SafeValidationResult] = Field(
        default_factory=list,
        description="Results of admitted safe validation commands.",
    )
    workspace_eligibility: WorkspaceEligibility | None = Field(
        default=None,
        description="Workspace eligibility assessment; set after ELIGIBILITY check.",
    )
    restrictions: list[str] = Field(
        default_factory=list,
        description="Human-readable runtime restrictions derived from risk assessment.",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Conditions or defects preventing lifecycle advancement.",
    )
    degraded: bool = Field(
        default=False,
        description="True when one or more lifecycle stages failed or produced degraded results.",
    )
    degradation_reasons: list[str] = Field(
        default_factory=list, description="Human-readable reasons for degradation."
    )
    context_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated confidence in the completeness and correctness of this context release (0.0 to 1.0).",
    )
    released_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 timestamp when this context release was emitted.",
    )
    content_digest: str = Field(
        default="",
        description="SHA256 hex digest of the canonical release JSON (excluding this field).",
    )
    provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Evidence references mapping stage names to evidence digests (e.g., structural_index: sha256:abc...).",
    )


RepositoryContextRelease.model_rebuild()


def compute_digest(release: RepositoryContextRelease) -> str:
    raw = release.model_dump(mode="json")
    raw.pop("content_digest", None)
    canonical = dump_canonical_json(raw)
    return sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "DependencyRiskSummary",
    "ExecutionRiskSummary",
    "InstructionMapDigest",
    "QuarantineInfo",
    "RepositoryContextRelease",
    "RepositoryLifecycleState",
    "SafeValidationResult",
    "StructuralIndexDigest",
    "WorkspaceEligibility",
    "compute_digest",
]
