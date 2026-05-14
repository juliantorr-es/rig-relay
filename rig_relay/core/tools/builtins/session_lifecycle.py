from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import ClassVar, Literal, cast

from pydantic import BaseModel, Field

from rig_relay.evidence.session_lifecycle import (
    ClassifiedArtifact,
    CompactionResult,
    DeletedArtifact,
    Refusal,
    SessionRetentionPolicy,
    finalize_session_storage,
)
from rig_relay.governance.mission_envelope import MissionEnvelope
from rig_relay.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from rig_relay.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, InvokeContext
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolStreamEvent


class SessionRetentionPolicyArgs(BaseModel):
    allow_prune: bool = False
    max_delete_mb: float = 0.0
    older_than_days: int = 30
    archive_dir: Path | None = None


class SessionFinalizeArgs(BaseModel):
    session_id: str
    sessions_root: Path
    mission_envelope: MissionEnvelope | None = None
    policy: SessionRetentionPolicyArgs = Field(
        default_factory=SessionRetentionPolicyArgs
    )
    allow_compaction: bool = True
    allow_prune: bool = False
    write_receipt: bool = True
    reason: str = "session_end"


class SessionFinalizeCompactionResult(BaseModel):
    source_path: str
    output_path: str | None
    size_bytes_before: int
    size_bytes_after: int
    category: str
    status: str
    reason: str


class SessionFinalizeArtifact(BaseModel):
    path: str
    size_bytes: int
    category: str


class SessionFinalizeRefusal(BaseModel):
    path: str
    category: str
    reason: str


class SessionFinalizeDeletedArtifact(BaseModel):
    path: str
    size_bytes: int
    category: str
    reason: str


class SessionFinalizeResultModel(BaseModel):
    session_id: str
    scanned_files: int
    total_bytes_before: int
    total_bytes_after: int
    compacted_files: tuple[SessionFinalizeCompactionResult, ...]
    protected_files: tuple[SessionFinalizeArtifact, ...]
    refused_files: tuple[SessionFinalizeRefusal, ...]
    prune_candidates: tuple[SessionFinalizeArtifact, ...]
    deleted_files: tuple[SessionFinalizeDeletedArtifact, ...]
    manifest_path: str | None
    receipt_path: str | None
    status: Literal["ok", "partial", "refused", "error"]
    warnings: tuple[str, ...] = ()


class SessionLifecycleFinalizeConfig(BaseToolConfig):
    pass


def _artifact_model(artifact: ClassifiedArtifact) -> SessionFinalizeArtifact:
    return SessionFinalizeArtifact(
        path=str(artifact.path),
        size_bytes=artifact.size_bytes,
        category=artifact.category.value,
    )


def _compaction_model(result: CompactionResult) -> SessionFinalizeCompactionResult:
    return SessionFinalizeCompactionResult(
        source_path=str(result.source_path),
        output_path=str(result.output_path) if result.output_path else None,
        size_bytes_before=result.size_bytes_before,
        size_bytes_after=result.size_bytes_after,
        category=result.category.value,
        status=result.status,
        reason=result.reason,
    )


def _refusal_model(refusal: Refusal) -> SessionFinalizeRefusal:
    return SessionFinalizeRefusal(
        path=str(refusal.path), category=refusal.category.value, reason=refusal.reason
    )


def _deleted_model(deleted: DeletedArtifact) -> SessionFinalizeDeletedArtifact:
    return SessionFinalizeDeletedArtifact(
        path=str(deleted.path),
        size_bytes=deleted.size_bytes,
        category=deleted.category.value,
        reason=deleted.reason,
    )


class SessionLifecycleFinalize(
    BaseTool[
        SessionFinalizeArgs,
        SessionFinalizeResultModel,
        SessionLifecycleFinalizeConfig,
        BaseToolState,
    ],
    ToolUIData[SessionFinalizeArgs, SessionFinalizeResultModel],
):
    description: ClassVar[str] = (
        "Finalize a Relay session by classifying artifacts, compacting eligible "
        "current-session files, and writing lifecycle evidence."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def format_call_display(cls, args: SessionFinalizeArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Finalize session: {args.session_id}")

    @classmethod
    def format_result_display(
        cls, result: SessionFinalizeResultModel
    ) -> ToolResultDisplay:
        return ToolResultDisplay(
            success=result.status == "ok",
            message=f"Session finalize {result.status}",
            warnings=list(result.warnings),
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Finalizing session"

    async def run(
        self, args: SessionFinalizeArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | SessionFinalizeResultModel, None]:
        try:
            result = self._finalize(args)
        except Exception as err:
            yield SessionFinalizeResultModel(
                session_id=args.session_id,
                scanned_files=0,
                total_bytes_before=0,
                total_bytes_after=0,
                compacted_files=(),
                protected_files=(),
                refused_files=(),
                prune_candidates=(),
                deleted_files=(),
                manifest_path=None,
                receipt_path=None,
                status="error",
                warnings=(str(err),),
            )
            return
        yield result

    def _finalize(self, args: SessionFinalizeArgs) -> SessionFinalizeResultModel:
        policy = SessionRetentionPolicy(
            allow_prune=args.policy.allow_prune,
            max_delete_mb=args.policy.max_delete_mb,
            older_than_days=args.policy.older_than_days,
            archive_dir=args.policy.archive_dir,
        )
        result = finalize_session_storage(
            session_id=args.session_id,
            sessions_root=args.sessions_root,
            policy=policy,
            mission_envelope=args.mission_envelope,
            allow_compaction=args.allow_compaction,
            allow_prune=args.allow_prune,
            write_receipt=args.write_receipt,
            reason=args.reason,
        )
        return SessionFinalizeResultModel(
            session_id=result.session_id,
            scanned_files=result.scanned_files,
            total_bytes_before=result.total_bytes_before,
            total_bytes_after=result.total_bytes_after,
            compacted_files=tuple(
                _compaction_model(item) for item in result.compacted_files
            ),
            protected_files=tuple(
                _artifact_model(item) for item in result.protected_files
            ),
            refused_files=tuple(_refusal_model(item) for item in result.refused_files),
            prune_candidates=tuple(
                _artifact_model(
                    ClassifiedArtifact(
                        path=item.path,
                        size_bytes=item.size_bytes,
                        category=item.category,
                    )
                )
                for item in result.prune_candidates
            ),
            deleted_files=tuple(_deleted_model(item) for item in result.deleted_files),
            manifest_path=str(result.manifest_path) if result.manifest_path else None,
            receipt_path=str(result.receipt_path) if result.receipt_path else None,
            status=cast(Literal["ok", "partial", "refused", "error"], result.status),
            warnings=result.warnings,
        )


__all__ = [
    "SessionFinalizeArgs",
    "SessionFinalizeResultModel",
    "SessionLifecycleFinalize",
    "SessionLifecycleFinalizeConfig",
]
