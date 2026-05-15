"""Ralph models v0.6 — scan, run state, decision, and UI projection types.

Adds run-state contracts (RalphRunState, RalphDecisionRequest/Result),
stable content hashes, separated scan/mission action boundaries, and
projection-integrity candidate kind. Content-light, SHA256 hashes.

v0.6 is approval-ready, not execution-ready.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AutonomyTier(IntEnum):
    OBSERVE = 0
    EVIDENCE_WRITE = 1
    SAFE_LOCAL_MAINTENANCE = 2
    PATCH_PROPOSAL = 3
    MAIN_WORKSPACE_MUTATION = 4
    EXTERNAL_SIDE_EFFECTS = 5


class RunStatus(StrEnum):
    IDLE = "idle"
    READY = "ready"
    AWAITING_USER_DECISION = "awaiting_user_decision"
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"


class ApprovalState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"


class ScanMode(StrEnum):
    OBSERVE_ONLY = "observe_only"


class ScanStopReason(StrEnum):
    NO_PROJECTIONS = "no_projections_found"
    NO_CANDIDATES = "no_candidates_after_ranking"
    COMPLETED = "scan_completed"
    MAX_TIME_EXCEEDED = "max_time_exceeded"
    MALFORMED_INPUT = "malformed_projection_input"


class CandidateKind(StrEnum):
    PROJECTION_CORRUPTION = "projection_corruption"
    PROJECTION_INTEGRITY = "projection_integrity"
    SECURITY_CONCERN = "security_concern"
    DATA_RACE = "data_race"
    STALE_CANONICAL_FINDING = "stale_canonical_finding"
    CANDIDATE_FINDING_WITH_EVIDENCE = "candidate_finding_with_evidence"
    DUPLICATE_CLUSTER = "duplicate_cluster"
    VALIDATION_GAP = "validation_gap"
    ARCHITECTURE_SEAM = "architecture_seam"
    IMPLEMENTATION_SEAM = "implementation_seam"
    LOW_RISK_DOCS = "low_risk_docs"
    LOW_RISK_PROJECTION = "low_risk_projection"
    DIAGNOSTIC_WARNING = "diagnostic_warning"


SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 10.0,
    "high": 8.0,
    "medium": 5.0,
    "low": 2.0,
    "none": 0.0,
}

KIND_WEIGHTS: dict[str, float] = {
    CandidateKind.PROJECTION_CORRUPTION: 20.0,
    CandidateKind.PROJECTION_INTEGRITY: 20.0,
    CandidateKind.DIAGNOSTIC_WARNING: 20.0,
    CandidateKind.SECURITY_CONCERN: 18.0,
    CandidateKind.DATA_RACE: 18.0,
    CandidateKind.STALE_CANONICAL_FINDING: 12.0,
    CandidateKind.CANDIDATE_FINDING_WITH_EVIDENCE: 10.0,
    CandidateKind.DUPLICATE_CLUSTER: 8.0,
    CandidateKind.VALIDATION_GAP: 7.0,
    CandidateKind.ARCHITECTURE_SEAM: 6.0,
    CandidateKind.IMPLEMENTATION_SEAM: 5.0,
    CandidateKind.LOW_RISK_DOCS: 2.0,
    CandidateKind.LOW_RISK_PROJECTION: 1.0,
}

RANKING_POLICY_VERSION = "ralph.ranking.v0"

SCAN_ALLOWED_ACTIONS = [
    "read projections",
    "read canonical fallback if projections are absent",
    "compute deterministic ranking",
    "return in-memory panel",
]

MISSION_ALLOWED_ACTIONS_DEFAULT = [
    "read files",
    "run read-only searches",
    "run validators",
    "write final report after approval",
]

FORBIDDEN_ACTIONS_V0 = [
    "source-code mutation",
    "canonical finding promotion",
    "canonical finding deletion",
    "report promotion",
    "external side effects",
    "worktree mutation",
    "merge to main",
    "network calls",
]

SUCCESS_CRITERIA_DEFAULT = [
    "Identify scope and affected files",
    "Produce evidence-backed report",
    "Recommend whether a follow-up mission is needed",
]

STOP_CONDITIONS_MISSION = [
    "dirty-state ambiguity",
    "missing source evidence",
    "attempted mutation",
    "missing AGENTS.md discipline",
]


class ScoreComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity_weight: float = 0.0
    kind_weight: float = 0.0
    evidence_bonus: float = 0.0
    staleness_weight: float = 0.0
    diagnostic_weight: float = 0.0
    recurrence_weight: float = 0.0
    total_score: float = 0.0


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "finding"
    id: str = ""
    path: str = ""


class RankedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_kind: str
    source_finding_id: str | None = None
    source_report_id: str | None = None
    title: str = ""
    severity: str = "medium"
    status: str = "open"
    reason: str = ""
    score: float = 0.0
    score_components: ScoreComponents = Field(default_factory=ScoreComponents)
    ranking_policy_version: str = RANKING_POLICY_VERSION
    recommended_mission_kind: str = ""
    risk_tier: int = AutonomyTier.OBSERVE
    requires_approval_for_execution: bool = True
    related_files: list[str] = Field(default_factory=list)
    scan_allowed_actions: list[str] = Field(default_factory=lambda: list(SCAN_ALLOWED_ACTIONS))


class MissionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_mission_candidate.v1"
    candidate_id: str = ""
    title: str = ""
    mission_kind: str = "read_only_audit"
    source_refs: list[SourceRef] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=lambda: list(MISSION_ALLOWED_ACTIONS_DEFAULT))
    forbidden_actions: list[str] = Field(default_factory=lambda: list(FORBIDDEN_ACTIONS_V0))
    requires_approval: bool = True
    required_autonomy_tier: int = AutonomyTier.OBSERVE
    success_criteria: list[str] = Field(default_factory=lambda: list(SUCCESS_CRITERIA_DEFAULT))
    stop_conditions: list[str] = Field(default_factory=lambda: list(STOP_CONDITIONS_MISSION))
    risk_tier: int = AutonomyTier.OBSERVE


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings_path: str = "docs/findings/out-of-scope-findings.jsonl"
    findings_sha256: str = ""
    report_summary_path: str = ""
    report_diagnostics_path: str = ""
    candidate_findings_path: str = ""
    open_raw_reports_path: str = ""
    max_reports_to_inspect: int = 200
    max_duration_seconds: float = 30.0


class InputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_input_snapshot.v1"
    input_source: str = ""
    projection_paths: list[str] = Field(default_factory=list)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    projection_metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_fallback_used: bool = False
    malformed_projection_count: int = 0


class RalphScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_scan.v1"
    scan_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: str = ScanMode.OBSERVE_ONLY.value
    stop_reason: str = ScanStopReason.COMPLETED.value
    inputs: ScanInput = Field(default_factory=ScanInput)
    input_snapshot: InputSnapshot | None = None
    ranking_policy_version: str = RANKING_POLICY_VERSION
    total_findings_inspected: int = 0
    candidates_considered: int = 0
    ranked_candidates: list[RankedCandidate] = Field(default_factory=list)
    mission_candidate: MissionCandidate | None = None
    stop_conditions_violated: list[str] = Field(default_factory=list)
    scan_duration_ms: float = 0.0


class RalphPanelAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = ""
    label: str = ""
    requires_confirmation: bool = True


class RalphPanelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = 0
    top_score: float = 0.0
    top_severity: str = "none"
    input_source: str = ""
    stop_reason: str = ""
    ranking_policy_version: str = RANKING_POLICY_VERSION


class RalphPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ui.ralph_panel.v1"
    status: str = "idle"
    summary: RalphPanelSummary = Field(default_factory=RalphPanelSummary)
    top_candidate: RankedCandidate | None = None
    ranked_candidates: list[RankedCandidate] = Field(default_factory=list)
    mission_candidate: MissionCandidate | None = None
    warnings: list[str] = Field(default_factory=list)
    available_actions: list[RalphPanelAction] = Field(default_factory=list)
    decision_required: bool = False
    approval_state: str = ApprovalState.NOT_REQUESTED.value
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    input_snapshot_sha256: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class RalphDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_decision_request.v1"
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_id: str = ""
    candidate_id: str = ""
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    approval_state: str = ApprovalState.PENDING.value
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = ""
    requested_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)


class RalphDecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_decision_result.v1"
    decision_id: str = ""
    scan_id: str = ""
    candidate_id: str = ""
    decision: str = ApprovalState.PENDING.value
    decided_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    rationale: str = ""
    next_phase: str = ""


class RalphRunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_run_state.v1"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    status: str = RunStatus.IDLE.value
    phase: str = "scan"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    scan_id: str = ""
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    selected_candidate_id: str = ""
    approval_state: str = ApprovalState.NOT_REQUESTED.value
    decision_id: str = ""


__all__ = [
    "FORBIDDEN_ACTIONS_V0",
    "KIND_WEIGHTS",
    "MISSION_ALLOWED_ACTIONS_DEFAULT",
    "RANKING_POLICY_VERSION",
    "SCAN_ALLOWED_ACTIONS",
    "SEVERITY_WEIGHTS",
    "STOP_CONDITIONS_MISSION",
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
    "ScanMode",
    "ScanStopReason",
    "ScoreComponents",
    "SourceRef",
]
