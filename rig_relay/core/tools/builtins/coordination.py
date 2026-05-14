from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from rig_relay.coordination.tool import execute_coordination_action, resolve_store_root
from rig_relay.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolCallEvent, ToolResultEvent, ToolStreamEvent


class CoordinationArgs(BaseModel):
    action: Literal[
        "claim_task",
        "reserve_paths",
        "heartbeat",
        "publish_artifact",
        "read_state_projection",
        "release_task",
        "release_paths",
        "report_conflict",
        "request_handoff",
        "mark_lease_stale",
        "register_session",
    ]
    session_id: str | None = None
    task_id: str | None = None
    claim_kind: str | None = None
    ttl_seconds: int | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["read", "write"] | None = None
    paths: list[str] = Field(default_factory=list)
    status: str | None = None
    current_step: str | None = None
    reserved_paths: list[str] = Field(default_factory=list)
    artifact_kind: str | None = None
    artifact_uri: str | None = None
    artifact_sha256: str | None = None
    schema_id: str | None = None
    conflict_id: str | None = None
    other_session_id: str | None = None
    recommended_resolution: str | None = None


class CoordinationResult(BaseModel):
    ok: bool = True
    action: str
    response: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CoordinationToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    store_root: Path = Field(
        default_factory=lambda: Path.cwd() / ".build" / "rig-relay" / "coordination"
    )


class Coordination(
    BaseTool[
        CoordinationArgs, CoordinationResult, CoordinationToolConfig, BaseToolState
    ],
    ToolUIData[CoordinationArgs, CoordinationResult],
):
    description: ClassVar[str] = (
        "Shared coordination plane for claims, leases, and artifacts."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        args = event.args
        if isinstance(args, CoordinationArgs):
            return ToolCallDisplay(summary=f"Coordination: {args.action}")
        return ToolCallDisplay(summary="Coordination")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        result = event.result
        if isinstance(result, CoordinationResult):
            return ToolResultDisplay(success=result.ok, message=result.action)
        return ToolResultDisplay(success=True, message="Coordination complete")

    @classmethod
    def get_status_text(cls) -> str:
        return "Running coordination action"

    @staticmethod
    def _store_root(ctx: InvokeContext | None) -> Path:
        if ctx and ctx.session_dir is not None:
            return resolve_store_root(
                Path.cwd() / ".build" / "rig-relay" / "coordination", ctx.session_dir
            )
        return Path.cwd() / ".build" / "rig-relay" / "coordination"

    async def run(
        self, args: CoordinationArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | CoordinationResult, None]:
        try:
            result = execute_coordination_action(
                store_root=self.config.store_root,
                action_data=args.model_dump(exclude_none=True),
            )
        except ValueError as e:
            raise ToolError(str(e)) from e
        yield CoordinationResult(
            ok=result.ok,
            action=result.action,
            response=result.response,
            warnings=result.warnings,
        )

    def resolve_permission(self, args: CoordinationArgs) -> None:
        return None
