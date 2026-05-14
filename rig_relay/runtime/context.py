from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.runtime_context.v1"
    session_id: str
    task_id: str
    lane_id: str | None = None
    workspace_id: str | None = None
    worktree_path: str | None = None
    repo_root: str | None = None
    coordination_scope: str | None = None
    receipt_index_path: str | None = None
    dirty_policy: str | None = None
    resolved_from: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimeContextResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.runtime_context_resolution.v1"
    status: str
    context: RuntimeContext | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
