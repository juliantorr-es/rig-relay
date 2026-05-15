from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from enum import StrEnum, auto
import hashlib
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from rig_relay.core.logger import logger
from rig_relay.core.telemetry.artifacts import (
    SearchQueryArtifact,
    SearchResultArtifact,
    SearchResultItem,
    ToolOutputArtifactWriter,
)
from rig_relay.core.telemetry.local import dump_canonical_json
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
from rig_relay.core.tools.utils import resolve_file_tool_permission
from rig_relay.core.types import ToolStreamEvent
from rig_relay.core.utils import kill_async_subprocess
from rig_relay.core.utils.io import read_safe

if TYPE_CHECKING:
    from rig_relay.core.types import ToolResultEvent


class GrepBackend(StrEnum):
    RIPGREP = auto()
    GNU_GREP = auto()


class GrepToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    sensitive_patterns: list[str] = Field(
        default=["**/.env", "**/.env.*"],
        description="File patterns that trigger ASK even when permission is ALWAYS.",
    )

    max_output_bytes: int = Field(
        default=64_000, description="Hard cap for the total size of matched lines."
    )
    default_max_matches: int = Field(
        default=100, description="Default maximum number of matches to return."
    )
    default_timeout: int = Field(
        default=60, description="Default timeout for the search command in seconds."
    )
    exclude_patterns: list[str] = Field(
        default=[
            ".venv/",
            "venv/",
            ".env/",
            "env/",
            "node_modules/",
            ".git/",
            "__pycache__/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".tox/",
            ".nox/",
            ".coverage/",
            "htmlcov/",
            "dist/",
            "build/",
            ".idea/",
            ".vscode/",
            "*.egg-info",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".DS_Store",
            "Thumbs.db",
        ],
        description="List of glob patterns to exclude from search (dirs should end with /).",
    )
    codeignore_file: str = Field(
        default=".vibeignore",
        description="Name of the file to read for additional exclusion patterns.",
    )


class GrepArgs(BaseModel):
    pattern: str
    path: str = "."
    max_matches: int | None = Field(
        default=None, description="Override the default maximum number of matches."
    )
    use_default_ignore: bool = Field(
        default=True, description="Whether to respect .gitignore and .ignore files."
    )


class GrepMatch(BaseModel):
    path: str
    line: int | None = None
    column: int | None = None
    line_content: str | None = None
    match_text: str | None = None

    @classmethod
    def from_output_line(cls, raw: str) -> GrepMatch | None:
        """Parse a single grep/rg output line in ``file:line:content`` format.

        Handles Windows drive-letter paths like ``C:\\repo\\file.py:10:match``
        and content containing colons like ``file.py:10:def hello():``.
        """
        parts = raw.split(":", 2)
        MIN_PARTS = 2
        if len(parts) < MIN_PARTS:
            return None

        # Windows drive letter: first part is a single letter (e.g. "C")
        MIN_WINDOWS_PARTS = 3
        is_windows_path = (
            len(parts[0]) == 1
            and parts[0].isalpha()
            and len(parts) >= MIN_WINDOWS_PARTS
        )
        if is_windows_path:
            file_path = f"{parts[0]}:{parts[1]}"
            line_and_content = parts[2]
        else:
            file_path = parts[0]
            if len(parts) >= MIN_WINDOWS_PARTS:
                line_and_content = f"{parts[1]}:{parts[2]}"
            else:
                line_and_content = parts[1] if len(parts) > 1 else ""

        if ":" in line_and_content:
            line_str, content = line_and_content.split(":", 1)
        else:
            line_str = line_and_content
            content = ""

        try:
            line_num = int(line_str) if line_str else None
        except ValueError:
            line_num = None
            content = line_and_content

        return cls(
            path=str(Path(file_path).resolve()),
            line=line_num,
            line_content=content,
            match_text=content,
        )


class GrepResult(BaseModel):
    matches: str
    match_count: int
    total_match_count: int = 0
    was_truncated: bool = Field(
        description="True if output was cut short by max_matches or max_output_bytes."
    )

    @property
    def parsed_matches(self) -> list[GrepMatch]:
        results: list[GrepMatch] = []
        for line in self.matches.splitlines():
            if match := GrepMatch.from_output_line(line):
                results.append(match)
        return results


class Grep(
    BaseTool[GrepArgs, GrepResult, GrepToolConfig, BaseToolState],
    ToolUIData[GrepArgs, GrepResult],
):
    description: ClassVar[str] = (
        "Recursively search files for a regex pattern using ripgrep (rg) or grep. "
        "Respects .gitignore and .codeignore files by default when using ripgrep."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    def resolve_permission(self, args: GrepArgs) -> PermissionContext | None:
        return resolve_file_tool_permission(
            args.path,
            tool_name=self.get_name(),
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
            sensitive_patterns=self.config.sensitive_patterns,
        )

    def _detect_backend(self) -> GrepBackend:
        if shutil.which("rg"):
            return GrepBackend.RIPGREP
        if shutil.which("grep"):
            return GrepBackend.GNU_GREP
        raise ToolError(
            "Neither ripgrep (rg) nor grep is installed. "
            "Please install ripgrep: https://github.com/BurntSushi/ripgrep#installation"
        )

    async def run(
        self, args: GrepArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GrepResult, None]:
        backend = self._detect_backend()
        self._validate_args(args)

        exclude_patterns = self._collect_exclude_patterns()
        cmd = self._build_command(args, exclude_patterns, backend)
        stdout, stdout_bytes, stderr_bytes = await self._execute_search(cmd)

        max_matches = args.max_matches or self.config.default_max_matches
        result = self._parse_output(stdout, max_matches)

        if ctx and ctx.session_dir and ctx.tool_call_id:
            try:
                self._emit_search_artifacts(
                    args, result, backend, stdout_bytes, stderr_bytes, ctx
                )
            except Exception as e:
                logger.warning("Failed to emit search artifacts: %s", e)

        yield result

    def _emit_search_artifacts(
        self,
        args: GrepArgs,
        result: GrepResult,
        backend: GrepBackend,
        stdout_bytes: bytes,
        stderr_bytes: bytes,
        ctx: InvokeContext,
    ) -> None:
        query_json = dump_canonical_json(self._build_query_payload(args, backend))
        query_sha256 = _sha256_bytes(query_json.encode("utf-8"))

        query_artifact = SearchQueryArtifact(
            tool_name="grep",
            query=args.pattern,
            backend=backend.value,
            root=str(args.path),
            exclude_globs=self._collect_exclude_patterns(),
            regex=True,
            normalized_query_sha256=query_sha256,
        )

        items = self._build_sorted_result_items(result)
        matched_file_count = len({i.relative_path for i in items})
        truncation_reason = self._build_truncation_reason(result)
        warnings = (
            ["Output was truncated due to size/match limits"]
            if result.was_truncated
            else []
        )

        result_artifact = SearchResultArtifact(
            query_sha256=query_sha256,
            results=items,
            truncated=result.was_truncated,
            backend=backend.value,
            ordering_policy="rig_normalized_path_line_column_match",
            total_match_count=result.total_match_count,
            returned_match_count=len(items),
            matched_file_count=matched_file_count,
            returned_file_count=matched_file_count,
            truncation_reason=truncation_reason,
            result_set_sha256=_compute_result_set_sha256(
                items, result.total_match_count, matched_file_count
            ),
            stdout_sha256=_sha256_bytes(stdout_bytes) if stdout_bytes else None,
            stderr_sha256=_sha256_bytes(stderr_bytes) if stderr_bytes else None,
            warnings=warnings,
        )

        if ctx.session_dir is None:
            return
        writer = ToolOutputArtifactWriter(str(ctx.session_dir.name))
        writer.write_search_artifacts(
            query_artifact=query_artifact,
            result_artifact=result_artifact,
            tool_call_id=ctx.tool_call_id,
        )

    def _build_query_payload(self, args: GrepArgs, backend: GrepBackend) -> dict:
        return {
            "pattern": args.pattern,
            "path": args.path,
            "max_matches": args.max_matches or self.config.default_max_matches,
            "use_default_ignore": args.use_default_ignore,
            "backend": backend.value,
            "exclude_patterns": sorted(self._collect_exclude_patterns()),
        }

    def _build_sorted_result_items(self, result: GrepResult) -> list[SearchResultItem]:
        items = []
        for match in result.parsed_matches:
            rel = _repo_relative(match.path)
            excerpt = match.line_content or ""
            items.append(
                SearchResultItem(
                    relative_path=rel,
                    start_line=match.line,
                    excerpt=excerpt,
                    excerpt_sha256=_sha256_bytes(excerpt.encode("utf-8"))
                    if excerpt
                    else None,
                    match_text=match.match_text,
                )
            )
        items.sort(key=lambda i: (i.relative_path, i.start_line or 0, i.excerpt or ""))
        return items

    @staticmethod
    def _build_truncation_reason(result: GrepResult) -> str | None:
        if not result.was_truncated:
            return None
        return (
            "result count exceeded max_matches or output size exceeded max_output_bytes"
        )

    def _validate_args(self, args: GrepArgs) -> None:
        if not args.pattern.strip():
            raise ToolError("Empty search pattern provided.")

        path_obj = normalize_tool_path(args.path)
        require_path_within_workdir(path_obj)

        if not path_obj.exists():
            raise ToolError(f"Path does not exist: {args.path}")

    def _collect_exclude_patterns(self) -> list[str]:
        patterns = list(self.config.exclude_patterns)

        codeignore_path = Path.cwd() / self.config.codeignore_file
        if codeignore_path.is_file():
            patterns.extend(self._load_codeignore_patterns(codeignore_path))

        return patterns

    def _load_codeignore_patterns(self, codeignore_path: Path) -> list[str]:
        patterns = []
        try:
            content = read_safe(codeignore_path).text
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError:
            pass

        return patterns

    def _build_command(
        self, args: GrepArgs, exclude_patterns: list[str], backend: GrepBackend
    ) -> list[str]:
        if backend == GrepBackend.RIPGREP:
            return self._build_ripgrep_command(args, exclude_patterns)
        return self._build_gnu_grep_command(args, exclude_patterns)

    def _build_ripgrep_command(
        self, args: GrepArgs, exclude_patterns: list[str]
    ) -> list[str]:
        max_matches = args.max_matches or self.config.default_max_matches

        cmd = [
            "rg",
            "--line-number",
            "--no-heading",
            "--smart-case",
            "--no-binary",
            # Request one extra to detect truncation
            "--max-count",
            str(max_matches + 1),
        ]

        if not args.use_default_ignore:
            cmd.append("--no-ignore")

        for pattern in exclude_patterns:
            cmd.extend(["--glob", f"!{pattern}"])

        cmd.extend(["-e", args.pattern, args.path])

        return cmd

    def _build_gnu_grep_command(
        self, args: GrepArgs, exclude_patterns: list[str]
    ) -> list[str]:
        max_matches = args.max_matches or self.config.default_max_matches

        cmd = ["grep", "-r", "-n", "-I", "-E", f"--max-count={max_matches + 1}"]

        if args.pattern.islower():
            cmd.append("-i")

        for pattern in exclude_patterns:
            if pattern.endswith("/"):
                dir_pattern = pattern.rstrip("/")
                cmd.append(f"--exclude-dir={dir_pattern}")
            else:
                cmd.append(f"--exclude={pattern}")

        cmd.extend(["-e", args.pattern, args.path])

        return cmd

    async def _execute_search(self, cmd: list[str]) -> tuple[str, bytes, bytes]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.default_timeout
                )
            except TimeoutError:
                await kill_async_subprocess(proc, kill_process_group=False)
                raise ToolError(
                    f"Search timed out after {self.config.default_timeout}s"
                )

            stdout = (
                stdout_bytes.decode("utf-8", errors="ignore") if stdout_bytes else ""
            )
            stderr = (
                stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
            )

            if proc.returncode not in {0, 1}:
                error_msg = stderr or f"Process exited with code {proc.returncode}"
                raise ToolError(f"grep error: {error_msg}")

            return stdout, stdout_bytes or b"", stderr_bytes or b""

        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Error running grep: {exc}") from exc

    def _parse_output(self, stdout: str, max_matches: int) -> GrepResult:
        output_lines = stdout.splitlines() if stdout else []
        total_lines = len(output_lines)

        truncated_lines = output_lines[:max_matches]
        truncated_output = "\n".join(truncated_lines)

        was_truncated = (
            total_lines > max_matches
            or len(truncated_output) > self.config.max_output_bytes
        )

        final_output = truncated_output[: self.config.max_output_bytes]

        return GrepResult(
            matches=final_output,
            match_count=len(truncated_lines),
            total_match_count=total_lines,
            was_truncated=was_truncated,
        )

    @classmethod
    def format_call_display(cls, args: GrepArgs) -> ToolCallDisplay:
        summary = f"Grepping '{args.pattern}'"
        if args.path != ".":
            summary += f" in {args.path}"
        if args.max_matches:
            summary += f" (max {args.max_matches} matches)"
        if not args.use_default_ignore:
            summary += " [no-ignore]"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, GrepResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        message = f"Found {event.result.match_count} matches"
        if event.result.was_truncated:
            message += " (truncated)"

        warnings = []
        if event.result.was_truncated:
            warnings.append("Output was truncated due to size/match limits")

        return ToolResultDisplay(success=True, message=message, warnings=warnings)

    @classmethod
    def get_status_text(cls) -> str:
        return "Searching files"


# ── module-level evidence helpers ──────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _repo_relative(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path


def _compute_result_set_sha256(
    items: list[SearchResultItem], total_count: int, file_count: int
) -> str:
    payload = {
        "total_match_count": total_count,
        "matched_file_count": file_count,
        "items": [
            {
                "relative_path": i.relative_path,
                "start_line": i.start_line,
                "excerpt": i.excerpt,
            }
            for i in items
        ],
    }
    return _sha256_bytes(dump_canonical_json(payload).encode("utf-8"))
