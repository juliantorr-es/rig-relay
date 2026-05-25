from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.git_index_operations import (
    get_current_branch,
    has_conflicts,
    is_detached_head,
    prepare_index_for_checkpoint,
)
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.types import ToolStreamEvent


class PrepareCheckpointPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        description="Repository-relative file path to stage for checkpoint."
    )
    change_kind: Literal["add", "modify", "delete"] = Field(
        default="modify", description="Kind of change being prepared."
    )
    expected_worktree_sha256: str | None = Field(
        default=None,
        description="sha256:<hex> of file bytes as they exist right now. "
        "Required for add and modify. Must match current worktree bytes exactly.",
    )
    expected_absent: bool = Field(
        default=False,
        description="Set true for delete operations. File must not exist at path.",
    )


class PrepareCheckpointArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[PrepareCheckpointPath] = Field(
        description="Paths with expected content hashes to stage for checkpoint. "
        "Each path must be within admitted mission scope."
    )
    session_id: str | None = Field(
        default=None, description="Session identifier. Auto-populated."
    )
    task_id: str | None = Field(
        default=None, description="Task identifier. Auto-populated."
    )


class PrepareCheckpointResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    prepared_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    pre_index_tree_digest: str | None = None
    post_index_tree_digest: str | None = None
    index_mutation_performed: bool = False
    scope_verified: bool = False
    dirty_guard_verified: bool = False
    reservation_verified: bool = False
    refusal_reason: str | None = None
    error_kind: str | None = None
    suggested_next_action: str | None = None
    receipt_sha256: str | None = None


class PrepareCheckpointConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK


class PrepareCheckpoint(
    BaseTool[
        PrepareCheckpointArgs,
        PrepareCheckpointResult,
        PrepareCheckpointConfig,
        BaseToolState,
    ]
):
    description: ClassVar[str] = (
        "Prepare admitted files for a governed checkpoint by staging them "
        "in the Git index. Verifies mission scope, dirty-file protection, "
        "coordination reservations, and expected file-state hashes before staging. "
        "Supports add, modify, and delete operations. "
        "After preparation, run validation and then checkpoint to commit the "
        "prepared index. "
        "This tool does NOT push, merge, or perform any destructive Git operations."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.MUTATES_GIT_STATE

    async def run(
        self, args: PrepareCheckpointArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | PrepareCheckpointResult, None]:
        from rig_relay.coordination.store import CoordinationStore

        worktree_root = (
            ctx.workspace_root.resolve() if ctx and ctx.workspace_root else Path.cwd()
        )

        mission_auth = (
            getattr(ctx.tool_runtime, "_mission_authority", None) if ctx else None
        )

        def _is_protected_branch(branch: str | None) -> bool:
            return branch in {"main", "master"}

        def _is_path_in_scope(path: str) -> bool:
            if mission_auth is None:
                return False
            return mission_auth.is_path_in_write_scope(path)

        def _is_protected_dirty(path: str) -> bool:
            try:
                from rig_relay.core.guard import get_guard

                guard = get_guard()
                if guard.captured_at is None:
                    return False
                return guard.is_protected(path)
            except Exception:
                return False

        def _has_active_write_reservation(path: str) -> bool:
            try:
                store_root = worktree_root / ".build" / "rig-relay" / "coordination"
                store = CoordinationStore(store_root)
                projection = store.read_state_projection()
                for _key, reservation in projection.active_path_reservations.items():
                    if reservation.status != "active":
                        continue
                    if reservation.mode != "write":
                        continue
                    if (
                        reservation.session_id == args.session_id
                        and reservation.task_id == args.task_id
                    ):
                        continue
                    for reserved_path in reservation.paths:
                        if path == reserved_path or path.startswith(
                            reserved_path + "/"
                        ):
                            return True
                        if reserved_path.startswith(path + "/"):
                            return True
                return False
            except Exception:
                return False

        branch = get_current_branch(worktree_root)
        detached = is_detached_head(worktree_root)
        conflicted = has_conflicts(worktree_root)

        prep = prepare_index_for_checkpoint(
            worktree_root=str(worktree_root),
            branch=branch,
            is_detached=detached,
            has_conflicts_flag=conflicted,
            is_protected_branch_func=_is_protected_branch,
            is_path_in_scope_func=_is_path_in_scope,
            is_protected_dirty_func=_is_protected_dirty,
            has_active_write_reservation_func=_has_active_write_reservation,
            preparation_paths=[
                {
                    "path": p.path,
                    "change_kind": p.change_kind,
                    "expected_worktree_sha256": p.expected_worktree_sha256,
                    "expected_absent": p.expected_absent,
                }
                for p in args.paths
            ],
        )

        result = PrepareCheckpointResult(
            ok=prep.ok,
            prepared_paths=prep.prepared_paths,
            excluded_paths=prep.excluded_paths,
            pre_index_tree_digest=prep.pre_index_tree_digest,
            post_index_tree_digest=prep.post_index_tree_digest,
            index_mutation_performed=prep.ok,
            scope_verified=prep.ok,
            dirty_guard_verified=prep.ok,
            reservation_verified=prep.ok,
            refusal_reason=prep.refusal_detail,
            error_kind=prep.refusal_code,
            suggested_next_action=(
                "Run validation for the prepared index, then call checkpoint."
                if prep.ok
                else (
                    "Correct the listed refusal and create a new preparation request."
                    if prep.refusal_code
                    else None
                )
            ),
        )

        # ── Persist durable preparation receipt ───────────────────────
        receipt_sha256: str | None = None
        if result.ok and result.post_index_tree_digest:
            try:
                from rig_relay.governance.auth_receipts import (
                    generate_preparation_receipt,
                    persist_preparation_receipt,
                )

                branch_name = get_current_branch(worktree_root)
                receipt = generate_preparation_receipt(
                    mission_id=getattr(mission_auth, "mission_id", None)
                    if mission_auth
                    else None,
                    authority_provenance_sha256=getattr(
                        mission_auth, "provenance_sha256", None
                    )
                    if mission_auth
                    else None,
                    claim_id=getattr(mission_auth, "claim_id", None)
                    if mission_auth
                    else None,
                    session_id=args.session_id or "",
                    task_id=args.task_id or "",
                    branch=branch_name or "",
                    prepared_paths=prep.prepared_paths,
                    change_kinds=[
                        p.change_kind
                        for p in args.paths
                        if p.path in prep.prepared_paths
                    ],
                    expected_worktree_sha256_values=[
                        p.expected_worktree_sha256 or ""
                        for p in args.paths
                        if p.path in prep.prepared_paths and p.expected_worktree_sha256
                    ],
                    pre_index_tree_digest=prep.pre_index_tree_digest,
                    post_index_tree_digest=prep.post_index_tree_digest,
                    index_mutation_performed=True,
                    worktree_root=str(worktree_root),
                )
                persisted = persist_preparation_receipt(receipt)
                if persisted is not None:
                    receipt_sha256 = receipt["receipt_sha256"]
            except Exception:
                yield PrepareCheckpointResult(
                    ok=False,
                    receipt_sha256=None,
                    pre_index_tree_digest=prep.pre_index_tree_digest,
                    post_index_tree_digest=prep.post_index_tree_digest,
                    prepared_paths=prep.prepared_paths,
                    index_mutation_performed=prep.index_mutation_performed,
                    refusal_reason="receipt_persistence_failed",
                    error_kind="receipt_persistence_failed",
                    suggested_next_action=(
                        "Preparation receipt could not be persisted. "
                        "The index may already be staged. Inspect git status "
                        "and re-prepare if needed before checkpoint."
                    ),
                )
                return

        result.receipt_sha256 = receipt_sha256

        yield result


__all__ = [
    "PrepareCheckpoint",
    "PrepareCheckpointArgs",
    "PrepareCheckpointConfig",
    "PrepareCheckpointPath",
    "PrepareCheckpointResult",
]
