"""Mission envelope model for governed runtime context."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class MissionDirtySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracked_modified_count: int = Field(ge=0)
    untracked_count: int = Field(ge=0)
    protected_dirty_count: int = Field(ge=0)


class MissionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.mission_envelope.v1"
    mission_id: str
    title: str
    created_at: str
    repo_root: str
    branch: str
    head: str
    dirty_summary: MissionDirtySummary
    allowed_paths: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(default_factory=list)
    instruction_paths: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    handoff_required: bool
    adr_id: str | None = None
    sprint_id: str | None = None

    @field_validator(
        "schema_version",
        "mission_id",
        "title",
        "created_at",
        "repo_root",
        "branch",
        "head",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value

    @field_validator(
        "allowed_paths", "protected_paths", "instruction_paths", "acceptance_checks"
    )
    @classmethod
    def _validate_lists(cls, values: list[str]) -> list[str]:
        for index, value in enumerate(values):
            if not value or not value.strip():
                raise ValueError(f"item {index} must be a non-empty string")
        return values

    @field_validator("adr_id", "sprint_id")
    @classmethod
    def _optional_ids(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional id must be a non-empty string when provided")
        return value

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


__all__ = ["MissionDirtySummary", "MissionEnvelope"]
