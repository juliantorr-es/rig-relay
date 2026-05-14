from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, final

import anyio
from pydantic import BaseModel, Field

from vibe.core.coordination import CoordinationStore
from vibe.core.guard import get_guard
from vibe.core.rewind.manager import FileSnapshot
from vibe.core.scratchpad import is_scratchpad_path
from vibe.core.telemetry.artifacts import ToolOutputArtifactWriter
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.determinism import normalize_tool_path, require_path_within_workdir
from vibe.core.tools.permissions import PermissionContext
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission, sha256_file_bytes
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class WriteFileArgs(BaseModel):
    path: str
    content: str
    overwrite: bool = Field(
        default=False, description="Must be set to true to overwrite an existing file."
    )
    allow_overwrite_protected: bool = Field(
        default=False,
        description=(
            "Set to true ONLY when overwriting a file that was dirty (modified, staged, or untracked) "
            "at session start. Must be paired with expected_before_sha256. "
            "Leave false for clean files and new files."
        ),
    )
    expected_before_sha256: str | None = Field(
        default=None,
        description=(
            "sha256:<hex> of the file bytes as they exist right now, before your write. "
            "Required when allow_overwrite_protected=true. "
            "The write will be REFUSED if this hash does not match the current file bytes — "
            "re-read the file and recompute the hash if you get a stale-hash refusal."
        ),
    )


class WriteFileResult(BaseModel):
    path: str
    bytes_written: int
    file_existed: bool
    content: str
    before_sha256: str | None = None
    after_sha256: str
    created_file: bool = False
    overwrote_existing_file: bool = False
    parent_dirs_created: bool = False
    status: str = "success"
    error_kind: str | None = None
    refusal_reason: str | None = None


def _classify_write_guard_refusal(check: object) -> str:
    """Classify a dirty-guard refusal into a structured error_kind."""
    rsn = getattr(check, "reason", "") or ""
    if "stale_hash" in rsn or "hash_mismatch" in rsn or "mismatch" in rsn:
        return "expected_hash_mismatch"
    if "no_overwrite_flag" in rsn or "missing_expected_hash" in rsn:
        return "dirty_file_protected"
    if "protected_file_missing" in rsn:
        return "protected_file_missing"
    if "missing" in rsn:
        return "dirty_file_protected"
    return "dirty_file_protected"


@dataclass(frozen=True)
class WriteFileCoordinationContext:
    session_id: str
    task_id: str
    path: Path
    relative_path: str


class WriteFileConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    sensitive_patterns: list[str] = Field(
        default=["**/.env", "**/.env.*"],
        description="File patterns that trigger ASK even when permission is ALWAYS.",
    )
    max_write_bytes: int = 64_000
    create_parent_dirs: bool = True


class WriteFile(
    BaseTool[WriteFileArgs, WriteFileResult, WriteFileConfig, BaseToolState],
    ToolUIData[WriteFileArgs, WriteFileResult],
):
    description: ClassVar[str] = (
        "Create or overwrite a UTF-8 file. Fails if file exists unless 'overwrite=True'."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def format_call_display(cls, args: WriteFileArgs) -> ToolCallDisplay:
        tag = " (scratchpad)" if is_scratchpad_path(args.path) else ""
        overwrite = " (overwrite)" if args.overwrite else ""
        return ToolCallDisplay(
            summary=f"Writing {args.path}{overwrite}{tag}", content=args.content
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if isinstance(event.result, WriteFileResult):
            action = "Overwritten" if event.result.file_existed else "Created"
            tag = " (scratchpad)" if is_scratchpad_path(event.result.path) else ""
            return ToolResultDisplay(
                success=True, message=f"{action} {Path(event.result.path).name}{tag}"
            )

        return ToolResultDisplay(success=True, message="File written")

    @classmethod
    def get_status_text(cls) -> str:
        return "Writing file"

    @staticmethod
    def _coordination_store(ctx: InvokeContext | None) -> CoordinationStore | None:
        if ctx is None or ctx.session_dir is None:
            return None
        return CoordinationStore(Path.cwd() / ".build" / "rig-relay" / "coordination")

    @staticmethod
    def _build_coordination_context(
        ctx: InvokeContext | None, file_path: Path
    ) -> WriteFileCoordinationContext | None:
        if ctx is None or ctx.session_dir is None or ctx.tool_call_id is None:
            return None
        return WriteFileCoordinationContext(
            session_id=ctx.session_dir.name,
            task_id=ctx.tool_call_id,
            path=file_path,
            relative_path=file_path.as_posix(),
        )

    @staticmethod
    def _maybe_claim_coordination(
        store: CoordinationStore | None,
        coordination: WriteFileCoordinationContext | None,
    ) -> bool:
        if store is None or coordination is None:
            return False
        claim_result = store.claim_task(
            session_id=coordination.session_id,
            task_id=coordination.task_id,
            claim_kind="write_file",
            ttl_seconds=300,
            scope={"allowed_paths": [coordination.relative_path]},
        )
        if not claim_result.allowed:
            return False
        reservation_result = store.reserve_paths(
            session_id=coordination.session_id,
            task_id=coordination.task_id,
            mode="write",
            paths=[coordination.relative_path],
            ttl_seconds=300,
        )
        if not reservation_result.allowed:
            return False
        return True

    @staticmethod
    def _maybe_publish_coordination_artifact(
        store: CoordinationStore | None,
        coordination: WriteFileCoordinationContext | None,
        result: WriteFileResult,
    ) -> None:
        if store is None or coordination is None:
            return
        artifact = ToolOutputArtifactWriter(coordination.session_id).write_artifact(
            tool_name="write_file",
            raw_output=result.model_dump_json(exclude_none=True),
            source_event_id=coordination.task_id,
        )
        store.publish_artifact(
            session_id=coordination.session_id,
            task_id=coordination.task_id,
            artifact_kind="write_file",
            artifact_uri=artifact.path,
            artifact_sha256=artifact.artifact_record_sha256 or artifact.payload_sha256,
            schema_id="rig.relay.artifact.envelope.v1",
        )

    def get_file_snapshot(self, args: WriteFileArgs) -> FileSnapshot | None:
        return self.get_file_snapshot_for_path(args.path)

    def resolve_permission(self, args: WriteFileArgs) -> PermissionContext | None:
        return resolve_file_tool_permission(
            args.path,
            tool_name=self.get_name(),
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
            sensitive_patterns=self.config.sensitive_patterns,
        )

    @final
    async def run(
        self, args: WriteFileArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | WriteFileResult, None]:
        file_path, file_existed, content_bytes, parent_dirs_created = (
            self._prepare_and_validate_path(args)
        )
        coordination_store = self._coordination_store(ctx)
        coordination = self._build_coordination_context(ctx, file_path)
        reservation_allowed = self._maybe_claim_coordination(
            coordination_store, coordination
        )
        if (
            not reservation_allowed
            and coordination_store is not None
            and coordination is not None
        ):
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=file_path.exists(),
                content="",
                before_sha256=None,
                after_sha256="",
                status="blocked",
                error_kind="path_reserved",
                refusal_reason="Coordination reservation refused: another session has an active lease on this path",
            )
            return

        guard = get_guard()
        check = guard.check_write_file(
            file_path,
            allow_overwrite_protected=args.allow_overwrite_protected,
            expected_before_sha256=args.expected_before_sha256,
        )
        if not check.allowed:
            guard.record_refusal(file_path, check.reason)
            _cls = _classify_write_guard_refusal(check)
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=file_path.exists(),
                content="",
                before_sha256=None,
                after_sha256="",
                status="refused",
                error_kind=_cls,
                refusal_reason=check.detail,
            )
            return

        guard.mark_touched(file_path)

        snapshot = self.get_file_snapshot_for_path(str(file_path))
        before_sha256 = sha256_file_bytes(snapshot.content)

        try:
            await self._write_file(args, file_path)

            after_sha256 = sha256_file_bytes(file_path.read_bytes())
            assert after_sha256 is not None  # file was just written

            result = WriteFileResult(
                path=str(file_path),
                bytes_written=content_bytes,
                file_existed=file_existed,
                content=args.content,
                before_sha256=before_sha256,
                after_sha256=after_sha256,
                created_file=not file_existed,
                overwrote_existing_file=file_existed,
                parent_dirs_created=parent_dirs_created,
            )
            self._maybe_publish_coordination_artifact(
                coordination_store, coordination, result
            )
            yield result
        finally:
            if (
                coordination_store is not None
                and coordination is not None
                and reservation_allowed
            ):
                coordination_store.release_paths(
                    session_id=coordination.session_id,
                    task_id=coordination.task_id,
                    paths=[coordination.relative_path],
                )

    def _prepare_and_validate_path(
        self, args: WriteFileArgs
    ) -> tuple[Path, bool, int, bool]:
        file_path = normalize_tool_path(args.path)
        require_path_within_workdir(file_path)

        if file_path.is_dir():
            raise ToolError(f"Path is a directory, not a file: {file_path}")

        content_bytes = len(args.content.encode("utf-8"))
        if content_bytes > self.config.max_write_bytes:
            raise ToolError(
                f"Content exceeds {self.config.max_write_bytes} bytes limit"
            )

        file_existed = file_path.exists()

        if file_existed and not args.overwrite:
            raise ToolError(
                f"File '{file_path}' exists. Set overwrite=True to replace."
            )

        parent_dirs_created = False
        if self.config.create_parent_dirs:
            parent_existed = file_path.parent.is_dir()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            parent_dirs_created = not parent_existed
        elif not file_path.parent.exists():
            raise ToolError(f"Parent directory does not exist: {file_path.parent}")

        return file_path, file_existed, content_bytes, parent_dirs_created

    async def _write_file(self, args: WriteFileArgs, file_path: Path) -> None:
        try:
            async with await anyio.Path(file_path).open(
                mode="w", encoding="utf-8"
            ) as f:
                await f.write(args.content)
        except Exception as e:
            raise ToolError(f"Error writing {file_path}: {e}") from e
