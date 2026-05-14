"""Content-light session event models for the Rig Console bridge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CodingTranscriptItemProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    turn_id: str = ""
    kind: str
    title: str
    body_text: str | None = None
    tool_name: str | None = None
    status: str | None = None
    created_at: str | None = None
    receipt_sha256: str | None = None
    runtime_result_sha256: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None


class CodingTranscriptProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible: bool = True
    session_id: str
    cursor: str | None = None
    items: list[CodingTranscriptItemProjection] = Field(default_factory=list)
    dropped_count: int = 0


class SubmitPromptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    status: str
    cursor: str | None = None
    refusal_reason: str | None = None


class CodingSessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    transcript: CodingTranscriptProjection


class CodingSessionEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = None
    items: list[CodingTranscriptItemProjection] = Field(default_factory=list)


__all__ = [
    "CodingSessionEvents",
    "CodingSessionSnapshot",
    "CodingTranscriptItemProjection",
    "CodingTranscriptProjection",
    "SubmitPromptResult",
]
