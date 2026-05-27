from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspaces_root: str = ".rig/relay/workspaces"
    workspaces_store_path: str = ".rig/relay/workspaces/registry"
    lifecycle_events_path: str = ".rig/relay/workspaces/lifecycle_events.jsonl"
    branch_prefix: str = "rig"
    max_active_workspaces: int = 4
    max_changed_files: int = 50
    stale_session_timeout_seconds: int = 300
    default_base_branch: str = "main"
    allow_destructive_reset: bool = False
    allow_primary_removal: bool = False


__all__ = ["WorkspaceConfig"]
