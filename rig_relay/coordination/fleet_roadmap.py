"""Fleet Roadmap & Sprint Models.

Content-light models for the orchestrator agent to plan roadmaps,
scope sprints, and schedule missions on a preproduction branch.

No raw file contents, no diffs, no patches, no secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


_SCHEMA_ROADMAP = "rig.fleet.roadmap.v1"
_SCHEMA_SPRINT = "rig.fleet.sprint.v1"
_SCHEMA_MISSION = "rig.fleet.mission.v1"


class FleetMission(BaseModel):
    """A single mission in a sprint — the unit of work for one subagent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_MISSION
    mission_id: str
    sprint_id: str
    title: str
    description: str
    agent_profile: str  # cleaner, builder, bug-exterminator, explore
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    status: Literal["planned", "queued", "running", "completed", "failed", "blocked"] = "planned"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    output_sha256: str | None = None
    touched_paths: list[str] = Field(default_factory=list)


class FleetSprint(BaseModel):
    """A sprint: a collection of missions targeting a preproduction branch."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_SPRINT
    sprint_id: str
    roadmap_id: str
    title: str
    goal: str
    preproduction_branch: str
    missions: list[FleetMission] = Field(default_factory=list)
    status: Literal["draft", "active", "completed", "cancelled"] = "draft"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    completed_at: str | None = None


class FleetRoadmap(BaseModel):
    """A roadmap: the user's desired scope, stack, and sprint plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_ROADMAP
    roadmap_id: str
    title: str
    scope: str  # User's description of what to build
    desired_stack: str  # Languages, frameworks, tools
    repository_url: str | None = None
    preproduction_branch_prefix: str = "rig-relay/sprint"
    sprints: list[FleetSprint] = Field(default_factory=list)
    status: Literal["draft", "active", "completed", "cancelled"] = "draft"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
