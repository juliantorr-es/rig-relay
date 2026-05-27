"""Repository digestion — codebase intake and operating-picture generation.

Slice 1A: Desktop Repository Preview Intake v1.

Read-only repository inspection that produces a local operating picture
without writing any state into the opened repository. Rig-owned state is
stored under Application Support, keyed by opaque repository identity.
"""

from __future__ import annotations

from rig_relay.digestion.app_paths import RigApplicationPaths
from rig_relay.digestion.context_release import (
    DependencyRiskSummary,
    ExecutionRiskSummary,
    InstructionMapDigest,
    QuarantineInfo,
    RepositoryContextRelease,
    RepositoryLifecycleState,
    SafeValidationResult,
    StructuralIndexDigest,
    WorkspaceEligibility,
    compute_digest,
)
from rig_relay.digestion.dependency_classifier import (
    ClassifiedDependencies,
    DependencyClassifier,
    DependencyEntry,
    DependencyKind,
    DependencyRisk,
    PackageManagerKind,
)
from rig_relay.digestion.ecosystem_detector import DetectedEcosystem, detect_ecosystems
from rig_relay.digestion.freshness import compute_dirty_state_digest, compute_freshness
from rig_relay.digestion.identity import (
    CheckoutIdentity,
    RepositoryIdentityCandidate,
    WorktreeIdentity,
    derive_checkout_identity_candidate,
    derive_repository_identity_candidate,
    derive_worktree_identity_candidate,
    resolve_git_common_dir,
)
from rig_relay.digestion.instruction_scanner import (
    build_scope_map,
    discover_instructions,
    discover_instructions_with_content,
    resolve_instruction_scope,
)
from rig_relay.digestion.intake import IntakeResult, RepositoryIntakeService
from rig_relay.digestion.mission_admission import MissionAdmission, admit_mission
from rig_relay.digestion.mission_proposer import propose_mission
from rig_relay.digestion.models import (
    DetectedCommand,
    DigestionFreshness,
    DigestionTelemetryProjection,
    InstructionFile,
    InstructionScope,
    InstructionScopeCollection,
    LocalRepositoryOperatingPicture,
    MissionProposalInput,
    OpenedRepository,
    TopologyEntry,
)
from rig_relay.digestion.registration import RepositoryRegistrationService
from rig_relay.digestion.registration_models import (
    RegisteredRepository,
    SourceCheckoutRecord,
    WorkspacePreparationPlan,
    generate_checkout_id,
    generate_stable_repository_id,
)
from rig_relay.digestion.risk_assessor import (
    AssessedRisk,
    ExecutionRiskAssessor,
    ExecutionRiskReport,
    RiskCategory,
    RiskLevel,
    ScriptRiskAssessment,
)
from rig_relay.digestion.structural_indexer import (
    ModuleEntry,
    StructuralIndex,
    StructuralIndexConfig,
    StructuralIndexer,
    StructuralIndexKind,
    SymbolEntry,
    SymbolKind,
)
from rig_relay.digestion.telemetry_projection import build_telemetry_projection
from rig_relay.digestion.topology_mapper import map_topology
from rig_relay.digestion.validation_detector import detect_validation_candidates

__all__ = [
    "AssessedRisk",
    "CheckoutIdentity",
    "ClassifiedDependencies",
    "DependencyClassifier",
    "DependencyEntry",
    "DependencyKind",
    "DependencyRisk",
    "DependencyRiskSummary",
    "DetectedCommand",
    "DetectedEcosystem",
    "DigestionFreshness",
    "DigestionTelemetryProjection",
    "ExecutionRiskAssessor",
    "ExecutionRiskReport",
    "ExecutionRiskSummary",
    "InstructionFile",
    "InstructionMapDigest",
    "InstructionScope",
    "InstructionScopeCollection",
    "IntakeResult",
    "LocalRepositoryOperatingPicture",
    "MissionAdmission",
    "MissionProposalInput",
    "ModuleEntry",
    "OpenedRepository",
    "PackageManagerKind",
    "QuarantineInfo",
    "RegisteredRepository",
    "RepositoryContextRelease",
    "RepositoryIdentityCandidate",
    "RepositoryIntakeService",
    "RepositoryLifecycleState",
    "RepositoryRegistrationService",
    "RigApplicationPaths",
    "RiskCategory",
    "RiskLevel",
    "SafeValidationResult",
    "ScriptRiskAssessment",
    "SourceCheckoutRecord",
    "StructuralIndex",
    "StructuralIndexConfig",
    "StructuralIndexDigest",
    "StructuralIndexKind",
    "StructuralIndexer",
    "SymbolEntry",
    "SymbolKind",
    "TopologyEntry",
    "WorkspaceEligibility",
    "WorkspacePreparationPlan",
    "WorktreeIdentity",
    "admit_mission",
    "build_scope_map",
    "build_telemetry_projection",
    "compute_digest",
    "compute_dirty_state_digest",
    "compute_freshness",
    "derive_checkout_identity_candidate",
    "derive_repository_identity_candidate",
    "derive_worktree_identity_candidate",
    "detect_ecosystems",
    "detect_validation_candidates",
    "discover_instructions",
    "discover_instructions_with_content",
    "generate_checkout_id",
    "generate_stable_repository_id",
    "map_topology",
    "propose_mission",
    "resolve_git_common_dir",
    "resolve_instruction_scope",
]
