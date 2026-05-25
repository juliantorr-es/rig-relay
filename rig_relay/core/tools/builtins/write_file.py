from __future__ import annotations

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
from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.store import get_default_trace_store


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        description="Repository-relative file path to write. Parent directories created automatically."
    )
    content: str = Field(
        description="Text content to write. Must be valid text (UTF-8)."
    )
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
    content_encoding: str = Field(
        default="utf-8", description="Encoding to use when writing the file content."
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
        "Create or overwrite a UTF-8 file. Use write_file for creating new files "
        "or completely replacing existing files. For targeted modifications to "
        "existing code, prefer search_replace. "
        "Parents directories are created automatically. "
        "Content is capped at 64KB. Fails if file exists unless overwrite=True."
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
    def _emit_coord_blocked_trace(
        ctx: InvokeContext | None, tool_name: str, file_path: str
    ) -> None:
        try:
            store = get_default_trace_store()
            event = build_golden_path_event(
                event_type="coord.write_blocked_missing_lease",
                correlation={
                    "session_id": ctx.session_dir.name
                    if ctx and ctx.session_dir
                    else "",
                    "coordination_store_available": False,
                },
                payload={
                    "tool_name": tool_name,
                    "file_path": file_path,
                    "tool_call_id": ctx.tool_call_id if ctx else "",
                    "parent_turn_id": ctx.parent_turn_id if ctx else "",
                },
            )
            store.write(event)
        except Exception:
            pass

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
    # ruff: noqa: PLR0914, PLR0915
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
        reservation_allowed = True
        if coordination_store is not None and coordination is not None:
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
            if ctx is not None and ctx.tool_runtime is not None:
                tc = getattr(ctx.tool_runtime, "telemetry_client", None)
                if tc is not None:
                    tc.emit_governance_gate_decision(
                        gate="dirty_guard",
                        decision="blocked",
                        reason=check.reason,
                        tool_name="write_file",
                        severity="warning",
                        mutation_intent=True,
                    )
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

        if ctx is not None and ctx.tool_runtime is not None:
            tc = getattr(ctx.tool_runtime, "telemetry_client", None)
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="dirty_guard",
                    decision="allowed",
                    reason=check.reason,
                    tool_name="write_file",
                    severity="info",
                )
        guard.mark_touched(file_path)

        # ── Prepare write ──
        snapshot = self.get_file_snapshot_for_path(str(file_path))
        before_sha256 = sha256_file_bytes(snapshot.content)
        before_bytes = len(snapshot.content) if snapshot.content is not None else 0

        # ── Atomic write ──
        try:
            self._atomic_write_text(
                file_path=file_path,
                content=args.content,
                encoding=args.content_encoding,
            )
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
        except OSError:
            raise
        except Exception:
            raise
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
    def _atomic_write_text(
        file_path: Path, content: str, encoding: str = "utf-8"
    ) -> None:
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


@dataclass(slots=True)
class ApplyCandidateResult:
    """Content-light result of applying a verified candidate mutation."""

    operation_id: str = ""
    canonical_path_identity: str = ""
    actual_after_sha256: str | None = None
    path_lock_acquired: bool = False
    refusal_reason: str | None = None


async def apply_verified_candidate(
    *,
    authority_root: Path,
    coordination_lock_root: Path,
    canonical_path_identity: str,
    operational_file_path: Path,
    expected_before_sha256: str,
    candidate_content: bytes,
    candidate_after_sha256: str,
) -> ApplyCandidateResult:
    """Guarded compare-and-write for an already-admitted candidate.

    Acquires a per-canonical-path lock (stored under
    ``coordination_lock_root``, NOT adjacent to source files),
    verifies the dirty guard, confirms the current file hash equals
    ``expected_before_sha256``, writes atomically via temp+rename,
    and verifies the resulting hash equals ``candidate_after_sha256``.

    Returns a content-light ``ApplyCandidateResult``. Never contains
    raw source text, replacement content, or mutation payload bodies.
    """
    import hashlib
    import os
    import tempfile

    from rig_relay.governance.dirty_guard import get_guard

    resolved = operational_file_path.resolve()
    try:
        resolved.relative_to(authority_root.resolve())
    except ValueError:
        return ApplyCandidateResult(
            canonical_path_identity=canonical_path_identity,
            refusal_reason=(
                f"operational path {resolved} is not under "
                f"authority root {authority_root}"
            ),
        )

    sha_prefix = "sha256:"
    expected = (
        expected_before_sha256[len(sha_prefix) :]
        if expected_before_sha256.startswith(sha_prefix)
        else expected_before_sha256
    )
    candidate = (
        candidate_after_sha256[len(sha_prefix) :]
        if candidate_after_sha256.startswith(sha_prefix)
        else candidate_after_sha256
    )

    # Per-canonical-path lock — stored in coordination custody
    lock_dir = coordination_lock_root / "path-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(canonical_path_identity.encode("utf-8")).hexdigest()[:32]
    lock_path = lock_dir / f"{lock_name}.lock"

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        guard = get_guard()
        guard_check = guard.check_write_file(
            resolved, allow_overwrite_protected=True, expected_before_sha256=expected
        )
        if not guard_check.allowed:
            return ApplyCandidateResult(
                canonical_path_identity=canonical_path_identity,
                path_lock_acquired=True,
                refusal_reason=(guard_check.reason or "dirty_guard_refused"),
            )

        current_bytes = resolved.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if current_hash != expected:
            return ApplyCandidateResult(
                canonical_path_identity=canonical_path_identity,
                path_lock_acquired=True,
                refusal_reason=(
                    f"expected hash {expected[:16]}..., got {current_hash[:16]}..."
                ),
            )

        # Atomic write
        fd_w, temp_str = tempfile.mkstemp(
            dir=str(resolved.parent), prefix="." + resolved.name + "."
        )
        Path(temp_str)
        try:
            os.write(fd_w, candidate_content)
            os.fsync(fd_w)
        finally:
            os.close(fd_w)
        os.replace(temp_str, str(resolved))

        result_bytes = resolved.read_bytes()
        result_hash = hashlib.sha256(result_bytes).hexdigest()
        if result_hash != candidate:
            return ApplyCandidateResult(
                canonical_path_identity=canonical_path_identity,
                path_lock_acquired=True,
                refusal_reason=(
                    f"after-write hash mismatch: "
                    f"expected {candidate[:16]}..., "
                    f"got {result_hash[:16]}..."
                ),
            )

        return ApplyCandidateResult(
            operation_id=hashlib.sha256(
                f"{canonical_path_identity}:{expected}:{result_hash}".encode()
            ).hexdigest()[:16],
            canonical_path_identity=canonical_path_identity,
            actual_after_sha256=f"{sha_prefix}{result_hash}",
            path_lock_acquired=True,
        )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
