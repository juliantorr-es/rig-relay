"""Ralph lane contracts — one bounded mission = one isolated lane.

A Ralph lane is a dedicated branch/worktree isolation boundary.
Lanes are proposed from Ralph mission candidates under background policy.
No git commands, no worktree creation, no merge, no push in this phase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

LANE_VERSION = "rig.ralph_lane.v1"


class RalphLane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LANE_VERSION
    lane_id: str = Field(default_factory=lambda: str(uuid4()))
    mission_id: str = ""
    source_run_id: str | None = None
    source_scan_id: str | None = None
    source_candidate_id: str | None = None
    source_orchestrator_lane_ids: list[str] = Field(default_factory=list)
    source_report_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    branch_name: str = ""
    worktree_path: str = ""
    base_branch: str = ""
    base_head: str = ""
    status: str = "proposed"
    approval_state: str = "not_requested"
    execution_enabled: bool = False
    merge_enabled: bool = False
    push_enabled: bool = False
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    forbidden_capabilities: list[str] = Field(default_factory=list)
    required_validations: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    sealed_at: str | None = None
    latest_commit_sha: str | None = None
    review_bundle_sha256: str | None = None
    latest_event_id: str | None = None
    latest_receipt_sha256: str | None = None

    def sanitize_branch_name(self, slug: str, short_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug.lower())[:40]
        return f"ralph/{safe}-{short_id[:8]}"


__all__ = [
    "LANE_VERSION",
    "RalphLane",
]
