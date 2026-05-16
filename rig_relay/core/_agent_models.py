"""AgentLoop data models."""

from __future__ import annotations

from enum import StrEnum, auto

from pydantic import BaseModel

from rig_relay.core.tools.permissions import ToolPermission


class ToolExecutionResponse(StrEnum):
    SKIP = auto()
    EXECUTE = auto()


class ToolDecision(BaseModel):
    verdict: ToolExecutionResponse
    approval_type: ToolPermission
    feedback: str | None = None
