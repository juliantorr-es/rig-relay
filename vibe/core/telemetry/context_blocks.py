from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextBlockKind(StrEnum):
    SYSTEM_PROMPT = "system_prompt"
    TOOL_SCHEMA = "tool_schema"
    SKILL_INSTRUCTION = "skill_instruction"
    PROJECT_DOCTRINE = "project_doctrine"
    TASK_BRIEF = "task_brief"
    CONVERSATION_TAIL = "conversation_tail"
    TOOL_EXCERPT = "tool_excerpt"
    ARTIFACT_REFERENCE = "artifact_reference"
    REPO_STATE = "repo_state"
    FILE_SUMMARY = "file_summary"
    ERROR_STATE = "error_state"


class ContextBlockStability(StrEnum):
    STABLE = "stable"
    SEMI_STABLE = "semi_stable"
    DYNAMIC = "dynamic"
    EPHEMERAL = "ephemeral"


class ContextBlock(BaseModel):
    schema_version: str = "rig.relay.context_block.v1"
    block_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: ContextBlockKind
    stability: ContextBlockStability
    cacheable: bool
    content: str
    byte_size: int
    estimated_tokens: int
    fingerprint: str
    source_event_ids: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextAssemblyReport(BaseModel):
    schema_version: str = "rig.relay.context_assembly.v1"
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    entrypoint: str | None = None
    model: str | None = None
    blocks: list[ContextBlock]
    stable_prefix_fingerprint: str
    dynamic_suffix_fingerprint: str
    total_bytes: int
    total_estimated_tokens: int
    stable_prefix_bytes: int
    dynamic_suffix_bytes: int
    cache_candidate_bytes: int
    largest_blocks: list[dict[str, Any]]
    optimization_hints: list[str]


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple heuristic (~4 chars per token).
    
    This is approximate and used for observational reporting only.
    """
    return len(text) // 4


def fingerprint_text(text: str) -> str:
    """Return a SHA256 fingerprint of the text."""
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def classify_block_stability(kind: ContextBlockKind) -> tuple[ContextBlockStability, bool]:
    """Return default (stability, cacheable) for a given block kind."""
    match kind:
        case ContextBlockKind.SYSTEM_PROMPT | ContextBlockKind.TOOL_SCHEMA:
            return ContextBlockStability.STABLE, True
        case ContextBlockKind.SKILL_INSTRUCTION | ContextBlockKind.PROJECT_DOCTRINE:
            return ContextBlockStability.SEMI_STABLE, True
        case ContextBlockKind.TASK_BRIEF | ContextBlockKind.ARTIFACT_REFERENCE:
            return ContextBlockStability.DYNAMIC, True
        case ContextBlockKind.CONVERSATION_TAIL | ContextBlockKind.REPO_STATE | ContextBlockKind.FILE_SUMMARY:
            return ContextBlockStability.DYNAMIC, False
        case ContextBlockKind.TOOL_EXCERPT | ContextBlockKind.ERROR_STATE:
            return ContextBlockStability.EPHEMERAL, False
        case _:
            return ContextBlockStability.EPHEMERAL, False
