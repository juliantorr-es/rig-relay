from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FindingKind(StrEnum):
    SEAM = auto()
    IMPLEMENTATION_GAP = auto()
    STUB = auto()
    GHOST = auto()
    DRIFT = auto()
    DUPLICATE_AUTHORITY = auto()
    UNSAFE_SURFACE = auto()
    VALIDATION_GAP = auto()
    DOC_CODE_MISMATCH = auto()
    PROTOCOL_MISMATCH = auto()


class FindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    kind: FindingKind
    title: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    confidence: float
    impact: str
    risk: str
    blast_radius: str
    validation_available: bool
    suggested_mode: str
    duplicate_of: str | None = None
    created_at: str

    # Self-regulation (SRL) specific fields
    srl_why_real: str | None = None
    srl_evidence_support: str | None = None
    srl_validation_proof: str | None = None
    srl_is_duplicate_or_stale: bool | None = None


class RegulationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    decision: Literal[
        "ignore", "record", "ask_user", "propose_patch", "open_repair_lane"
    ]
    rationale: str
    confidence: float
    required_user_approval: bool
    allowed_next_action: str | None = None


class PatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    source_finding_ids: list[str]
    scope: str
    files_expected: list[str]
    validation_commands: list[str]
    risk: str
    rollback_note: str
    requires_worktree_lane: bool


class CartographerReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str
    loop_mode: Literal["cartograph", "repair-propose", "repair-lane"]
    scan_inputs_sha256: str
    findings_count: int
    accepted_count: int
    rejected_count: int
    patch_plans_count: int
    receipt_sha256: str
