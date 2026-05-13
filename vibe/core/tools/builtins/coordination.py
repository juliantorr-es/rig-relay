from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from vibe.core.coordination import (
    CoordinationConflict,
    CoordinationSession,
    CoordinationStore,
)
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent, ToolStreamEvent


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
    store_root: Path = Field(default_factory=lambda: Path.cwd() / ".build" / "rig-relay" / "coordination")


class Coordination(
    BaseTool[CoordinationArgs, CoordinationResult, CoordinationToolConfig, BaseToolState],
    ToolUIData[CoordinationArgs, CoordinationResult],
):
    description: ClassVar[str] = "Shared coordination plane for claims, leases, and artifacts."

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
            return ctx.session_dir.parent / ".build" / "rig-relay" / "coordination"
        return Path.cwd() / ".build" / "rig-relay" / "coordination"

    async def run(
        self, args: CoordinationArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | CoordinationResult, None]:
        store = CoordinationStore(self.config.store_root)

        match args.action:
            case "register_session":
                yield self._register_session(store, args)
            case "heartbeat":
                yield self._heartbeat(store, args)
            case "claim_task":
                yield self._claim_task(store, args)
            case "reserve_paths":
                yield self._reserve_paths(store, args)
            case "release_paths":
                yield self._release_paths(store, args)
            case "publish_artifact":
                yield self._publish_artifact(store, args)
            case "report_conflict":
                yield self._report_conflict(store, args)
            case "read_state_projection":
                yield CoordinationResult(
                    action=args.action,
                    response=store.read_state_projection().model_dump(exclude_none=True),
                )
            case "release_task":
                yield self._release_task(store, args)
            case "request_handoff":
                yield self._request_handoff(store, args)
            case "mark_lease_stale":
                yield self._mark_lease_stale(store, args)
            case _:
                raise ToolError(f"Unknown coordination action: {args.action}")

    def resolve_permission(self, args: CoordinationArgs) -> None:
        return None

    @staticmethod
    def _register_session(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.status is None:
            raise ToolError("session_id and status are required")
        session = store.register_session(
            CoordinationSession(
                session_id=args.session_id,
                task_id=args.task_id,
                status=args.status,
            )
        )
        return CoordinationResult(
            action=args.action, response=session.model_dump(exclude_none=True)
        )

    @staticmethod
    def _heartbeat(store: CoordinationStore, args: CoordinationArgs) -> CoordinationResult:
        if args.session_id is None or args.status is None:
            raise ToolError("session_id and status are required")
        heartbeat = store.heartbeat(
            session_id=args.session_id,
            task_id=args.task_id,
            status=args.status,
            reserved_paths=args.reserved_paths,
        )
        return CoordinationResult(
            action=args.action, response=heartbeat.model_dump(exclude_none=True)
        )

    @staticmethod
    def _claim_task(store: CoordinationStore, args: CoordinationArgs) -> CoordinationResult:
        if (
            args.session_id is None
            or args.task_id is None
            or args.claim_kind is None
            or args.ttl_seconds is None
        ):
            raise ToolError(
                "session_id, task_id, claim_kind, ttl_seconds are required"
            )
        result = store.claim_task(
            session_id=args.session_id,
            task_id=args.task_id,
            claim_kind=args.claim_kind,
            ttl_seconds=args.ttl_seconds,
            scope=args.scope,
        )
        return CoordinationResult(action=args.action, response=result.model_dump(exclude_none=True))

    @staticmethod
    def _reserve_paths(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if (
            args.session_id is None
            or args.task_id is None
            or args.mode is None
            or args.ttl_seconds is None
        ):
            raise ToolError("session_id, task_id, mode, ttl_seconds are required")
        result = store.reserve_paths(
            session_id=args.session_id,
            task_id=args.task_id,
            mode=args.mode,
            paths=args.paths,
            ttl_seconds=args.ttl_seconds,
        )
        return CoordinationResult(action=args.action, response=result.model_dump(exclude_none=True))

    @staticmethod
    def _release_paths(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.task_id is None:
            raise ToolError("session_id and task_id are required")
        store.release_paths(
            session_id=args.session_id, task_id=args.task_id, paths=args.paths
        )
        return CoordinationResult(action=args.action, response={"released": True})

    @staticmethod
    def _publish_artifact(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if (
            args.session_id is None
            or args.artifact_kind is None
            or args.artifact_uri is None
            or args.artifact_sha256 is None
        ):
            raise ToolError(
                "session_id, artifact_kind, artifact_uri, artifact_sha256 are required"
            )
        artifact = store.publish_artifact(
            session_id=args.session_id,
            task_id=args.task_id,
            artifact_kind=args.artifact_kind,
            artifact_uri=args.artifact_uri,
            artifact_sha256=args.artifact_sha256,
            schema_id=args.schema_id,
        )
        return CoordinationResult(action=args.action, response=artifact.model_dump(exclude_none=True))

    @staticmethod
    def _report_conflict(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.conflict_id is None:
            raise ToolError("session_id and conflict_id are required")
        conflict = store.report_conflict(
            CoordinationConflict(
                conflict_id=args.conflict_id,
                kind="coordination_conflict",
                session_id=args.session_id,
                other_session_id=args.other_session_id,
                task_id=args.task_id,
                paths=args.paths,
                recommended_resolution=args.recommended_resolution,
            )
        )
        return CoordinationResult(action=args.action, response=conflict.model_dump(exclude_none=True))

    @staticmethod
    def _release_task(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.task_id is None:
            raise ToolError("session_id and task_id are required")
        store.release_task(session_id=args.session_id, task_id=args.task_id)
        return CoordinationResult(action=args.action, response={"released": True})

    @staticmethod
    def _request_handoff(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.other_session_id is None:
            raise ToolError("session_id and target_session_id are required")
        result = store.request_handoff(
            session_id=args.session_id,
            target_session_id=args.other_session_id,
            task_id=args.task_id,
            scope=args.scope,
        )
        return CoordinationResult(action=args.action, response=result)

    @staticmethod
    def _mark_lease_stale(
        store: CoordinationStore, args: CoordinationArgs
    ) -> CoordinationResult:
        if args.session_id is None or args.task_id is None:
            raise ToolError("session_id and task_id are required")
        store.mark_lease_stale(
            session_id=args.session_id,
            task_id=args.task_id,
            reason=args.recommended_resolution or "manual",
        )
        return CoordinationResult(action=args.action, response={"marked_stale": True})
