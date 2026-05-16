"""Ralph v0.6 — approval-ready, projection-driven background scanner.

Observes report projections, detects projection-integrity issues,
ranks overlooked gaps by deterministic policy, and produces a
hash-backed UI panel with decision contract and run state.

v0.6 adds:
- Run-state models (RalphRunState, RalphDecisionRequest/Result)
- Stable content hashes (panel, mission_candidate, input_snapshot)
- Separated scan/mission action boundaries
- Projection-integrity candidate detection
- No execution, no scheduling, no mutation.
"""

from __future__ import annotations

from rig_relay.ralph.models import (
    MISSION_ALLOWED_ACTIONS_DEFAULT,
    SCAN_ALLOWED_ACTIONS,
    ApprovalState,
    AutonomyTier,
    CandidateKind,
    InputSnapshot,
    MissionCandidate,
    RalphDecisionRequest,
    RalphDecisionResult,
    RalphPanel,
    RalphPanelAction,
    RalphPanelSummary,
    RalphRunState,
    RalphScanResult,
    RankedCandidate,
    RunStatus,
    ScanInput,
    ScoreComponents,
)
from rig_relay.ralph.scanner import (
    build_ralph_panel,
    build_run_state,
    compute_decision_request,
    compute_decision_result,
    scan_projections,
)

__all__ = [
    "MISSION_ALLOWED_ACTIONS_DEFAULT",
    "SCAN_ALLOWED_ACTIONS",
    "ApprovalState",
    "AutonomyTier",
    "CandidateKind",
    "InputSnapshot",
    "MissionCandidate",
    "RalphDecisionRequest",
    "RalphDecisionResult",
    "RalphPanel",
    "RalphPanelAction",
    "RalphPanelSummary",
    "RalphRunState",
    "RalphScanResult",
    "RankedCandidate",
    "RunStatus",
    "ScanInput",
    "ScoreComponents",
    "build_ralph_panel",
    "build_run_state",
    "compute_decision_request",
    "compute_decision_result",
    "scan_projections",
]
