"""Mission context packet model for governed mission compilation.

DuckDB may be used later as a rebuildable analytical index, but the
packet itself remains a deterministic Pydantic model over canonical files.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SCHEMA_VERSION = "rig.mission_context_packet.v1"
_RECEIPT_SCHEMA_VERSION = "rig.mission_context_packet_receipt.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class MissionContextSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    kind: str
    size_bytes: int | None = Field(default=None, ge=0)
    note: str | None = None

    @field_validator("path", "sha256", "kind")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionContextDirtyFileState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    status: str
    before_sha256: str | None = None
    after_sha256: str | None = None
    byte_count: int | None = Field(default=None, ge=0)
    protected: bool = False

    @field_validator("path", "status")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionContextWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    message: str

    @field_validator("kind", "message")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionContextBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    message: str

    @field_validator("kind", "message")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionContextRequiredCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    required: bool = True

    @field_validator("name", "command")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionEnvelopeLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.mission_envelope.v1"
    mission_id: str
    fingerprint: str

    @field_validator("schema_version", "mission_id", "fingerprint")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value


class MissionContextPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    packet_id: str
    mission_id: str
    title: str
    created_at: str
    repo_root: str
    branch: str
    head: str
    mission_envelope: MissionEnvelopeLink | None = None
    source_refs: list[MissionContextSourceRef] = Field(default_factory=list)
    dirty_file_states: list[MissionContextDirtyFileState] = Field(default_factory=list)
    required_checks: list[MissionContextRequiredCheck] = Field(default_factory=list)
    warnings: list[MissionContextWarning] = Field(default_factory=list)
    blockers: list[MissionContextBlocker] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(default_factory=list)
    instruction_paths: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    content_policy: str = "content_light"
    handoff_required: bool = True

    @field_validator(
        "schema_version",
        "packet_id",
        "mission_id",
        "title",
        "created_at",
        "repo_root",
        "branch",
        "head",
        "content_policy",
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
    def _validate_str_list(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or not value.strip():
                raise ValueError("list items must be non-empty strings")
        return values

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


class MissionContextPacketReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = _RECEIPT_SCHEMA_VERSION
    packet_id: str
    mission_id: str
    mission_envelope_sha256: str
    packet_fingerprint: str
    packet_sha256: str
    index_backend: str
    duckdb_cache_path: str | None = None
    source_ref_count: int = Field(ge=0)
    dirty_file_count: int = Field(ge=0)
    required_check_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    created_at: str
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    @field_validator(
        "schema_version",
        "packet_id",
        "mission_id",
        "mission_envelope_sha256",
        "packet_fingerprint",
        "packet_sha256",
        "index_backend",
        "created_at",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must be a non-empty string")
        return value

    @field_validator("warnings", "blockers")
    @classmethod
    def _validate_messages(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or not value.strip():
                raise ValueError("list items must be non-empty strings")
        return values

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json", exclude_none=True))

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def build_mission_context_packet_receipt(
    packet: MissionContextPacket, *, created_at: str
) -> MissionContextPacketReceipt:
    return MissionContextPacketReceipt(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        mission_envelope_sha256=packet.mission_envelope.fingerprint
        if packet.mission_envelope is not None
        else "",
        packet_fingerprint=packet.fingerprint,
        packet_sha256=packet.fingerprint,
        index_backend="python",
        duckdb_cache_path=None,
        source_ref_count=len(packet.source_refs),
        dirty_file_count=len(packet.dirty_file_states),
        required_check_count=len(packet.required_checks),
        warning_count=len(packet.warnings),
        blocker_count=len(packet.blockers),
        created_at=created_at,
        warnings=[warning.message for warning in packet.warnings],
        blockers=[blocker.message for blocker in packet.blockers],
    )


__all__ = [
    "MissionContextBlocker",
    "MissionContextDirtyFileState",
    "MissionContextPacket",
    "MissionContextPacketReceipt",
    "MissionContextRequiredCheck",
    "MissionContextSourceRef",
    "MissionContextWarning",
    "MissionEnvelopeLink",
    "build_mission_context_packet_receipt",
]
