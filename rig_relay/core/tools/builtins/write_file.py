from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time
from typing import ClassVar, final

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.store import CoordinationStore
from rig_relay.core.guard import get_guard
from rig_relay.core.rewind.manager import FileSnapshot
from rig_relay.core.scratchpad import is_scratchpad_path
from rig_relay.core.telemetry.artifacts import ToolOutputArtifactWriter
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.determinism import (
    normalize_tool_path,
    require_path_within_workdir,
)
from rig_relay.core.tools.permissions import PermissionContext
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.tools.utils import resolve_file_tool_permission, sha256_file_bytes
from rig_relay.core.types import ToolResultEvent, ToolStreamEvent


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    before_bytes: int | None = None
    after_bytes: int | None = None
    duration_ms: float | None = None


class WriteFileReceipt(BaseModel):
    """Content-light receipt for a write_file invocation.

    Contains no raw file content — only metadata, SHA256 hashes, byte
    counts, path, and structured error classification.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.write_file_receipt.v1"
    path: str
    status: str = "success"
    error_kind: str | None = None
    refusal_reason: str | None = None
    bytes_written: int = 0
    before_sha256: str | None = None
    after_sha256: str | None = None
    before_bytes: int | None = None
    after_bytes: int | None = None
    file_existed: bool = False
    created_file: bool = False
    overwrote_existing_file: bool = False
    parent_dirs_created: bool = False
    duration_ms: float | None = None


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

    @final
    def build_receipt(self, result: WriteFileResult) -> WriteFileReceipt:
        """Build a content-light receipt from a write_file result.

        The receipt contains no raw file content — only metadata, SHA256
        hashes, byte counts, path, and structured error classification.
        """
        return WriteFileReceipt(
            path=str(result.path),
            status=result.status,
            error_kind=result.error_kind,
            refusal_reason=self._sanitize_refusal_for_receipt(result.refusal_reason),
            bytes_written=result.bytes_written,
            before_sha256=result.before_sha256,
            after_sha256=result.after_sha256,
            before_bytes=result.before_bytes,
            after_bytes=result.after_bytes,
            file_existed=result.file_existed,
            created_file=result.created_file,
            overwrote_existing_file=result.overwrote_existing_file,
            parent_dirs_created=result.parent_dirs_created,
            duration_ms=result.duration_ms,
        )

    @staticmethod
    def _sanitize_refusal_for_receipt(refusal_reason: str | None) -> str | None:
        """Strip file content context from a refusal reason string.

        Guard check.detail may contain file paths, not raw content.
        Currently a pass-through since the guard does not embed content.
        """
        if not refusal_reason:
            return None
        return refusal_reason

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
    # ruff: noqa: PLR0914
    async def run(
        self, args: WriteFileArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | WriteFileResult, None]:
        start = time.perf_counter()

        # ── Path safety (abnormal — may raise ToolError) ──
        file_path = normalize_tool_path(args.path)
        require_path_within_workdir(file_path)

        # ── Early deterministic refusals (structured results) ──
        if file_path.is_dir():
            elapsed = (time.perf_counter() - start) * 1000
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=False,
                content="",
                before_sha256=None,
                after_sha256="",
                status="refused",
                error_kind="path_is_directory",
                refusal_reason=f"Path is a directory, not a file: {file_path}",
                duration_ms=elapsed,
            )
            return

        content_bytes = len(args.content.encode("utf-8"))
        if content_bytes > self.config.max_write_bytes:
            elapsed = (time.perf_counter() - start) * 1000
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=file_path.exists(),
                content="",
                before_sha256=None,
                after_sha256="",
                status="refused",
                error_kind="content_too_large",
                refusal_reason=f"Content exceeds {self.config.max_write_bytes} bytes limit",
                duration_ms=elapsed,
            )
            return

        file_existed = file_path.exists()

        if file_existed and not args.overwrite:
            elapsed = (time.perf_counter() - start) * 1000
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=True,
                content="",
                before_sha256=None,
                after_sha256="",
                status="refused",
                error_kind="overwrite_required",
                refusal_reason=f"File '{file_path}' exists. Set overwrite=True to replace.",
                duration_ms=elapsed,
            )
            return

        parent_dirs_created = self._prepare_parent_dir(file_path)
        if not file_path.parent.exists():
            elapsed = (time.perf_counter() - start) * 1000
            yield WriteFileResult(
                path=str(file_path),
                bytes_written=0,
                file_existed=file_existed,
                content="",
                before_sha256=None,
                after_sha256="",
                status="refused",
                error_kind="parent_missing",
                refusal_reason=f"Parent directory does not exist: {file_path.parent}",
                duration_ms=elapsed,
            )
            return

        # ── Coordination ──
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
            elapsed = (time.perf_counter() - start) * 1000
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
                duration_ms=elapsed,
            )
            return

        # ── Dirty file guard ──
        guard = get_guard()
        check = guard.check_write_file(
            file_path,
            allow_overwrite_protected=args.allow_overwrite_protected,
            expected_before_sha256=args.expected_before_sha256,
        )
        if not check.allowed:
            guard.record_refusal(file_path, check.reason)
            _cls = _classify_write_guard_refusal(check)
            elapsed = (time.perf_counter() - start) * 1000
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
                duration_ms=elapsed,
            )
            return

        guard.mark_touched(file_path)

        # ── Prepare write ──
        snapshot = self.get_file_snapshot_for_path(str(file_path))
        before_sha256 = sha256_file_bytes(snapshot.content)
        before_bytes = len(snapshot.content) if snapshot.content is not None else 0

        # ── Atomic write ──
        try:
            await self._write_file(args, file_path)

            after_sha256 = sha256_file_bytes(file_path.read_bytes())
            assert after_sha256 is not None  # file was just written
            after_bytes = file_path.stat().st_size

            elapsed = (time.perf_counter() - start) * 1000
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
                duration_ms=elapsed,
                before_bytes=before_bytes,
                after_bytes=after_bytes,
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

    def _prepare_parent_dir(self, file_path: Path) -> bool:
        """Create parent directories if configured.

        Returns True if parent dirs were created by this call.
        """
        if self.config.create_parent_dirs:
            parent_existed = file_path.parent.is_dir()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            return not parent_existed
        return False

    @staticmethod
    def _atomic_write_text(file_path: Path, content: str) -> None:
        """Write text content atomically using same-directory temp file + os.replace().

        Creates a temporary file in the same directory as target, writes content,
        fsyncs, then replaces the target atomically on POSIX when source and
        destination are on the same filesystem. Best-effort durable atomic replace.

        Bounded by max_write_bytes (64 KB), so synchronous I/O is acceptable
        and will not block the event loop significantly.
        """
        content_bytes = content.encode("utf-8")
        temp_path: Path | None = None
        try:
            fd, tmp_path_str = tempfile.mkstemp(
                dir=str(file_path.parent), prefix=f".{file_path.name}.", suffix=".tmp"
            )
            temp_path = Path(tmp_path_str)

            try:
                os.write(fd, content_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)

            # Preserve existing file mode when overwriting
            if file_path.exists():
                old_mode = file_path.stat().st_mode
                temp_path.chmod(old_mode)

            # Atomic replace (atomic on POSIX when same filesystem)
            os.replace(tmp_path_str, str(file_path))

            # Best-effort directory fsync on POSIX
            try:
                parent_fd = os.open(str(file_path.parent), os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except (OSError, AttributeError):
                pass  # Directory sync is best-effort

        except Exception:
            # Clean up temp file on failure (before replace)
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    async def _write_file(self, args: WriteFileArgs, file_path: Path) -> None:
        """Write content atomically using same-directory temp file + os.replace()."""
        try:
            await asyncio.to_thread(self._atomic_write_text, file_path, args.content)
        except Exception as e:
            raise ToolError(f"Error writing {file_path}: {e}") from e
