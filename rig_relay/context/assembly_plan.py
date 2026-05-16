"""ContextAssemblyPlan contract spine v1.

Provides the type system for context assembly planning: candidates,
selections, omissions, budget accounting, hashing, and privacy.

Schema version: rig.context_assembly_plan.v1
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

PLAN_SCHEMA_VERSION = "rig.context_assembly_plan.v1"


# ── Enums ──────────────────────────────────────────────────────────


class CandidateKind(StrEnum):
    source = "source"
    test = "test"
    doc = "doc"
    schema = "schema"
    config = "config"
    work = "work"
    receipt = "receipt"
    governance = "governance"
    message = "message"
    unknown = "unknown"


class CandidateSource(StrEnum):
    requested_path = "requested_path"
    requested_symbol = "requested_symbol"
    repo_map = "repo_map"
    repo_index = "repo_index"
    work_map = "work_map"
    receipt = "receipt"
    recent_message = "recent_message"
    derived = "derived"


class CandidateRelation(StrEnum):
    direct = "direct"
    test = "test"
    doc = "doc"
    schema = "schema"
    same_package = "same_package"
    active_work = "active_work"
    collision = "collision"
    doctrine = "doctrine"
    config = "config"
    derived = "derived"


class RiskFlag(StrEnum):
    dirty = "dirty"
    collision = "collision"
    generated = "generated"
    large = "large"
    binary = "binary"
    untrusted = "untrusted"
    unavailable = "unavailable"


class TrustTier(StrEnum):
    first_party = "first_party"
    repo_content = "repo_content"
    tool_output = "tool_output"
    external = "external"
    untrusted = "untrusted"


class CacheTier(StrEnum):
    stable = "stable"
    semi_stable = "semi_stable"
    dynamic = "dynamic"
    volatile = "volatile"


class IncludeMode(StrEnum):
    full = "full"
    summary = "summary"
    path_only = "path_only"
    hash_only = "hash_only"


class OmissionReason(StrEnum):
    budget_exceeded = "budget_exceeded"
    disabled_by_scope = "disabled_by_scope"
    duplicate = "duplicate"
    risk_policy = "risk_policy"
    unavailable = "unavailable"
    unsupported = "unsupported"
    not_relevant = "not_relevant"


# ── Hash helpers ───────────────────────────────────────────────────


def _canonical_json(obj: Any) -> bytes:
    """Serialize to canonical JSON with sorted keys and compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def _sha256_hex(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _build_candidate_id(path: str, kind: str, source: str, relation: str) -> str:
    """Deterministic candidate id from stable fields."""
    raw = f"{path}|{kind}|{source}|{relation}"
    return _sha256_hex(raw.encode("utf-8"))[:20]


# ── Models ─────────────────────────────────────────────────────────


class ContextCandidate(BaseModel):
    """A discovered possible context item."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = ""
    path: str
    kind: CandidateKind
    source: CandidateSource
    relation: CandidateRelation
    estimated_tokens: int = Field(default=0, ge=0)
    priority: int = Field(default=0, ge=0)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    reason: str = ""
    source_hash: str | None = Field(default=None, max_length=128)
    trust_tier: TrustTier = TrustTier.repo_content
    cache_tier: CacheTier = CacheTier.semi_stable

    @model_validator(mode="after")
    def _set_candidate_id(self) -> ContextCandidate:
        if not self.candidate_id:
            self.candidate_id = _build_candidate_id(
                self.path,
                str(self.kind.value),
                str(self.source.value),
                str(self.relation.value),
            )
        return self


class ContextSelection(BaseModel):
    """A candidate selected for inclusion in the context packet."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    selected_tokens: int = Field(ge=0)
    include_mode: IncludeMode
    selection_reason: str = ""
    section_name: str = ""
    cache_tier: CacheTier = CacheTier.semi_stable


class ContextOmission(BaseModel):
    """A candidate omitted from the context packet."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    omission_reason: OmissionReason
    estimated_tokens: int = Field(ge=0)
    detail: str = ""


class ContextBudgetLedger(BaseModel):
    """Token budget accounting for the assembly plan."""

    model_config = ConfigDict(extra="forbid")

    requested_tokens: int = Field(default=0, ge=0)
    used_tokens: int = Field(default=0, ge=0)
    remaining_tokens: int = Field(default=0, ge=0)
    selection_overhead_tokens: int = Field(default=0, ge=0)
    compression_ratio: float | None = None


class ContextAssemblyWarning(BaseModel):
    """Safe warning produced during assembly planning."""

    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str = ""
    candidate_id: str | None = None


class ContextRenderedSection(BaseModel):
    """Optional contract for rendered section output."""

    model_config = ConfigDict(extra="forbid")

    section_name: str
    token_count: int = Field(ge=0)
    compression_applied: bool = False
    section_sha256: str | None = None


class ContextAssemblyPlan(BaseModel):
    """Full context assembly plan — candidates, selections, omissions, budget."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PLAN_SCHEMA_VERSION
    plan_id: str = ""
    request_sha256: str | None = None
    candidates: list[ContextCandidate] = Field(default_factory=list)
    selections: list[ContextSelection] = Field(default_factory=list)
    omissions: list[ContextOmission] = Field(default_factory=list)
    budget: ContextBudgetLedger = Field(default_factory=ContextBudgetLedger)
    warnings: list[ContextAssemblyWarning] = Field(default_factory=list)
    deterministic_inputs: dict[str, Any] = Field(default_factory=dict)
    plan_sha256: str = ""
    selection_sha256: str = ""
    generated_at: str | None = None

    @model_validator(mode="after")
    def _compute_hashes(self) -> ContextAssemblyPlan:
        # Compute selection hash from selections only
        sel_raw = _canonical_json([s.model_dump(mode="json") for s in self.selections])
        sel_hash = _sha256_hex(sel_raw)
        object.__setattr__(self, "selection_sha256", sel_hash)

        # Compute plan hash from stable fields (exclude volatile)
        plan_raw = _canonical_json({
            "schema_version": self.schema_version,
            "plan_id": "",  # not part of hash input
            "request_sha256": self.request_sha256,
            "candidates": [c.model_dump(mode="json") for c in self.candidates],
            "selections": [s.model_dump(mode="json") for s in self.selections],
            "omissions": [o.model_dump(mode="json") for o in self.omissions],
            "budget": self.budget.model_dump(mode="json"),
            "warnings": [w.model_dump(mode="json") for w in self.warnings],
            "deterministic_inputs": self.deterministic_inputs,
        })
        plan_hash = _sha256_hex(plan_raw)
        object.__setattr__(self, "plan_sha256", plan_hash)

        if not self.plan_id:
            object.__setattr__(self, "plan_id", plan_hash[:24])

        return self
