"""rig_relay.governance — Dirty guard, auth, telemetry modes, update policy, governance engine.

Target package for migrating:
  vibe/core/guard/
  vibe/core/auth/
  vibe/core/telemetry/

Exports:
  GovernanceEngine — pure governance gate evaluator
  GateDecision, GovernanceDecisionKind, GovernanceReasonSeverity — decision models
  DecisionReason, BlockedIntent, AllowedIntent — decision sub-models
  ServiceState, ProfileState, LocalProfile, ProfileStore, CapabilityGate — local control-plane
"""

from __future__ import annotations

from rig_relay.governance.decisions import (
    AllowedIntent,
    BlockedIntent,
    DecisionReason,
    GateDecision,
    GovernanceDecisionKind,
    GovernanceReasonSeverity,
)
from rig_relay.governance.governance_engine import GovernanceEngine
from rig_relay.governance.mission_context_compiler import (
    MissionContextCompileBlocker,
    MissionContextCompiler,
    MissionContextCompilerResult,
)
from rig_relay.governance.mission_context_packet import (
    MissionContextBlocker,
    MissionContextDirtyFileState,
    MissionContextPacket,
    MissionContextPacketReceipt,
    MissionContextRequiredCheck,
    MissionContextSourceRef,
    MissionContextWarning,
    MissionEnvelopeLink,
    build_mission_context_packet_receipt,
)
from rig_relay.governance.mission_envelope import MissionDirtySummary, MissionEnvelope
from rig_relay.governance.service_state import (
    CapabilityGate,
    LocalProfile,
    ProfileState,
    ProfileStore,
    ServiceState,
    get_capability_gate,
)
from rig_relay.governance.steward_context_assembler import (
    CAPSULE_SCHEMA_VERSION,
    DIAGNOSIS_SCHEMA_VERSION,
    REPAIR_MISSION_SCHEMA_VERSION,
    REPAIR_RESULT_SCHEMA_VERSION,
    CapsuleDigestionResult,
    RawEvidenceBundle,
    RepairMissionPacket,
    RepairResult,
    SubstrateDiagnosis,
    assemble_raw_evidence,
    build_repair_mission,
    build_repair_result,
    diagnose_substrate,
    digest_to_capsule,
    validate_capsule,
)

__all__ = [
    "CAPSULE_SCHEMA_VERSION",
    "DIAGNOSIS_SCHEMA_VERSION",
    "REPAIR_MISSION_SCHEMA_VERSION",
    "REPAIR_RESULT_SCHEMA_VERSION",
    "AllowedIntent",
    "BlockedIntent",
    "CapabilityGate",
    "CapsuleDigestionResult",
    "DecisionReason",
    "GateDecision",
    "GovernanceDecisionKind",
    "GovernanceEngine",
    "GovernanceReasonSeverity",
    "LocalProfile",
    "MissionContextBlocker",
    "MissionContextCompileBlocker",
    "MissionContextCompiler",
    "MissionContextCompilerResult",
    "MissionContextDirtyFileState",
    "MissionContextPacket",
    "MissionContextPacketReceipt",
    "MissionContextRequiredCheck",
    "MissionContextSourceRef",
    "MissionContextWarning",
    "MissionDirtySummary",
    "MissionEnvelope",
    "MissionEnvelopeLink",
    "ProfileState",
    "ProfileStore",
    "RawEvidenceBundle",
    "RepairMissionPacket",
    "RepairResult",
    "ServiceState",
    "SubstrateDiagnosis",
    "assemble_raw_evidence",
    "build_mission_context_packet_receipt",
    "build_repair_mission",
    "build_repair_result",
    "diagnose_substrate",
    "digest_to_capsule",
    "get_capability_gate",
    "validate_capsule",
]
