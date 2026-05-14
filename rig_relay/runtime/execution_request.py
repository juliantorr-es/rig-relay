"""Rig Relay ExecutionRequest Model — Ported from Rig domain/execution/models.py.

Defines the input specification for governed execution. This is the WHAT/HOW/
WHERE/WHY for a command that will run under an ExecutionLease.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: reimplement (Rig source: rig/domain/execution/models.py).
  Adaptations: Pydantic BaseModel with extra="forbid" instead of frozen dataclass;
  list[str] for argv (not shell strings, no shell=True); SHA256 request fingerprint;
  timeout in ms (not seconds); relay-native RuntimeCapabilityKind vocabulary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from rig_relay.runtime.models import RuntimeCapabilityKind


def _canonical_dump(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ExecutionRequest(BaseModel):
    """Request to execute a command in a governed context.

    Fields:
        request_id: Unique identifier for this request.
        argv: Command and arguments as a list of non-empty strings. No shell strings.
        cwd: Working directory path (string, not Path) for the execution.
        env_overlay: Environment variables to set/override for the execution.
        timeout_ms: Maximum execution time in milliseconds. Must be positive.
        purpose: Human-readable description of why this execution is needed.
        workspace_id: Optional workspace/lane context identifier.
        worktree_path: Optional git worktree path for isolated execution.
        requested_capabilities: Capability kinds this execution requires.
        request_sha256: Content hash computed from canonical JSON of all fields
            except request_id and request_sha256 itself.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.execution_request.v1"
    request_id: str
    argv: list[str]
    cwd: str
    env_overlay: dict[str, str] = {}
    timeout_ms: int
    purpose: str
    workspace_id: str | None = None
    worktree_path: str | None = None
    requested_capabilities: list[RuntimeCapabilityKind] = []
    request_sha256: str | None = None

    @field_validator("argv")
    @classmethod
    def _argv_must_be_non_empty(cls, argv: list[str]) -> list[str]:
        if not argv:
            raise ValueError("argv must be non-empty")
        for i, entry in enumerate(argv):
            if not entry or not entry.strip():
                raise ValueError(f"argv[{i}] must be a non-empty string")
        return argv

    @field_validator("cwd")
    @classmethod
    def _cwd_must_be_non_empty(cls, cwd: str) -> str:
        if not cwd or not cwd.strip():
            raise ValueError("cwd must be a non-empty string")
        return cwd

    @field_validator("timeout_ms")
    @classmethod
    def _timeout_must_be_positive(cls, timeout_ms: int) -> int:
        if timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {timeout_ms}")
        return timeout_ms

    @model_validator(mode="after")
    def _compute_request_sha256(self) -> ExecutionRequest:
        if self.request_sha256 is None:
            to_hash = self.model_dump(
                mode="json", exclude={"request_sha256", "request_id"}
            )
            raw = _canonical_dump(to_hash)
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            self.request_sha256 = f"sha256:{digest}"
        return self


__all__ = ["ExecutionRequest"]
