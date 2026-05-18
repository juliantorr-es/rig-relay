"""Context models — Pydantic models for context request, packet, and receipt."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContextMode(StrEnum):
    MAP = "map"
    PACKET = "packet"
    HANDOFF = "handoff"
    COLLISION = "collision"
    SYMBOLS = "symbols"
    DIGEST = "digest"


class CompressionMode(StrEnum):
    NONE = "none"
    LIGHT = "light"
    SYMBOL_SUBSTITUTION = "symbol_substitution"
    AGGRESSIVE = "aggressive"


class DetailLevel(StrEnum):
    SUMMARY = "summary"
    STANDARD = "standard"
    DEEP = "deep"


class OutputFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    CONTEXT_PACKET = "context_packet"


class ContextScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    include_tests: bool = True
    include_docs: bool = True
    include_receipts: bool = True
    include_other_agents: bool = True


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int = 60000
    compression: CompressionMode = CompressionMode.NONE
    detail: DetailLevel = DetailLevel.STANDARD


class ContextFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_git_status: bool = True
    require_worktree_scan: bool = True
    require_receipt_scan: bool = False


class ContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: OutputFormat = OutputFormat.JSON
    include_resource_links: bool = True


class ContextRequest(BaseModel):
    """Request model for rig.get_context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.context_request.v1"
    mission_id: str | None = None
    agent_id: str | None = None
    mode: ContextMode = ContextMode.MAP
    scope: ContextScope = Field(default_factory=ContextScope)
    budget: ContextBudget = Field(default_factory=ContextBudget)
    freshness: ContextFreshness = Field(default_factory=ContextFreshness)
    output: ContextOutput = Field(default_factory=ContextOutput)


class RepoInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    head: str
    branch: str
    dirty_summary: dict[str, int] = Field(
        default_factory=lambda: {"modified": 0, "untracked": 0, "staged": 0}
    )


class SubsystemEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    paths: list[str]
    entry_points: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    docs: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)


class ActiveLane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = ""
    mission_id: str = ""
    worktree_path: str = ""
    claimed_paths: list[str] = Field(default_factory=list)
    dirty_paths: list[str] = Field(default_factory=list)
    status: str = "unknown"


class CollisionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    claimed_by: str = ""
    reason: str = ""


class SymbolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str = ""
    paths: list[str] = Field(default_factory=list)


class ReceiptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = ""
    path: str = ""
    sha256: str = ""


class PathRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = ""
    reason: str = ""


class ContextPacket(BaseModel):
    """Output model for rig.get_context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.context_packet.v1"
    context_id: str = Field(default_factory=lambda: f"ctx_{uuid4().hex[:12]}")
    mode: ContextMode = ContextMode.MAP
    request_sha256: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    repo: RepoInfo = Field(default_factory=RepoInfo)
    subsystems: list[SubsystemEntry] = Field(default_factory=list)
    active_work: dict[str, Any] = Field(
        default_factory=lambda: {"lanes": [], "collision_warnings": []}
    )
    symbol_map: dict[str, Any] = Field(
        default_factory=lambda: {"aliases": {}, "symbols": []}
    )
    receipts: list[ReceiptEntry] = Field(default_factory=list)
    recommended_context: list[PathRecommendation] = Field(default_factory=list)
    do_not_touch: list[PathRecommendation] = Field(default_factory=list)
    summary_text: str = ""
    assembly_plan_summary: dict[str, Any] = Field(default_factory=dict)
    canonical_packet_sha256: str | None = None
    optimized_packet_sha256: str | None = None
    substitution_table_sha256: str | None = None
    duration_ms: float = 0.0
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class ContextEnvelopeReceipt(BaseModel):
    """Receipt produced by ContextCompiler.build_envelope().

    Carries the rendered prompt string, section count, and a receipt
    fingerprint. Content-light: no raw file contents or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    rendered_prompt: str = ""
    section_count: int = 0
    estimated_tokens: int = 0
    dirty_file_count: int = 0
    collision_warnings: int = 0
    receipt_sha256: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    symbol_manifest: Any | None = None


class ContextReceipt(BaseModel):
    """Receipt for rig.get_context. Content-light."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "rig.context.receipt.v1"
    context_id: str = ""
    mode: str = "map"
    request_sha256: str = ""
    packet_sha256: str = ""
    subsystem_count: int = 0
    active_lane_count: int = 0
    collision_warning_count: int = 0
    receipt_count: int = 0
    dirty_file_count: int = 0
    symbol_count: int = 0
    estimated_tokens: int = 0
    open_finding_count: int = 0
    stale_finding_count: int = 0
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: float = 0.0
