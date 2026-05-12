from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import os
from pathlib import Path
from typing import Any, ClassVar, final
from abc import ABC

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolResultEvent, ToolStreamEvent


class GitResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int
    argv: list[str]


class GitToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_output_bytes: int = Field(
        default=64_000, description="Maximum total bytes to capture from git output."
    )
    timeout: int = Field(
        default=30, description="Default timeout for git commands in seconds."
    )


async def _run_git_command(
    argv: list[str], config: GitToolConfig, ctx: InvokeContext | None = None
) -> GitResult:
    """Run a git command using create_subprocess_exec and return structured results."""
    env = {
        **os.environ,
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "en_US.UTF-8",
    }

    # Use context workdir if available, otherwise cwd
    cwd = Path.cwd()
    if ctx and ctx.session_dir:
        # Note: session_dir might not be the project root, but Path.cwd() in Rig Relay 
        # is typically the project root during invocation.
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
            cwd=str(cwd),
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=config.timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise ToolError(f"Git command timed out after {config.timeout}s: git {' '.join(argv)}")

        stdout = stdout_bytes.decode("utf-8", errors="replace")[: config.max_output_bytes]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[: config.max_output_bytes]
        returncode = proc.returncode or 0

        if returncode != 0:
            error_msg = f"Git command failed with exit code {returncode}\n"
            error_msg += f"Command: git {' '.join(argv)}\n"
            if stderr:
                error_msg += f"Stderr: {stderr.strip()}\n"
            if stdout:
                error_msg += f"Stdout: {stdout.strip()}\n"
            raise ToolError(error_msg.strip())

        return GitResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            argv=["git"] + argv,
        )
    except Exception as e:
        if isinstance(e, ToolError):
            raise
        raise ToolError(f"Failed to execute git command: {e}") from e


def _normalize_paths(paths: list[str]) -> list[str]:
    """Normalize paths and prevent them from being interpreted as options."""
    if not paths:
        return []
    
    clean_paths = []
    for p in paths:
        clean_paths.append(p)
    return clean_paths


class _GitToolBase[TArgs: BaseModel](
    BaseTool[TArgs, GitResult, GitToolConfig, BaseToolState],
    ToolUIData[TArgs, GitResult],
    ABC,
):
    @classmethod
    def get_status_text(cls) -> str:
        return "Running git command"


# --- Git Status ---

class GitStatusArgs(BaseModel):
    short: bool = Field(default=True, description="Show status in short format.")
    branch: bool = Field(default=True, description="Show branch information.")
    porcelain: bool = Field(default=False, description="Use porcelain format (machine-readable).")


class GitStatus(_GitToolBase[GitStatusArgs]):
    description: ClassVar[str] = "Get the status of the repository (git status)."

    @classmethod
    def format_call_display(cls, args: GitStatusArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="git status")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=True, message="Fetched repository status")

    async def run(
        self, args: GitStatusArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["status"]
        if args.short:
            argv.append("--short")
        if args.branch:
            argv.append("--branch")
        if args.porcelain:
            argv.append("--porcelain")
        
        yield await _run_git_command(argv, self.config, ctx)


# --- Git Diff ---

class GitDiffArgs(BaseModel):
    paths: list[str] = Field(default_factory=list, description="Optional paths to limit the diff.")
    cached: bool = Field(default=False, description="Show diff of staged changes.")
    stat: bool = Field(default=False, description="Show stats instead of full patch.")


class GitDiff(_GitToolBase[GitDiffArgs]):
    description: ClassVar[str] = "Show changes between commits, commit and working tree, etc."

    @classmethod
    def format_call_display(cls, args: GitDiffArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"git diff{' --cached' if args.cached else ''}")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=True, message="Fetched git diff")

    async def run(
        self, args: GitDiffArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["diff"]
        if args.cached:
            argv.append("--cached")
        if args.stat:
            argv.append("--stat")
        
        if args.paths:
            argv.append("--")
            argv.extend(_normalize_paths(args.paths))
        
        yield await _run_git_command(argv, self.config, ctx)


# --- Git Log ---

class GitLogArgs(BaseModel):
    max_count: int = Field(default=20, description="Limit the number of commits to show.")
    oneline: bool = Field(default=True, description="Show each commit on a single line.")
    paths: list[str] = Field(default_factory=list, description="Limit log to specific paths.")


class GitLog(_GitToolBase[GitLogArgs]):
    description: ClassVar[str] = "Show the commit logs."

    @classmethod
    def format_call_display(cls, args: GitLogArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"git log -n {args.max_count}")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=True, message="Fetched git log")

    async def run(
        self, args: GitLogArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["log", "-n", str(args.max_count)]
        if args.oneline:
            argv.append("--oneline")
        
        if args.paths:
            argv.append("--")
            argv.extend(_normalize_paths(args.paths))
        
        yield await _run_git_command(argv, self.config, ctx)


# --- Git Branch ---

class GitBranchArgs(BaseModel):
    show_current: bool = Field(default=True, description="Show only the current branch name.")


class GitBranch(_GitToolBase[GitBranchArgs]):
    description: ClassVar[str] = "List, create, or delete branches."

    @classmethod
    def format_call_display(cls, args: GitBranchArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="git branch")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=True, message="Fetched git branch info")

    async def run(
        self, args: GitBranchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["branch"]
        if args.show_current:
            argv.append("--show-current")
        
        yield await _run_git_command(argv, self.config, ctx)


# --- Git Show ---

class GitShowArgs(BaseModel):
    ref: str = Field(default="HEAD", description="The reference to show (e.g., HEAD, a commit hash, a branch name).")
    paths: list[str] = Field(default_factory=list, description="Limit output to specific paths.")


class GitShow(_GitToolBase[GitShowArgs]):
    description: ClassVar[str] = "Show various types of objects (git show)."

    @classmethod
    def format_call_display(cls, args: GitShowArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"git show {args.ref}")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        # Since format_result_display doesn't have access to args, we just use a generic message
        # Or we could override get_result_display if we really want to show the ref
        return ToolResultDisplay(success=True, message="Showed git object")

    async def run(
        self, args: GitShowArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["show", args.ref]
        
        if args.paths:
            argv.append("--")
            argv.extend(_normalize_paths(args.paths))
        
        yield await _run_git_command(argv, self.config, ctx)


# --- Git Ls-Files ---

class GitLsFilesArgs(BaseModel):
    paths: list[str] = Field(default_factory=list, description="Limit listing to specific paths.")
    others: bool = Field(default=False, description="Show untracked files in the output.")
    modified: bool = Field(default=False, description="Show modified files in the output.")
    deleted: bool = Field(default=False, description="Show deleted files in the output.")


class GitLsFiles(_GitToolBase[GitLsFilesArgs]):
    description: ClassVar[str] = "Show information about files in the index and the working tree."

    @classmethod
    def format_call_display(cls, args: GitLsFilesArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="git ls-files")

    @classmethod
    def format_result_display(cls, result: GitResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=True, message="Listed git files")

    async def run(
        self, args: GitLsFilesArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GitResult, None]:
        argv = ["ls-files"]
        if args.others:
            argv.append("--others")
            argv.append("--exclude-standard")
        if args.modified:
            argv.append("--modified")
        if args.deleted:
            argv.append("--deleted")
        
        if args.paths:
            argv.append("--")
            argv.extend(_normalize_paths(args.paths))
        
        yield await _run_git_command(argv, self.config, ctx)
