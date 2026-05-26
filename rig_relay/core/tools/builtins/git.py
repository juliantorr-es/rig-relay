from __future__ import annotations

from abc import ABC
import asyncio
from collections.abc import AsyncGenerator
import hashlib
import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.artifacts import (
    GitStateArtifact,
    GitStateFile,
    ToolOutputArtifactWriter,
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
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.determinism import truncate_text
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.utils import kill_async_subprocess

# ── Bounded Git evidence result models (Lane B3) ──────────────────────


class _GitEvidenceModel(BaseModel):
    """Mixin for bounded Git evidence with redaction and integrity."""

    def _evidence_digest(self) -> str:
        raw = self.model_dump_json()
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def redacted_projection(self) -> dict[str, Any]:
        raise NotImplementedError


class GitStatusResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "status"
    branch: str | None = None
    head_sha: str | None = None
    upstream: str | None = None
    ahead_count: int = 0
    behind_count: int = 0
    is_detached: bool = False
    repository_state: str = "unknown"
    staged_count: int = 0
    unstaged_count: int = 0
    untracked_count: int = 0
    conflicted_count: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "repository_state": self.repository_state,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "is_detached": self.is_detached,
            "ahead_count": self.ahead_count,
            "behind_count": self.behind_count,
            "staged_count": self.staged_count,
            "unstaged_count": self.unstaged_count,
            "untracked_count": self.untracked_count,
            "conflicted_count": self.conflicted_count,
            "changed_paths_count": len(self.changed_paths),
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


class GitDiffResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "diff"
    branch: str | None = None
    head_sha: str | None = None
    files_changed_count: int = 0
    additions: int = 0
    deletions: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    change_kinds: dict[str, str] = Field(default_factory=dict)
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "files_changed_count": self.files_changed_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "change_kind_summary": {
                k: v
                for k, v in {
                    "added": sum(1 for ck in self.change_kinds.values() if ck == "A"),
                    "modified": sum(
                        1 for ck in self.change_kinds.values() if ck == "M"
                    ),
                    "deleted": sum(1 for ck in self.change_kinds.values() if ck == "D"),
                    "renamed": sum(
                        1 for ck in self.change_kinds.values() if ck.startswith("R")
                    ),
                    "copied": sum(
                        1 for ck in self.change_kinds.values() if ck.startswith("C")
                    ),
                }.items()
                if v > 0
            },
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


class GitLogResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "log"
    branch: str | None = None
    head_sha: str | None = None
    commits: list[str] = Field(default_factory=list)
    commits_returned: int = 0
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "commits_returned": self.commits_returned,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


class GitBranchResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "branch"
    branch: str | None = None
    head_sha: str | None = None
    current_branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    is_detached: bool = False
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "current_branch_available": self.current_branch is not None,
            "branches_count": len(self.branches),
            "is_detached": self.is_detached,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


class GitShowResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "show"
    branch: str | None = None
    head_sha: str | None = None
    commit_sha: str | None = None
    author_date: str | None = None
    subject: str | None = None
    files_changed_count: int = 0
    additions: int = 0
    deletions: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "commit_sha": self.commit_sha,
            "subject_available": self.subject is not None,
            "files_changed_count": self.files_changed_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


class GitLsFilesResult(_GitEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = "ls_files"
    branch: str | None = None
    head_sha: str | None = None
    paths: list[str] = Field(default_factory=list)
    paths_returned: int = 0
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "branch_available": self.branch is not None,
            "head_sha": self.head_sha,
            "paths_returned": self.paths_returned,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


# ── Raw subprocess result (kept internal for _run_git) ────────────────


class _RawGitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    argv: list[str] = Field(default_factory=list)
    stdout: str
    stderr: str
    returncode: int
    truncated_stdout: bool
    truncated_stderr: bool


# ── Backward compatibility alias for tests that still reference GitResult ─
GitResult = _RawGitResult


# ── Config ────────────────────────────────────────────────────────────


class GitToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_output_bytes: int = Field(
        default=64_000, description="Hard cap for Git command output."
    )
    timeout: int = Field(default=30, description="Timeout for Git commands in seconds.")


# ── Base class (generic over args and result) ─────────────────────────


class GitBase[TArgs: BaseModel, TResult: BaseModel](
    BaseTool[TArgs, TResult, GitToolConfig, BaseToolState],
    ToolUIData[TArgs, TResult],
    ABC,
):
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    async def run(
        self, args: TArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[TResult, None]:
        raise NotImplementedError
        yield  # type: ignore

    async def _run_git(self, operation: str, args: list[str]) -> _RawGitResult:
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
                error_kind = self._classify_git_error(stderr)
                err = ToolError(
                    f"Git {operation} failed with code {proc.returncode}\n"
                    f"STDERR: {stderr[:200]}"
                )
                err.error_kind = error_kind  # type: ignore[attr-defined]
                raise err

            return _RawGitResult(
                operation=operation,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                truncated_stdout=truncated_stdout,
                truncated_stderr=truncated_stderr,
            )

        except ToolError:
            raise
        except Exception as e:
            err = ToolError(f"Error executing git {operation}: {e}")
            err.error_kind = "git_command_failed"  # type: ignore[attr-defined]
            raise err

    async def _read_head(self) -> str | None:
        try:
            r = await self._run_git("rev-parse", ["HEAD"])
            return r.stdout.strip() or None
        except ToolError:
            return None

    async def _read_branch(self) -> str | None:
        try:
            r = await self._run_git("branch", ["--show-current"])
            return r.stdout.strip() or None
        except ToolError:
            return None

    @staticmethod
    def _classify_git_error(stderr: str) -> str:
        stderr_lower = stderr.lower()
        if "not a git repository" in stderr_lower:
            return "invalid_revision"
        if "did not match any file" in stderr_lower or "pathspec" in stderr_lower:
            return "invalid_pathspec"
        if "does not have any commits" in stderr_lower:
            return "no_history"
        return "git_command_failed"

    def _validate_path(self, path: str) -> str:
        if not path.strip():
            raise ToolError("Path cannot be empty")
        if path.startswith("-"):
            raise ToolError(f"Path spec cannot start with '-': {path}")
        p = Path(path).expanduser()
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(Path.cwd().resolve())
                return str(rel)
            except ValueError:
                raise ToolError(f"Path is outside the project directory: {path}")
        return path

    def _validate_paths(self, paths: list[str]) -> list[str]:
        return [self._validate_path(p) for p in paths]

    async def _verify_commit_ref(self, rev: str) -> str:
        """Validate a revision as a commit object via git rev-parse --verify.

        Rejects option-shaped revisions, ambiguous names, non-commit objects,
        and invalid refs. Returns the full 40-char SHA on success.
        """
        if rev.startswith("-"):
            raise ToolError(f"Revision cannot start with '-': {rev}")
        try:
            result = await self._run_git(
                "rev-parse", ["--verify", "--end-of-options", f"{rev}^{{commit}}"]
            )
        except ToolError as exc:
            raise ToolError(f"Revision '{rev}' is not a valid commit object") from exc
        sha = result.stdout.strip()
        if not sha or len(sha) < 7:
            raise ToolError(f"Revision '{rev}' resolved to invalid SHA: {sha!r}")
        return sha


# ── Git status ────────────────────────────────────────────────────────


class GitStatusArgs(BaseModel):
    short: bool = Field(default=False, description="Use short format (--short).")
    branch: bool = Field(
        default=True, description="Show branch and upstream tracking info (--branch)."
    )
    porcelain: bool = Field(
        default=False, description="Machine-readable porcelain v1 format."
    )


class GitStatus(GitBase[GitStatusArgs, GitStatusResult]):
    description: ClassVar[str] = (
        "Bounded workspace status. Returns structured branch, head, and dirty-state "
        "evidence. For checkpoint eligibility, prefer git_workspace_state."
    )

    async def run(
        self, args: GitStatusArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitStatusResult, None]:
        head = await self._read_head()
        branch = await self._read_branch()

        argv = ["--porcelain=v2", "--branch"]
        if args.short:
            argv = ["--short", "--branch"]

        try:
            raw = await self._run_git("status", argv)
        except ToolError as exc:
            yield GitStatusResult(
                branch=branch,
                head_sha=head,
                error_kind=getattr(exc, "error_kind", "git_command_failed"),
                truncated=exc.error_kind == "output_truncated"
                if hasattr(exc, "error_kind")
                else False,
            )
            return

        is_detached = branch is None
        repo_state: str = "clean"
        staged = unstaged = untracked = conflicted = 0
        upstream_val: str | None = None
        ahead = behind = 0
        changed: list[str] = []

        for line in raw.stdout.splitlines():
            if not line:
                continue
            if line.startswith("# branch.oid "):
                sha = line.split(" ", 2)[-1] if len(line.split(" ", 2)) > 2 else None
                if sha and sha != "(initial)":
                    head = sha
            elif line.startswith("# branch.head "):
                b = line.split(" ", 2)[-1] if len(line.split(" ", 2)) > 2 else None
                if b and b != "(detached)":
                    branch = b
            elif line.startswith("# branch.upstream "):
                upstream_val = (
                    line.split(" ", 2)[-1] if len(line.split(" ", 2)) > 2 else None
                )
            elif line.startswith("# branch.ab "):
                parts = line.split(" ")
                if len(parts) >= 3:
                    ahead = int(parts[2].lstrip("+"))
                if len(parts) >= 4:
                    behind = int(parts[3].lstrip("-"))
            elif line.startswith("?"):
                untracked += 1
                if len(line) > 2:
                    changed.append(line[2:].strip())
            elif line.startswith("u"):
                conflicted += 1
            elif line and line[0] in "12":
                xy = line[2:4] if len(line) > 3 else ""
                if xy and xy[0] not in {" ", "?", "!"}:
                    staged += 1
                if xy and xy[1] not in {" ", "?", "!"}:
                    unstaged += 1
                path_part = line.split(" ") if len(line) > 5 else []
                if not args.short and xy and (xy[0] != " " or xy[1] != " "):
                    changed.append(path_part[-1] if path_part else "")

        if staged or unstaged or untracked or conflicted:
            repo_state = "dirty"
        if conflicted:
            repo_state = "conflicted"

        result = GitStatusResult(
            branch=branch,
            head_sha=head,
            upstream=upstream_val,
            ahead_count=ahead,
            behind_count=behind,
            is_detached=is_detached,
            repository_state=repo_state,
            staged_count=staged,
            unstaged_count=unstaged,
            untracked_count=untracked,
            conflicted_count=conflicted,
            changed_paths=changed,
            truncated=raw.truncated_stdout,
            error_kind=None,
        )

        if ctx and ctx.session_dir and ctx.tool_call_id:
            try:
                await self._emit_git_state_artifact(
                    head,
                    branch,
                    upstream_val,
                    ahead,
                    behind,
                    changed,
                    staged,
                    unstaged,
                    untracked,
                    conflicted,
                    ctx,
                )
            except Exception:
                pass
        yield result

    async def _emit_git_state_artifact(
        self,
        head_sha: str | None,
        branch: str | None,
        upstream_branch: str | None,
        ahead: int,
        behind: int,
        changed_paths: list[str],
        staged: int,
        unstaged: int,
        untracked: int,
        conflicted: int,
        ctx: InvokeContext,
    ) -> None:
        from rig_relay.core.telemetry.local import dump_canonical_json

        payload: dict[str, object] = {
            "tool_name": "git_status",
            "repo_root": Path.cwd().resolve().as_posix(),
            "branch": branch,
            "head_sha": head_sha,
            "head_short_sha": head_sha[:7] if head_sha else None,
            "upstream_branch": upstream_branch,
            "upstream_ahead_count": ahead,
            "upstream_behind_count": behind,
            "is_detached_head": branch is None,
            "is_dirty": bool(changed_paths),
            "dirty_file_count": len(changed_paths),
            "staged_file_count": staged,
            "unstaged_file_count": unstaged,
            "untracked_file_count": untracked,
            "conflict_file_count": conflicted,
            "ignored_file_count": None,
            "dirty_files": changed_paths,
            "ordering_policy": "rig_normalized_path_kind",
            "warnings": [],
        }
        payload["stdout_sha256"] = "sha256:n/a"
        payload["state_sha256"] = (
            f"sha256:{hashlib.sha256(dump_canonical_json(payload).encode('utf-8')).hexdigest()}"
        )
        artifact = GitStateArtifact.model_validate(payload)
        session_dir = ctx.session_dir
        assert session_dir is not None
        writer = ToolOutputArtifactWriter(str(session_dir.name))
        writer.write_git_state_artifact(
            artifact=artifact, tool_call_id=ctx.tool_call_id
        )

    @classmethod
    def format_call_display(cls, args: GitStatusArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Checking git status")

    @classmethod
    def format_result_display(cls, result: GitStatusResult) -> ToolResultDisplay:
        warnings: list[str] = []
        if result.truncated:
            warnings.append("Output was truncated due to size limit.")
        if result.is_detached:
            warnings.append("Repository is in detached HEAD state.")
        return ToolResultDisplay(
            success=result.error_kind is None,
            message=f"Git status: {result.repository_state}, branch={result.branch or '(detached)'}",
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking status"

    @staticmethod
    def _sha256_text(text: str) -> str:
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _sha256_payload(payload: dict[str, object]) -> str:
        from rig_relay.core.telemetry.local import dump_canonical_json

        return f"sha256:{hashlib.sha256(dump_canonical_json(payload).encode('utf-8')).hexdigest()}"

    async def _build_git_state_payload(self, raw: _RawGitResult) -> dict[str, object]:
        """Backward-compatible payload builder for artifact emission tests."""
        branch = await self._read_branch()
        head = await self._read_head()
        upstream_branch, ahead, behind = None, None, None
        try:
            r = await self._run_git(
                "rev-parse", ["--abbrev-ref", "--symbolic-full-name", "@{u}"]
            )
            upstream_branch = r.stdout.strip() or None
            if upstream_branch:
                c = await self._run_git(
                    "rev-list", ["--left-right", "--count", "HEAD...@{u}"]
                )
                a_s, b_s = c.stdout.strip().split("\t", 1)
                ahead, behind = int(a_s), int(b_s)
        except (ToolError, ValueError):
            pass
        dirty_files_raw, staged, unstaged, untracked, conflicted = (
            self._parse_dirty_files(raw.stdout)
        )
        return {
            "tool_name": "git_status",
            "repo_root": Path.cwd().resolve().as_posix(),
            "branch": branch,
            "head_sha": head,
            "head_short_sha": head[:7] if head else None,
            "upstream_branch": upstream_branch,
            "upstream_ahead_count": ahead,
            "upstream_behind_count": behind,
            "is_detached_head": branch is None,
            "is_dirty": bool(dirty_files_raw),
            "dirty_file_count": len(dirty_files_raw),
            "staged_file_count": staged,
            "unstaged_file_count": unstaged,
            "untracked_file_count": untracked,
            "conflict_file_count": conflicted,
            "ignored_file_count": None,
            "dirty_files": [item.model_dump() for item in dirty_files_raw],
            "ordering_policy": "rig_normalized_path_kind",
            "warnings": [],
        }

    @staticmethod
    def _parse_dirty_files(
        stdout: str,
    ) -> tuple[list[GitStateFile], int, int, int, int]:
        dirty_files: list[GitStateFile] = []
        seen_paths: set[str] = set()
        staged = unstaged = untracked = conflicted = 0
        for line in stdout.splitlines():
            if not line or line.startswith("## "):
                continue
            if len(line) <= 3:
                continue
            status = line[:2]
            path = line[3:]
            rel = Path(path).as_posix()
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            staged_flag = status[0] not in {" ", "?"}
            unstaged_flag = status[1] not in {" ", "?"}
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


# ── Git diff ─────────────────────────────────────────────────────────


class GitDiffArgs(BaseModel):
    paths: list[str] = Field(
        default_factory=list, description="Files to diff. Empty = all changed files."
    )
    cached: bool = Field(default=False, description="Show staged changes (--cached).")
    stat: bool = Field(default=False, description="Show diffstat only (--stat).")


class GitDiff(GitBase[GitDiffArgs, GitDiffResult]):
    description: ClassVar[str] = (
        "Bounded diff evidence. Returns change statistics (--numstat) and change-kind "
        "classifications (--name-status) without raw patch content."
    )

    async def run(
        self, args: GitDiffArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitDiffResult, None]:
        head = await self._read_head()
        branch = await self._read_branch()

        argv: list[str] = []
        if args.cached:
            argv.append("--cached")
        argv.append("--numstat")
        if args.stat:
            argv.append("--stat")
        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        additions = deletions = 0
        changed: list[str] = []
        change_kinds: dict[str, str] = {}

        try:
            raw_numstat = await self._run_git("diff", argv)
        except ToolError as exc:
            ek = getattr(exc, "error_kind", "git_command_failed")
            if ek == "invalid_pathspec":
                yield GitDiffResult(
                    branch=branch, head_sha=head, error_kind=ek, files_changed_count=0
                )
                return
            raise

        for line in raw_numstat.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    additions += int(parts[0]) if parts[0] != "-" else 0
                    deletions += int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    pass
                p = parts[2]
                if p not in changed:
                    changed.append(p)

        try:
            argv_name = [a for a in argv if a != "--numstat"]
            if "--stat" in argv_name:
                argv_name.remove("--stat")
            argv_name.append("--name-status")
            if args.paths:
                pass
            raw_names = await self._run_git("diff", argv_name)
            for line in raw_names.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    change_kinds[parts[1]] = parts[0]
        except ToolError:
            pass

        yield GitDiffResult(
            branch=branch,
            head_sha=head,
            files_changed_count=len(changed),
            additions=additions,
            deletions=deletions,
            changed_paths=changed,
            change_kinds=change_kinds,
            truncated=raw_numstat.truncated_stdout,
        )

    @classmethod
    def format_call_display(cls, args: GitDiffArgs) -> ToolCallDisplay:
        summary = "Checking git diff"
        if args.paths:
            summary += f" for {', '.join(args.paths)}"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def format_result_display(cls, result: GitDiffResult) -> ToolResultDisplay:
        warnings: list[str] = []
        if result.truncated:
            warnings.append("Output was truncated due to size limit.")
        return ToolResultDisplay(
            success=result.error_kind is None,
            message=(
                f"Git diff: {result.files_changed_count} files changed "
                f"(+{result.additions}/-{result.deletions})"
            ),
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking diff"


# ── Git log ───────────────────────────────────────────────────────────


class GitLogArgs(BaseModel):
    max_count: int = Field(
        default=20, description="Number of commits to show. Capped at 100."
    )
    oneline: bool = Field(default=True, description="Single-line format.")
    paths: list[str] = Field(
        default_factory=list,
        description="Filter commits affecting these files. Empty = all history.",
    )


class GitLog(GitBase[GitLogArgs, GitLogResult]):
    description: ClassVar[str] = (
        "Bounded commit log. Returns structured commit hashes and subjects "
        "via --format, not raw git porcelain output."
    )

    async def run(
        self, args: GitLogArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitLogResult, None]:
        max_count = max(1, min(args.max_count, 100))
        head = await self._read_head()
        branch = await self._read_branch()

        fmt = "%H %s" if args.oneline else "%H%n%aI%n%s%n---EOC---"
        argv = [f"--format={fmt}", f"--max-count={max_count}"]
        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        commits: list[str] = []
        truncated = False
        try:
            raw = await self._run_git("log", argv)
            truncated = raw.truncated_stdout
            for line in raw.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("---EOC---"):
                    commits.append(line)
        except ToolError as exc:
            ek = getattr(exc, "error_kind", "git_command_failed")
            yield GitLogResult(
                branch=branch, head_sha=head, error_kind=ek, commits_returned=0
            )
            return

        yield GitLogResult(
            branch=branch,
            head_sha=head,
            commits=commits,
            commits_returned=len(commits),
            truncated=truncated,
        )

    @classmethod
    def format_call_display(cls, args: GitLogArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Reading git log (last {args.max_count})")

    @classmethod
    def format_result_display(cls, result: GitLogResult) -> ToolResultDisplay:
        warnings: list[str] = []
        if result.truncated:
            warnings.append("Output was truncated due to size limit.")
        return ToolResultDisplay(
            success=result.error_kind is None,
            message=f"Git log: {result.commits_returned} commits",
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Reading log"


# ── Git branch ────────────────────────────────────────────────────────


class GitBranchArgs(BaseModel):
    show_current: bool = Field(
        default=True,
        description="Show only current branch name. Set False to list all branches.",
    )


class GitBranch(GitBase[GitBranchArgs, GitBranchResult]):
    description: ClassVar[str] = (
        "Bounded branch information. Returns current branch or full branch list "
        "without raw git output."
    )

    async def run(
        self, args: GitBranchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitBranchResult, None]:
        head = await self._read_head()
        branch = await self._read_branch()

        if args.show_current:
            yield GitBranchResult(
                branch=branch,
                head_sha=head,
                current_branch=branch,
                is_detached=branch is None,
            )
            return

        branches: list[str] = []
        try:
            raw = await self._run_git("branch", [])
            for line in raw.stdout.splitlines():
                stripped = line.strip().lstrip("* ")
                if stripped:
                    branches.append(stripped)
        except ToolError as exc:
            ek = getattr(exc, "error_kind", "git_command_failed")
            yield GitBranchResult(branch=branch, head_sha=head, error_kind=ek)
            return

        yield GitBranchResult(
            branch=branch,
            head_sha=head,
            current_branch=branch,
            branches=branches,
            is_detached=branch is None,
            truncated=raw.truncated_stdout if "raw" in dir() else False,
        )

    @classmethod
    def format_call_display(cls, args: GitBranchArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Checking current git branch")

    @classmethod
    def format_result_display(cls, result: GitBranchResult) -> ToolResultDisplay:
        msg = f"Git branch: {result.current_branch or '(detached)'}"
        if result.branches:
            msg += f" ({len(result.branches)} branches)"
        return ToolResultDisplay(success=result.error_kind is None, message=msg)

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking branch"


# ── Git show ──────────────────────────────────────────────────────────


class GitShowArgs(BaseModel):
    ref: str = Field(
        description="Git ref to show: SHA, branch name, tag, or relative (HEAD~1)."
    )
    paths: list[str] = Field(
        default_factory=list, description="Restrict diff to these paths."
    )


class GitShow(GitBase[GitShowArgs, GitShowResult]):
    description: ClassVar[str] = (
        "Bounded commit inspection. Returns structured commit metadata and change "
        "statistics without raw patch content."
    )

    async def run(
        self, args: GitShowArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitShowResult, None]:
        if args.ref.startswith("-"):
            raise ToolError(f"Ref cannot start with '-': {args.ref}")

        verified_ref = await self._verify_commit_ref(args.ref)

        head = await self._read_head()
        branch = await self._read_branch()

        fmt_argv = ["--format=%H%x00%aI%x00%s", "--numstat", "-z", verified_ref]
        if args.paths:
            fmt_argv.append("--")
            fmt_argv.extend(self._validate_paths(args.paths))

        try:
            raw = await self._run_git("show", fmt_argv)
        except ToolError as exc:
            ek = getattr(exc, "error_kind", "git_command_failed")
            yield GitShowResult(
                branch=branch, head_sha=head, error_kind=ek, commit_sha=args.ref
            )
            return

        parts = raw.stdout.split("\0")
        commit_sha = parts[0] if len(parts) > 0 else args.ref
        author_date = parts[1] if len(parts) > 1 else None
        subject = parts[2] if len(parts) > 2 else None

        additions = deletions = 0
        changed: list[str] = []
        for part in parts[3:]:
            part = part.strip()
            if not part:
                continue
            tab_parts = part.split("\t")
            if len(tab_parts) >= 3:
                try:
                    additions += int(tab_parts[0]) if tab_parts[0] != "-" else 0
                    deletions += int(tab_parts[1]) if tab_parts[1] != "-" else 0
                except ValueError:
                    pass
                changed.append(tab_parts[2])

        yield GitShowResult(
            branch=branch,
            head_sha=head,
            commit_sha=commit_sha,
            author_date=author_date,
            subject=subject,
            files_changed_count=len(changed),
            additions=additions,
            deletions=deletions,
            changed_paths=changed,
            truncated=raw.truncated_stdout,
        )

    @classmethod
    def format_call_display(cls, args: GitShowArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Showing git object {args.ref}")

    @classmethod
    def format_result_display(cls, result: GitShowResult) -> ToolResultDisplay:
        return ToolResultDisplay(
            success=result.error_kind is None,
            message=(
                f"Git show {result.commit_sha}: {result.files_changed_count} files "
                f"(+{result.additions}/-{result.deletions})"
            ),
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Showing object"


# ── Git ls-files ──────────────────────────────────────────────────────


class GitLsFilesArgs(BaseModel):
    paths: list[str] = Field(
        default_factory=list, description="Files to check. Empty = all tracked files."
    )
    others: bool = Field(default=False, description="Show untracked files (--others).")
    modified: bool = Field(
        default=False, description="Show modified files (--modified)."
    )
    deleted: bool = Field(default=False, description="Show deleted files (--deleted).")


class GitLsFiles(GitBase[GitLsFilesArgs, GitLsFilesResult]):
    description: ClassVar[str] = (
        "Bounded file listing. Returns NUL-delimited file paths without raw git output."
    )

    async def run(
        self, args: GitLsFilesArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[GitLsFilesResult, None]:
        head = await self._read_head()
        branch = await self._read_branch()

        argv: list[str] = ["-z"]
        if args.others:
            argv.append("--others")
        if args.modified:
            argv.append("--modified")
        if args.deleted:
            argv.append("--deleted")
        if args.paths:
            argv.append("--")
            argv.extend(self._validate_paths(args.paths))

        try:
            raw = await self._run_git("ls-files", argv)
        except ToolError as exc:
            ek = getattr(exc, "error_kind", "git_command_failed")
            yield GitLsFilesResult(
                branch=branch, head_sha=head, error_kind=ek, paths_returned=0
            )
            return

        paths = [p for p in raw.stdout.split("\0") if p]

        yield GitLsFilesResult(
            branch=branch,
            head_sha=head,
            paths=paths,
            paths_returned=len(paths),
            truncated=raw.truncated_stdout,
        )

    @classmethod
    def format_call_display(cls, args: GitLsFilesArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Listing git files")

    @classmethod
    def format_result_display(cls, result: GitLsFilesResult) -> ToolResultDisplay:
        return ToolResultDisplay(
            success=result.error_kind is None,
            message=f"Git ls-files: {result.paths_returned} files",
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Listing files"
