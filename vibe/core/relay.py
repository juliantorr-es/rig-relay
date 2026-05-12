from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GitSafetyPolicy(BaseModel):
    """Policy for safe Git operations in Rig Relay."""

    model_config = ConfigDict(frozen=True)

    # These commands are strictly forbidden unless explicitly overridden
    forbidden_commands: list[str] = Field(
        default_factory=lambda: [
            "git reset",
            "git reset --hard",
            "git clean",
            "git checkout",  # when used for undo/destructive
            "git restore",  # when used for undo/destructive
            "git stash",
            "git rebase",
            "git merge",
            "git push --force",
        ]
    )

    commit_requires_user_request: bool = True
    push_requires_user_request: bool = True


class RelayReceiptMetadata(BaseModel):
    """Metadata for a task completion receipt, ingestible by Rig."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0.0"
    harness_name: str = "rig-relay"
    selected_model: str
    selected_provider: str
    selected_skill_id: str | None = None
    branch: str | None = None
    head: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    result_status: Literal["success", "failure", "interrupted", "unknown"] = "unknown"


class SkillManifest(BaseModel):
    """Typed manifest for Rig Relay skills."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    kind: Literal["task", "workflow", "policy", "custom"] = "task"
    description: str
    triggers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list, alias="allowed-tools")
    requires_worktree: bool = True
    requires_receipts: bool = False
    phases: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    source_attribution: str | None = None
