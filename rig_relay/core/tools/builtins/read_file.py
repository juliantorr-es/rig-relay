from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final

import anyio
from pydantic import BaseModel, Field

from rig_relay.core.config.harness_files import get_harness_files_manager
from rig_relay.core.scratchpad import is_scratchpad_path
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
from rig_relay.core.tools.security import (
    MAX_TEXT_FILE_BYTES,
    is_binary_extension,
    is_likely_binary,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.tools.utils import resolve_file_tool_permission
from rig_relay.core.types import ToolStreamEvent
from rig_relay.core.utils import VIBE_WARNING_TAG
from rig_relay.core.utils.io import decode_safe

if TYPE_CHECKING:
    from rig_relay.core.types import ToolResultEvent


class _ReadResult(NamedTuple):
    lines: list[str]
    bytes_read: int
    was_truncated: bool
    error_kind: str | None = None
    encoding_fallback: bool = False


class ReadFileArgs(BaseModel):
    path: str = Field(description="Repository-relative path to the file to read.")
    offset: int = Field(
        default=0,
        description="Line number to start reading from (0-indexed, inclusive).",
    )
    limit: int | None = Field(
        default=None, description="Maximum number of lines to read."
    )


class ReadFileResult(BaseModel):
    path: str
    content: str
    offset: int = 0
    lines_read: int
    was_truncated: bool = Field(
        description="True if the reading was stopped due to the max_read_bytes limit."
    )
    error_kind: str | None = None


class ReadFileToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    sensitive_patterns: list[str] = Field(
        default=["**/.env", "**/.env.*"],
        description="File patterns that trigger ASK even when permission is ALWAYS.",
    )

    max_read_bytes: int = Field(
        default=64_000, description="Maximum total bytes to read from a file in one go."
    )


class ReadFileState(BaseToolState):
    injected_agents_md: set[str] = Field(default_factory=set)


class ReadFile(
    BaseTool[ReadFileArgs, ReadFileResult, ReadFileToolConfig, ReadFileState],
    ToolUIData[ReadFileArgs, ReadFileResult],
):
    description: ClassVar[str] = (
        "Read a text file (encoding detected safely), returning content from a "
        "specific line range. Reading is capped by a byte limit for safety.\n\n"
        "Use read_file when the target file is known and you need source context. "
        "For searching code, prefer grep. For structural code patterns, use ast_grep. "
        "For directory listings, use bash.\n\n"
        "Offset is 0-indexed. When was_truncated=true, use offset+limit to page "
        "through the file. Binary files are detected and refused. "
        "Large files (>10MB) are refused. Output is capped at 64KB."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    @final
    async def run(
        self, args: ReadFileArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ReadFileResult, None]:
        file_path, error_kind = self._prepare_and_validate_path(args)
        if error_kind is not None:
            yield ReadFileResult(
                path=args.path,
                content="",
                offset=args.offset,
                lines_read=0,
                was_truncated=False,
                error_kind=error_kind,
            )
            return

        read_result = await self._read_file(args, file_path)
        if read_result.error_kind is not None:
            yield ReadFileResult(
                path=str(file_path),
                content="",
                offset=args.offset,
                lines_read=0,
                was_truncated=False,
                error_kind=read_result.error_kind,
            )
            return

        result = ReadFileResult(
            path=str(file_path),
            content="".join(read_result.lines),
            offset=args.offset,
            lines_read=len(read_result.lines),
            was_truncated=read_result.was_truncated,
        )

        if result.was_truncated:
            result.error_kind = "content_truncated"
        elif read_result.encoding_fallback:
            result.error_kind = "encoding_fallback_used"

        yield result

    def resolve_permission(self, args: ReadFileArgs) -> PermissionContext | None:
        return resolve_file_tool_permission(
            args.path,
            tool_name=self.get_name(),
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
            sensitive_patterns=self.config.sensitive_patterns,
        )

    def get_result_extra(self, result: ReadFileResult) -> str | None:
        try:
            mgr = get_harness_files_manager()
        except RuntimeError:
            return None
        docs = mgr.find_subdirectory_agents_md(Path(result.path))
        new_docs = [
            (d, c)
            for d, c in docs
            if str(d.resolve()) not in self.state.injected_agents_md
        ]
        if not new_docs:
            return None
        for d, _ in new_docs:
            self.state.injected_agents_md.add(str(d.resolve()))
        sections = [
            f"Contents of {d}/AGENTS.md (project instructions for this directory):\n\n{c.strip()}"
            for d, c in new_docs
        ]
        return f"<{VIBE_WARNING_TAG}>\n{'\n\n'.join(sections)}\n</{VIBE_WARNING_TAG}>"

    def _prepare_and_validate_path(self, args: ReadFileArgs) -> tuple[Path, str | None]:
        if error_kind := self._validate_inputs(args):
            return Path(args.path), error_kind

        file_path = normalize_tool_path(args.path)
        require_path_within_workdir(file_path)

        if error_kind := self._validate_path(file_path):
            return file_path, error_kind
        return file_path, None

    async def _read_file(self, args: ReadFileArgs, file_path: Path) -> _ReadResult:
        encoding_fallback = False
        try:
            raw_lines: list[bytes] = []
            bytes_read = 0
            was_truncated = True

            async with await anyio.Path(file_path).open("rb") as preview_f:
                header = await preview_f.read(8192)
                if is_likely_binary(header):
                    return _ReadResult(
                        lines=[],
                        bytes_read=0,
                        was_truncated=False,
                        error_kind="binary_file_refused",
                    )

            async with await anyio.Path(file_path).open("rb") as f:
                line_index = 0
                while raw_line := await f.readline():
                    if line_index < args.offset:
                        line_index += 1
                        continue

                    if args.limit is not None and len(raw_lines) >= args.limit:
                        break

                    line_bytes = len(raw_line)
                    if bytes_read + line_bytes > self.config.max_read_bytes:
                        break

                    raw_lines.append(raw_line)
                    bytes_read += line_bytes
                    line_index += 1
                else:
                    was_truncated = False
        except OSError as exc:
            return _ReadResult(
                lines=[], bytes_read=0, was_truncated=False, error_kind="read_failed"
            )

        raw_bytes = b"".join(raw_lines)
        try:
            raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            encoding_fallback = True

        lines_to_return = decode_safe(raw_bytes).text.splitlines(keepends=True)
        return _ReadResult(
            lines=lines_to_return,
            bytes_read=bytes_read,
            was_truncated=was_truncated,
            encoding_fallback=encoding_fallback,
        )

    def _validate_inputs(self, args: ReadFileArgs) -> str | None:
        if not args.path.strip():
            raise ToolError("Path cannot be empty")
        if args.offset < 0:
            return "invalid_line_range"
        if args.limit is not None and args.limit <= 0:
            return "invalid_line_range"
        return None

    def _validate_path(self, file_path: Path) -> str | None:
        try:
            resolved_path = file_path.resolve()
        except ValueError:
            return "missing_path"
        except FileNotFoundError:
            return "missing_path"

        if not resolved_path.exists():
            return "missing_path"
        if resolved_path.is_dir():
            return "path_is_directory"

        if is_binary_extension(resolved_path):
            return "binary_file_refused"

        file_size = resolved_path.stat().st_size
        if file_size > MAX_TEXT_FILE_BYTES:
            raise ToolError(
                f"Refusing to read '{resolved_path.name}': file is "
                f"{file_size / 1_048_576:.1f} MB, which exceeds the {MAX_TEXT_FILE_BYTES // 1_048_576} MB limit."
            )
        return None

    @classmethod
    def format_call_display(cls, args: ReadFileArgs) -> ToolCallDisplay:
        tag = " (scratchpad)" if is_scratchpad_path(args.path) else ""
        summary = f"Reading {args.path}"
        if args.offset > 0 or args.limit is not None:
            parts = []
            if args.offset > 0:
                parts.append(f"from line {args.offset}")
            if args.limit is not None:
                parts.append(f"limit {args.limit} lines")
            summary += f" ({', '.join(parts)})"
        return ToolCallDisplay(summary=f"{summary}{tag}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ReadFileResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        path_obj = Path(event.result.path)
        tag = " (scratchpad)" if is_scratchpad_path(event.result.path) else ""
        message = f"Read {event.result.lines_read} line{'' if event.result.lines_read <= 1 else 's'} from {path_obj.name}{tag}"
        if event.result.was_truncated:
            message += " (truncated)"

        return ToolResultDisplay(
            success=True,
            message=message,
            warnings=["File was truncated due to size limit"]
            if event.result.was_truncated
            else [],
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Reading file"
