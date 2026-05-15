"""Context observation — content-light telemetry record for tool call correlation.

An observation records whether a tool call's target paths intersected with
the context packet's recommendations, collision warnings, dirty paths, or
do-not-touch lists. Observations are telemetry only — they never block
tool execution.

All fields are optional except the identity markers. Missing data produces
`context_available: false` rather than failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class ContextObservation(BaseModel):
    """Content-light observation correlating a tool call with context state.

    All fields are content-light: no file contents, diffs, secrets, or prompts.
    `observation_only` is always True — this record is never a policy decision.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "rig.context.observation.v1"
    session_id: str | None = None
    agent_id: str | None = None
    context_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str = ""
    target_paths: list[str] = Field(default_factory=list)
    mutation_class: str = "unknown"
    context_available: bool = False
    matched_recommended_context: bool = False
    overlapped_active_work: bool = False
    touched_dirty_path: bool = False
    touched_soft_warning: bool = False
    touched_hard_denied_path: bool = False
    tool_status: str = "pending"
    blocked_by_policy: bool = False
    observation_only: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
