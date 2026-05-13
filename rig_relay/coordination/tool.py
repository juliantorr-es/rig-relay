from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from rig_relay.coordination.models import CoordinationConflict, CoordinationSession
from rig_relay.coordination.store import CoordinationStore


class CoordinationArgsData(BaseModel):
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


class CoordinationResultData(BaseModel):
    ok: bool = True
    action: str
    response: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def resolve_store_root(store_root: Path, session_dir: Path | None) -> Path:
    if session_dir is not None:
        return session_dir.parent / ".build" / "rig-relay" / "coordination"
    return store_root


def execute_coordination_action(
    *, store_root: Path, action_data: dict[str, Any]
) -> CoordinationResultData:
    args = CoordinationArgsData.model_validate(action_data)
    store = CoordinationStore(store_root)

    result: CoordinationResultData
    match args.action:
        case "register_session":
            result = _register_session(store, args)
        case "heartbeat":
            result = _heartbeat(store, args)
        case "claim_task":
            result = _claim_task(store, args)
        case "reserve_paths":
            result = _reserve_paths(store, args)
        case "release_paths":
            result = _release_paths(store, args)
        case "publish_artifact":
            result = _publish_artifact(store, args)
        case "report_conflict":
            result = _report_conflict(store, args)
        case "read_state_projection":
            result = CoordinationResultData(
                action=args.action,
                response=store.read_state_projection().model_dump(exclude_none=True),
            )
        case "release_task":
            result = _release_task(store, args)
        case "request_handoff":
            result = _request_handoff(store, args)
        case "mark_lease_stale":
            result = _mark_lease_stale(store, args)
        case _:
            raise ValueError(f"Unknown coordination action: {args.action}")
    return result


def _register_session(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.status is None:
        raise ValueError("session_id and status are required")
    session = store.register_session(
        CoordinationSession(
            session_id=args.session_id, task_id=args.task_id, status=args.status
        )
    )
    return CoordinationResultData(
        action=args.action, response=session.model_dump(exclude_none=True)
    )


def _heartbeat(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.status is None:
        raise ValueError("session_id and status are required")
    heartbeat = store.heartbeat(
        session_id=args.session_id,
        task_id=args.task_id,
        status=args.status,
        reserved_paths=args.reserved_paths,
    )
    return CoordinationResultData(
        action=args.action, response=heartbeat.model_dump(exclude_none=True)
    )


def _claim_task(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if (
        args.session_id is None
        or args.task_id is None
        or args.claim_kind is None
        or args.ttl_seconds is None
    ):
        raise ValueError("session_id, task_id, claim_kind, ttl_seconds are required")
    result = store.claim_task(
        session_id=args.session_id,
        task_id=args.task_id,
        claim_kind=args.claim_kind,
        ttl_seconds=args.ttl_seconds,
        scope=args.scope,
    )
    return CoordinationResultData(
        action=args.action, response=result.model_dump(exclude_none=True)
    )


def _reserve_paths(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if (
        args.session_id is None
        or args.task_id is None
        or args.mode is None
        or args.ttl_seconds is None
    ):
        raise ValueError("session_id, task_id, mode, ttl_seconds are required")
    result = store.reserve_paths(
        session_id=args.session_id,
        task_id=args.task_id,
        mode=args.mode,
        paths=args.paths,
        ttl_seconds=args.ttl_seconds,
    )
    return CoordinationResultData(
        action=args.action, response=result.model_dump(exclude_none=True)
    )


def _release_paths(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.task_id is None:
        raise ValueError("session_id and task_id are required")
    store.release_paths(
        session_id=args.session_id, task_id=args.task_id, paths=args.paths
    )
    return CoordinationResultData(action=args.action, response={"released": True})


def _publish_artifact(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if (
        args.session_id is None
        or args.artifact_kind is None
        or args.artifact_uri is None
        or args.artifact_sha256 is None
    ):
        raise ValueError(
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
    return CoordinationResultData(
        action=args.action, response=artifact.model_dump(exclude_none=True)
    )


def _report_conflict(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.conflict_id is None:
        raise ValueError("session_id and conflict_id are required")
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
    return CoordinationResultData(
        action=args.action, response=conflict.model_dump(exclude_none=True)
    )


def _release_task(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.task_id is None:
        raise ValueError("session_id and task_id are required")
    store.release_task(session_id=args.session_id, task_id=args.task_id)
    return CoordinationResultData(action=args.action, response={"released": True})


def _request_handoff(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.other_session_id is None:
        raise ValueError("session_id and target_session_id are required")
    result = store.request_handoff(
        session_id=args.session_id,
        target_session_id=args.other_session_id,
        task_id=args.task_id,
        scope=args.scope,
    )
    return CoordinationResultData(action=args.action, response=result)


def _mark_lease_stale(
    store: CoordinationStore, args: CoordinationArgsData
) -> CoordinationResultData:
    if args.session_id is None or args.task_id is None:
        raise ValueError("session_id and task_id are required")
    store.mark_lease_stale(
        session_id=args.session_id,
        task_id=args.task_id,
        reason=args.recommended_resolution or "manual",
    )
    return CoordinationResultData(action=args.action, response={"marked_stale": True})


__all__ = [
    "CoordinationArgsData",
    "CoordinationResultData",
    "execute_coordination_action",
    "resolve_store_root",
]
