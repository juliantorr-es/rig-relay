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

__all__ = [
    "AllowedIntent",
    "BlockedIntent",
    "CapabilityGate",
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
    "ServiceState",
    "build_mission_context_packet_receipt",
    "get_capability_gate",
]
