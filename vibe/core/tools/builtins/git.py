from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.determinism import truncate_text
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.utils import kill_async_subprocess


class GitResult(BaseModel):
    operation: str
    argv: list[str]
    stdout: str
    stderr: str
    returncode: int
    truncated_stdout: bool
    truncated_stderr: bool


class GitToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_output_bytes: int = Field(
        default=64_000, description="Hard cap for Git command output."
    )
    timeout: int = Field(default=30, description="Timeout for Git commands in seconds.")


class GitBase[TArgs: BaseModel](
    BaseTool[TArgs, GitResult, GitToolConfig, BaseToolState],
    ToolUIData[TArgs, GitResult],
    ABC,
):
    @abstractmethod
    async def run(
        self, args: TArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        # This is an abstract base class; sub-classes must implement run.
        raise NotImplementedError
        yield  # type: ignore
    async def _run_git(self, operation: str, args: list[str]) -> GitResult:
        argv = ["git", operation] + args

        env = os.environ.copy()
        env["GIT_PAGER"] = "cat"
        env["PAGER"] = "cat"
        env["TERM"] = "dumb"
        env["LC_ALL"] = "en_US.UTF-8"

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout
                )
            except TimeoutError:
                await kill_async_subprocess(proc, kill_process_group=False)
                raise ToolError(f"Git {operation} timed out after {self.config.timeout}s")

            stdout_raw = (
                stdout_bytes.decode("utf-8", errors="ignore") if stdout_bytes else ""
            )
            stderr_raw = (
                stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
            )

            stdout, truncated_stdout = truncate_text(
                stdout_raw, self.config.max_output_bytes
            )
            stderr, truncated_stderr = truncate_text(
                stderr_raw, self.config.max_output_bytes
            )

            if proc.returncode != 0:
                raise ToolError(
                    f"Git {operation} failed with code {proc.returncode}\n"
                    f"STDOUT: {stdout[:200]}\n"
                    f"STDERR: {stderr[:200]}"
                )

            return GitResult(
                operation=operation,
                argv=argv,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                truncated_stdout=truncated_stdout,
                truncated_stderr=truncated_stderr,
            )

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Error executing git {operation}: {e}")

    def _validate_path(self, path: str) -> str:
        if not path.strip():
            raise ToolError("Path cannot be empty")
        if path.startswith("-"):
            raise ToolError(f"Path spec cannot start with '-': {path}")

        p = Path(path).expanduser()
        if p.is_absolute():
            try:
                # Must be within workdir
                rel = p.resolve().relative_to(Path.cwd().resolve())
                return str(rel)
            except ValueError:
                raise ToolError(f"Path is outside the project directory: {path}")
        return path

    def _validate_paths(self, paths: list[str]) -> list[str]:
        return [self._validate_path(p) for p in paths]

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        message = f"Git {result.operation} completed."
        warnings = []
        if result.truncated_stdout or result.truncated_stderr:
            warnings.append("Output was truncated due to size limit.")
        return ToolResultDisplay(success=True, message=message, warnings=warnings)


class GitStatusArgs(BaseModel):
    short: bool = True
    branch: bool = True
    porcelain: bool = False


class GitStatus(GitBase[GitStatusArgs]):
    description: ClassVar[str] = "Show the working tree status."

    async def run(
        self, args: GitStatusArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        argv = []
        if args.porcelain:
            argv.append("--porcelain=v1")
        elif args.short:
            argv.append("--short")

        if args.branch:
            argv.append("--branch")

        yield await self._run_git("status", argv)

    @classmethod
    def format_call_display(cls, args: GitStatusArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Checking git status")

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking status"


class GitDiffArgs(BaseModel):
    paths: list[str] = Field(default_factory=list)
    cached: bool = False
    stat: bool = False


class GitDiff(GitBase[GitDiffArgs]):
    description: ClassVar[str] = (
        "Show changes between commits, commit and working tree, etc."
    )

    async def run(
        self, args: GitDiffArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        argv = []
        if args.cached:
            argv.append("--cached")
        if args.stat:
            argv.append("--stat")

        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        yield await self._run_git("diff", argv)

    @classmethod
    def format_call_display(cls, args: GitDiffArgs) -> ToolCallDisplay:
        summary = "Checking git diff"
        if args.paths:
            summary += f" for {', '.join(args.paths)}"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking diff"


class GitLogArgs(BaseModel):
    max_count: int = 20
    oneline: bool = True
    paths: list[str] = Field(default_factory=list)


class GitLog(GitBase[GitLogArgs]):
    description: ClassVar[str] = "Show commit logs."

    async def run(
        self, args: GitLogArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        max_count = max(1, min(args.max_count, 100))
        argv = [f"-n{max_count}"]
        if args.oneline:
            argv.append("--oneline")

        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        yield await self._run_git("log", argv)

    @classmethod
    def format_call_display(cls, args: GitLogArgs) -> ToolCallDisplay:
        summary = f"Reading git log (last {args.max_count})"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_status_text(cls) -> str:
        return "Reading log"


class GitBranchArgs(BaseModel):
    show_current: bool = True


class GitBranch(GitBase[GitBranchArgs]):
    description: ClassVar[str] = "List branches."

    async def run(
        self, args: GitBranchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        argv = []
        if args.show_current:
            argv.append("--show-current")
        yield await self._run_git("branch", argv)

    @classmethod
    def format_call_display(cls, args: GitBranchArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Checking current git branch")

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking branch"


class GitShowArgs(BaseModel):
    ref: str
    paths: list[str] = Field(default_factory=list)


class GitShow(GitBase[GitShowArgs]):
    description: ClassVar[str] = "Show various types of objects."

    async def run(
        self, args: GitShowArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        if args.ref.startswith("-"):
            raise ToolError(f"Ref cannot start with '-': {args.ref}")

        argv = [args.ref]
        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        yield await self._run_git("show", argv)

    @classmethod
    def format_call_display(cls, args: GitShowArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Showing git object {args.ref}")

    @classmethod
    def get_status_text(cls) -> str:
        return "Showing object"


class GitLsFilesArgs(BaseModel):
    paths: list[str] = Field(default_factory=list)
    others: bool = False
    modified: bool = False
    deleted: bool = False


class GitLsFiles(GitBase[GitLsFilesArgs]):
    description: ClassVar[str] = (
        "Show information about files in the index and the working tree."
    )

    async def run(
        self, args: GitLsFilesArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitResult, None]:
        argv = []
        if args.others:
            argv.append("--others")
        if args.modified:
            argv.append("--modified")
        if args.deleted:
            argv.append("--deleted")

        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        yield await self._run_git("ls-files", argv)

    @classmethod
    def format_call_display(cls, args: GitLsFilesArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Listing git files")

    @classmethod
    def get_status_text(cls) -> str:
        return "Listing files"
