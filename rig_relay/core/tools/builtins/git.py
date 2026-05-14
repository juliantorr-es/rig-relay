from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import AsyncGenerator
import hashlib
import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from rig_relay.core.telemetry.artifacts import (
    GitStateArtifact,
    GitStateFile,
    ToolOutputArtifactWriter,
)
from rig_relay.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.determinism import truncate_text
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.utils import kill_async_subprocess


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
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

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
                raise ToolError(
                    f"Git {operation} timed out after {self.config.timeout}s"
                )

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
    _STATUS_LINE_PATH_OFFSET: ClassVar[int] = 3

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

        result = await self._run_git("status", argv)
        if ctx and ctx.session_dir and ctx.tool_call_id:
            try:
                await self._emit_git_state_artifact(result, ctx)
            except Exception:
                pass
        yield result

    async def _emit_git_state_artifact(
        self, result: GitResult, ctx: InvokeContext
    ) -> None:
        payload = await self._build_git_state_payload(result)
        payload["stdout_sha256"] = self._sha256_text(result.stdout)
        payload["stderr_sha256"] = (
            self._sha256_text(result.stderr) if result.stderr else None
        )
        payload["state_sha256"] = self._sha256_payload(payload)
        artifact = GitStateArtifact.model_validate(payload)
        session_dir = ctx.session_dir
        assert session_dir is not None
        writer = ToolOutputArtifactWriter(str(session_dir.name))
        writer.write_git_state_artifact(
            artifact=artifact, tool_call_id=ctx.tool_call_id
        )

    @staticmethod
    def _sha256_text(text: str) -> str:
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _sha256_payload(payload: dict[str, object]) -> str:
        from rig_relay.core.telemetry.local import dump_canonical_json

        return f"sha256:{hashlib.sha256(dump_canonical_json(payload).encode('utf-8')).hexdigest()}"

    async def _build_git_state_payload(self, result: GitResult) -> dict[str, object]:
        branch = await self._read_git_branch()
        head_sha = await self._read_git_head_sha()
        (
            upstream_branch,
            upstream_ahead,
            upstream_behind,
        ) = await self._read_git_upstream()
        dirty_files, staged, unstaged, untracked, conflicted = self._parse_dirty_files(
            result.stdout
        )
        return {
            "tool_name": "git_status",
            "repo_root": Path.cwd().resolve().as_posix(),
            "branch": branch,
            "head_sha": head_sha,
            "head_short_sha": head_sha[:7] if head_sha else None,
            "upstream_branch": upstream_branch,
            "upstream_ahead_count": upstream_ahead,
            "upstream_behind_count": upstream_behind,
            "is_detached_head": branch is None,
            "is_dirty": bool(dirty_files),
            "dirty_file_count": len(dirty_files),
            "staged_file_count": staged,
            "unstaged_file_count": unstaged,
            "untracked_file_count": untracked,
            "conflict_file_count": conflicted,
            "ignored_file_count": None,
            "dirty_files": [item.model_dump() for item in dirty_files],
            "ordering_policy": "rig_normalized_path_kind",
            "warnings": [],
        }

    async def _read_git_head_sha(self) -> str | None:
        try:
            result = await self._run_git("rev-parse", ["HEAD"])
        except ToolError:
            return None
        return result.stdout.strip() or None

    async def _read_git_branch(self) -> str | None:
        try:
            result = await self._run_git("branch", ["--show-current"])
        except ToolError:
            return None
        branch = result.stdout.strip()
        return branch or None

    async def _read_git_upstream(self) -> tuple[str | None, int | None, int | None]:
        try:
            branch_result = await self._run_git(
                "rev-parse", ["--abbrev-ref", "--symbolic-full-name", "@{u}"]
            )
            upstream_branch = branch_result.stdout.strip() or None
            if upstream_branch is None:
                return None, None, None
            counts_result = await self._run_git(
                "rev-list", ["--left-right", "--count", "HEAD...@{u}"]
            )
            ahead_text, behind_text = counts_result.stdout.strip().split("\t", 1)
            return upstream_branch, int(ahead_text), int(behind_text)
        except (ToolError, ValueError):
            return None, None, None

    def _parse_dirty_files(
        self, stdout: str
    ) -> tuple[list[GitStateFile], int, int, int, int]:
        dirty_files: list[GitStateFile] = []
        seen_paths: set[str] = set()
        staged = unstaged = untracked = conflicted = 0

        for line in stdout.splitlines():
            if not line or line.startswith("## "):
                continue
            parsed = self._parse_status_line(line)
            if parsed is None:
                continue
            rel, status = parsed
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            staged_flag = self._is_staged_status(status)
            unstaged_flag = self._is_unstaged_status(status)
            untracked_flag = status == "??"
            conflicted_flag = "U" in status
            staged += int(staged_flag)
            unstaged += int(unstaged_flag)
            untracked += int(untracked_flag)
            conflicted += int(conflicted_flag)
            dirty_files.append(
                GitStateFile(
                    relative_path=rel,
                    change_kind=status.strip() or "unknown",
                    staged=staged_flag,
                    unstaged=unstaged_flag,
                    untracked=untracked_flag,
                    conflicted=conflicted_flag,
                )
            )

        dirty_files.sort(key=lambda item: (item.relative_path, item.change_kind))
        return dirty_files, staged, unstaged, untracked, conflicted

    @staticmethod
    def _parse_status_line(line: str) -> tuple[str, str] | None:
        if len(line) <= GitStatus._STATUS_LINE_PATH_OFFSET:
            return None
        status = line[:2]
        path = line[GitStatus._STATUS_LINE_PATH_OFFSET :]
        return Path(path).as_posix(), status

    @staticmethod
    def _is_staged_status(status: str) -> bool:
        return status[0] not in {" ", "?"}

    @staticmethod
    def _is_unstaged_status(status: str) -> bool:
        return status[1] not in {" ", "?"}

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
