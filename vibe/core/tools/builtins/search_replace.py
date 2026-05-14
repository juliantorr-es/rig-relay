from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
import difflib
from pathlib import Path
import re
import shutil
import time
from typing import ClassVar, NamedTuple, final

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
)
from vibe.core.tools.determinism import normalize_tool_path, require_path_within_workdir
from vibe.core.tools.permissions import PermissionContext
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.tools.utils import resolve_file_tool_permission, sha256_file_bytes
from vibe.core.types import ToolResultEvent, ToolStreamEvent
from vibe.core.utils.io import ReadSafeResult, read_safe_async

SEARCH_REPLACE_BLOCK_RE = re.compile(
    r"<{5,} SEARCH\r?\n(.*?)\r?\n?={5,}\r?\n(.*?)\r?\n?>{5,} REPLACE", flags=re.DOTALL
)

SEARCH_REPLACE_BLOCK_WITH_FENCE_RE = re.compile(
    r"```[\s\S]*?\n<{5,} SEARCH\r?\n(.*?)\r?\n?={5,}\r?\n(.*?)\r?\n?>{5,} REPLACE\s*\n```",
    flags=re.DOTALL,
)


class SearchReplaceBlock(NamedTuple):
    search: str
    replace: str


class FuzzyMatch(NamedTuple):
    similarity: float
    start_line: int
    end_line: int
    text: str


class BlockApplyResult(NamedTuple):
    content: str
    applied: int
    errors: list[str]
    warnings: list[str]


_MISMATCH_KEYWORDS: dict[str, str] = {
    "Search text not found": "old_text_not_found",
    "search text hasn't been modified": "unchanged_replacement",
}


def _is_binary_content(content: bytes) -> bool:
    """Check if content appears to be binary (contains null bytes)."""
    return b"\x00" in content[:8192] if content else False


def _classify_refusal(check: object) -> str:
    """Classify a guard refusal into a structured error_kind."""
    guard_detail = getattr(check, "detail", "") or getattr(check, "reason", "") or ""
    if "hash" in guard_detail.lower() or "sha256" in guard_detail.lower():
        return "expected_hash_mismatch"
    if "protected" in guard_detail.lower() or "dirty" in guard_detail.lower():
        return "protected_file"
    if "outside" in guard_detail.lower() or "traversal" in guard_detail.lower():
        return "path_refused"
    if "binary" in guard_detail.lower():
        return "binary_file"
    return "protected_file"


def _classify_block_errors(errors: list[str]) -> str:
    """Classify SEARCH/REPLACE block errors into a structured error_kind."""
    for error in errors:
        for keyword, kind in _MISMATCH_KEYWORDS.items():
            if keyword in error:
                return kind
    if errors:
        if any("Expected" in e and "replacements" in e for e in errors):
            return "replacement_count_mismatch"
        if any("allow_multiple=False" in e for e in errors):
            return "multiple_matches_when_single_required"
        if any("encoding" in e.lower() for e in errors):
            return "encoding_error"
    return "old_text_not_found"


class SearchReplaceArgs(BaseModel):
    file_path: str
    content: str
    expected_before_sha256: str | None = Field(
        default=None,
        description=(
            "sha256:<hex> of the file bytes as they exist right now, before your patch. "
            "Required when editing a file that was dirty (modified, staged, or untracked) at session start. "
            "The patch will be REFUSED if this hash does not match the current file bytes — "
            "re-read the file and recompute the hash if you get a stale-hash refusal."
        ),
    )
    expected_replacements: int | None = Field(
        default=None,
        description=(
            "Expected number of replacements. If set and actual replacements differ, "
            "the operation returns count_mismatch without mutating the file."
        ),
    )
    allow_multiple: bool = Field(
        default=True,
        description=(
            "If false, multiple matches for the same search text return "
            "ambiguous_match without mutating the file."
        ),
    )


class SearchReplaceResult(BaseModel):
    file: str
    blocks_applied: int
    lines_changed: int
    content: str
    warnings: list[str] = Field(default_factory=list)
    before_file_sha256: dict[str, str] = Field(default_factory=dict)
    after_file_sha256: dict[str, str] = Field(default_factory=dict)
    changed_files: list[str] = Field(default_factory=list)
    failed_block_count: int = 0
    total_block_count: int = 0
    replacements: int = 0
    before_bytes: int = 0
    after_bytes: int = 0
    status: str = "success"
    error_kind: str | None = None
    refusal_reason: str | None = None
    duration_ms: float | None = None


class SearchReplaceReceipt(BaseModel):
    """Content-light receipt for a search_replace invocation.

    Contains no raw file content, old_text, new_text, diffs, or
    private paths — only metadata, block counts, hashes, byte
    counts, and structured error classification.
    """

    file: str
    status: str = "success"
    blocks_applied: int = 0
    lines_changed: int = 0
    replacements: int = 0
    warnings: list[str] = Field(default_factory=list)
    before_file_sha256: dict[str, str] = Field(default_factory=dict)
    after_file_sha256: dict[str, str] = Field(default_factory=dict)
    changed_files: list[str] = Field(default_factory=list)
    failed_block_count: int = 0
    total_block_count: int = 0
    before_bytes: int = 0
    after_bytes: int = 0
    error_kind: str | None = None
    refusal_reason: str | None = None
    duration_ms: float | None = None


@dataclass(frozen=True)
class SearchReplaceCoordinationContext:
    session_id: str
    task_id: str
    relative_path: str


class SearchReplaceConfig(BaseToolConfig):
    sensitive_patterns: list[str] = Field(
        default=["**/.env", "**/.env.*"],
        description="File patterns that trigger ASK even when permission is ALWAYS.",
    )
    max_content_size: int = 100_000
    create_backup: bool = False
    fuzzy_threshold: float = 0.9


class SearchReplace(
    BaseTool[
        SearchReplaceArgs, SearchReplaceResult, SearchReplaceConfig, BaseToolState
    ],
    ToolUIData[SearchReplaceArgs, SearchReplaceResult],
):
    description: ClassVar[str] = (
        "Replace sections of files using SEARCH/REPLACE blocks. "
        "Supports fuzzy matching and detailed error reporting. "
        "Format: <<<<<<< SEARCH\\n[text]\\n=======\\n[replacement]\\n>>>>>>> REPLACE"
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def format_call_display(cls, args: SearchReplaceArgs) -> ToolCallDisplay:
        tag = " (scratchpad)" if is_scratchpad_path(args.file_path) else ""
        blocks = cls._parse_search_replace_blocks(args.content)
        return ToolCallDisplay(
            summary=f"Patching {args.file_path} ({len(blocks)} blocks){tag}",
            content=args.content,
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if isinstance(event.result, SearchReplaceResult):
            path_name = Path(event.result.file).name
            tag = " (scratchpad)" if is_scratchpad_path(event.result.file) else ""
            return ToolResultDisplay(
                success=True,
                message=f"Applied {event.result.blocks_applied} block{'' if event.result.blocks_applied == 1 else 's'} to {path_name}{tag}",
                warnings=event.result.warnings,
            )

        return ToolResultDisplay(success=True, message="Patch applied")

    @classmethod
    def get_status_text(cls) -> str:
        return "Editing files"

    @staticmethod
    def _coordination_store(ctx: InvokeContext | None) -> CoordinationStore | None:
        if ctx is None or ctx.session_dir is None:
            return None
        return CoordinationStore(Path.cwd() / ".build" / "rig-relay" / "coordination")

    @staticmethod
    def _build_coordination_context(
        ctx: InvokeContext | None, file_path: Path
    ) -> SearchReplaceCoordinationContext | None:
        if ctx is None or ctx.session_dir is None or ctx.tool_call_id is None:
            return None
        return SearchReplaceCoordinationContext(
            session_id=ctx.session_dir.name,
            task_id=ctx.tool_call_id,
            relative_path=file_path.as_posix(),
        )

    @staticmethod
    def _build_coordination_state(
        ctx: InvokeContext | None, file_path: Path
    ) -> tuple[CoordinationStore | None, SearchReplaceCoordinationContext | None]:
        return SearchReplace._coordination_store(
            ctx
        ), SearchReplace._build_coordination_context(ctx, file_path)

    @staticmethod
    def _claim_coordination(
        store: CoordinationStore | None,
        coordination: SearchReplaceCoordinationContext | None,
    ) -> bool:
        if store is None or coordination is None:
            return False
        claim_result = store.claim_task(
            session_id=coordination.session_id,
            task_id=coordination.task_id,
            claim_kind="search_replace",
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
    def _publish_coordination_artifact(
        store: CoordinationStore | None,
        coordination: SearchReplaceCoordinationContext | None,
        result: SearchReplaceResult,
    ) -> None:
        if store is None or coordination is None:
            return
        artifact = ToolOutputArtifactWriter(coordination.session_id).write_artifact(
            tool_name="search_replace",
            raw_output=result.model_dump_json(exclude_none=True),
            source_event_id=coordination.task_id,
        )
        store.publish_artifact(
            session_id=coordination.session_id,
            task_id=coordination.task_id,
            artifact_kind="search_replace",
            artifact_uri=artifact.path,
            artifact_sha256=artifact.artifact_record_sha256 or artifact.payload_sha256,
            schema_id="rig.relay.artifact.envelope.v1",
        )

    @staticmethod
    def _build_search_replace_result(
        *,
        file_path: Path,
        before_hash: str,
        original_content: str,
        modified_content: str,
        block_result: BlockApplyResult,
        total_block_count: int,
    ) -> SearchReplaceResult:
        repo_file_key = SearchReplace._repo_file_key(file_path)

        if modified_content == original_content:
            lines_changed = 0
            after_hash = before_hash
        else:
            lines_changed = len(modified_content.splitlines()) - len(
                original_content.splitlines()
            )
            after_hash = sha256_file_bytes(file_path.read_bytes())
            assert after_hash is not None

        before_bytes = len(original_content.encode("utf-8"))
        after_bytes = len(modified_content.encode("utf-8"))

        return SearchReplaceResult(
            file=str(file_path),
            blocks_applied=block_result.applied,
            lines_changed=lines_changed,
            replacements=block_result.applied,
            warnings=block_result.warnings,
            content=modified_content,
            before_file_sha256={repo_file_key: before_hash},
            after_file_sha256={repo_file_key: after_hash},
            before_bytes=before_bytes,
            after_bytes=after_bytes,
            changed_files=[repo_file_key]
            if modified_content != original_content
            else [],
            failed_block_count=total_block_count - block_result.applied,
            total_block_count=total_block_count,
        )

    async def _apply_search_replace(
        self,
        *,
        file_path: Path,
        search_replace_blocks: list[SearchReplaceBlock],
        total_block_count: int,
        allow_multiple: bool = True,
        expected_replacements: int | None = None,
    ) -> SearchReplaceResult:
        before_snapshot = self.get_file_snapshot_for_path(str(file_path))
        before_hash = sha256_file_bytes(before_snapshot.content)
        assert before_hash is not None
        decoded = await self._read_file(file_path)
        original_content = decoded.text
        block_result = self._apply_blocks(
            original_content,
            search_replace_blocks,
            file_path,
            self.config.fuzzy_threshold,
            allow_multiple=allow_multiple,
            expected_replacements=expected_replacements,
        )

        # ── Structured mismatch: block errors produce a result, not an exception ──
        if block_result.errors:
            error_kind = _classify_block_errors(block_result.errors)
            status = self._classify_status_from_error_kind(error_kind)
            repo_file_key = self._repo_file_key(file_path)
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=block_result.applied,
                lines_changed=0,
                content=original_content,
                before_bytes=len(original_content.encode("utf-8")),
                after_bytes=len(original_content.encode("utf-8")),
                warnings=block_result.warnings,
                before_file_sha256={repo_file_key: before_hash},
                after_file_sha256={repo_file_key: before_hash},
                changed_files=[],
                failed_block_count=total_block_count - block_result.applied,
                total_block_count=total_block_count,
                status=status,
                error_kind=error_kind,
                refusal_reason="SEARCH/REPLACE blocks failed:\n"
                + "\n\n".join(block_result.errors),
            )

        modified_content = block_result.content
        if modified_content != original_content:
            try:
                if self.config.create_backup:
                    await self._backup_file(file_path)
            except Exception:
                pass
            await self._write_file(file_path, modified_content, decoded.encoding)

        return self._build_search_replace_result(
            file_path=file_path,
            before_hash=before_hash,
            original_content=original_content,
            modified_content=modified_content,
            block_result=block_result,
            total_block_count=total_block_count,
        )

    @staticmethod
    def _classify_status_from_error_kind(error_kind: str) -> str:
        """Map error_kind to a structured result status.

        Legacy callers may see status="mismatch" which is still valid;
        new code prefers specific statuses.
        """
        if error_kind in {
            "old_text_not_found",
            "unchanged_replacement",
            "encoding_error",
        }:
            return "no_match"
        if error_kind == "multiple_matches_when_single_required":
            return "ambiguous_match"
        if error_kind == "replacement_count_mismatch":
            return "count_mismatch"
        return "mismatch"

    @final
    @staticmethod
    def _repo_file_key(file_path: Path) -> str:
        try:
            return file_path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            return file_path.as_posix()

    @final
    def build_receipt(self, result: SearchReplaceResult) -> SearchReplaceReceipt:
        """Build a content-light receipt from a search_replace result.

        The receipt contains no raw file content, old_text, new_text,
        diffs, or private paths — only metadata, block counts, hashes,
        byte counts, and structured error classification.

        ``refusal_reason`` is sanitized to strip file context lines
        (search text, context analysis, fuzzy match diffs) that are
        present in the user-facing result but must not enter receipts.
        """
        return SearchReplaceReceipt(
            file=result.file,
            status=result.status,
            blocks_applied=result.blocks_applied,
            lines_changed=result.lines_changed,
            replacements=result.replacements,
            warnings=result.warnings,
            before_file_sha256=result.before_file_sha256,
            after_file_sha256=result.after_file_sha256,
            changed_files=result.changed_files,
            failed_block_count=result.failed_block_count,
            total_block_count=result.total_block_count,
            before_bytes=result.before_bytes,
            after_bytes=result.after_bytes,
            error_kind=result.error_kind,
            refusal_reason=self._sanitize_refusal_for_receipt(result.refusal_reason),
            duration_ms=result.duration_ms,
        )

    @final
    @staticmethod
    def _sanitize_refusal_for_receipt(refusal_reason: str | None) -> str | None:
        """Strip file content context from a refusal reason string.

        Keeps only summary lines (``SEARCH/REPLACE block …``) and
        debugging tips. Strips search text, context analysis, fuzzy
        match diffs, and file content lines.
        """
        if not refusal_reason:
            return None
        lines = refusal_reason.split("\n")
        safe_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("SEARCH/REPLACE block", "Expected")):
                safe_lines.append(line.rstrip())
            elif stripped.startswith(("Debugging tips:", "1.", "2.", "3.", "4.")):
                safe_lines.append(line.rstrip())
        return "\n".join(safe_lines) if safe_lines else None

    def get_file_snapshot(self, args: SearchReplaceArgs) -> FileSnapshot | None:
        return self.get_file_snapshot_for_path(args.file_path)

    def resolve_permission(self, args: SearchReplaceArgs) -> PermissionContext | None:
        return resolve_file_tool_permission(
            args.file_path,
            tool_name=self.get_name(),
            allowlist=self.config.allowlist,
            denylist=self.config.denylist,
            config_permission=self.config.permission,
            sensitive_patterns=self.config.sensitive_patterns,
        )

    @final
    async def run(
        self, args: SearchReplaceArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | SearchReplaceResult, None]:
        start = time.perf_counter()
        validation = self._prepare_and_validate_args(args)
        if isinstance(validation, SearchReplaceResult):
            validation.duration_ms = (time.perf_counter() - start) * 1000
            yield validation
            return

        file_path, search_replace_blocks = validation
        total_block_count = len(search_replace_blocks)
        coordination_store, coordination = self._build_coordination_state(
            ctx, file_path
        )
        reservation_allowed = self._claim_coordination(coordination_store, coordination)
        if (
            not reservation_allowed
            and coordination_store is not None
            and coordination is not None
        ):
            yield SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                duration_ms=(time.perf_counter() - start) * 1000,
                warnings=[],
                before_file_sha256={},
                after_file_sha256={},
                changed_files=[],
                failed_block_count=0,
                total_block_count=total_block_count,
                status="blocked",
                error_kind="path_reserved",
                refusal_reason="Coordination reservation refused: another session has an active lease on this path",
            )
            return

        guard = get_guard()
        check = guard.check_search_replace(
            file_path, expected_before_sha256=args.expected_before_sha256
        )
        if not check.allowed:
            guard.record_refusal(file_path, check.reason)
            yield SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                duration_ms=(time.perf_counter() - start) * 1000,
                warnings=[],
                before_file_sha256={},
                after_file_sha256={},
                changed_files=[],
                failed_block_count=0,
                total_block_count=total_block_count,
                status="refused",
                error_kind=_classify_refusal(check),
                refusal_reason=check.detail,
            )
            return

        guard.mark_touched(file_path)

        try:
            result = await self._apply_search_replace(
                file_path=file_path,
                search_replace_blocks=search_replace_blocks,
                total_block_count=total_block_count,
                allow_multiple=args.allow_multiple,
                expected_replacements=args.expected_replacements,
            )
            result.duration_ms = (time.perf_counter() - start) * 1000
            self._publish_coordination_artifact(
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

    @final
    def _prepare_and_validate_args(  # noqa: PLR0911
        self, args: SearchReplaceArgs
    ) -> SearchReplaceResult | tuple[Path, list[SearchReplaceBlock]]:
        content = args.content.strip()

        if len(content) > self.config.max_content_size:
            return SearchReplaceResult(
                file="",
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=0,
                after_bytes=0,
                status="refused",
                error_kind="content_too_large",
                refusal_reason=(
                    f"Content size ({len(content)} bytes) exceeds max_content_size "
                    f"({self.config.max_content_size} bytes)"
                ),
            )

        if not content:
            return SearchReplaceResult(
                file="",
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=0,
                after_bytes=0,
                status="refused",
                error_kind="empty_content",
                refusal_reason="Empty content provided",
            )

        file_path = normalize_tool_path(args.file_path)

        try:
            require_path_within_workdir(file_path)
        except ToolError:
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=0,
                after_bytes=0,
                status="refused",
                error_kind="unsafe_path",
                refusal_reason=f"Path is outside the project directory: {file_path}",
            )

        if not file_path.exists():
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=0,
                after_bytes=0,
                status="refused",
                error_kind="file_not_found",
                refusal_reason=f"File does not exist: {file_path}",
            )

        if not file_path.is_file():
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=0,
                after_bytes=0,
                status="refused",
                error_kind="path_is_directory",
                refusal_reason=f"Path is not a file: {file_path}",
            )

        # Refuse binary files — search/replace on binary content is undefined
        raw_head = file_path.read_bytes()[:8192]
        if _is_binary_content(raw_head):
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=file_path.stat().st_size,
                after_bytes=0,
                status="refused",
                error_kind="binary_file",
                refusal_reason=(
                    f"Refusing to edit binary file: {file_path}. "
                    "search_replace operates on text files only."
                ),
            )

        search_replace_blocks = self._parse_search_replace_blocks(content)
        if not search_replace_blocks:
            return SearchReplaceResult(
                file=str(file_path),
                blocks_applied=0,
                lines_changed=0,
                content="",
                before_bytes=file_path.stat().st_size,
                after_bytes=0,
                status="refused",
                error_kind="parse_error",
                refusal_reason=(
                    "No valid SEARCH/REPLACE blocks found in content.\n"
                    "Expected format:\n"
                    "<<<<<<< SEARCH\n"
                    "[exact content to find]\n"
                    "=======\n"
                    "[new content to replace with]\n"
                    ">>>>>>> REPLACE"
                ),
            )

        return file_path, search_replace_blocks

    async def _read_file(self, file_path: Path) -> ReadSafeResult:
        try:
            return await read_safe_async(file_path, raise_on_error=True)
        except PermissionError:
            raise ToolError(f"Permission denied reading file: {file_path}")
        except OSError as e:
            raise ToolError(f"OS error reading {file_path}: {e}") from e
        except Exception as e:
            raise ToolError(f"Unexpected error reading {file_path}: {e}") from e

    async def _backup_file(self, file_path: Path) -> None:
        shutil.copy2(file_path, file_path.with_suffix(file_path.suffix + ".bak"))

    async def _write_file(self, file_path: Path, content: str, encoding: str) -> None:
        try:
            async with await anyio.Path(file_path).open(
                mode="w", encoding=encoding
            ) as f:
                await f.write(content)
        except UnicodeEncodeError as e:
            raise ToolError(
                f"Cannot encode patched content for {file_path} using {encoding!r}: {e}"
            ) from e
        except PermissionError:
            raise ToolError(f"Permission denied writing to file: {file_path}")
        except OSError as e:
            raise ToolError(f"OS error writing to {file_path}: {e}") from e
        except Exception as e:
            raise ToolError(f"Unexpected error writing to {file_path}: {e}") from e

    @final
    @staticmethod
    def _apply_blocks(
        content: str,
        blocks: list[SearchReplaceBlock],
        filepath: Path,
        fuzzy_threshold: float = 0.9,
        allow_multiple: bool = True,
        expected_replacements: int | None = None,
    ) -> BlockApplyResult:
        applied = 0
        errors: list[str] = []
        warnings: list[str] = []
        current_content = content
        total_replacements = 0

        for i, (search, replace) in enumerate(blocks, 1):
            if search not in current_content:
                context = SearchReplace._find_search_context(current_content, search)
                fuzzy_context = SearchReplace._find_fuzzy_match_context(
                    current_content, search, fuzzy_threshold
                )

                error_msg = (
                    f"SEARCH/REPLACE block {i} failed: Search text not found in {filepath}\n"
                    f"Search text was:\n{search!r}\n"
                    f"Context analysis:\n{context}"
                )

                if fuzzy_context:
                    error_msg += f"\n{fuzzy_context}"

                error_msg += (
                    "\nDebugging tips:\n"
                    "1. Check for exact whitespace/indentation match\n"
                    "2. Verify line endings match the file exactly (\\r\\n vs \\n)\n"
                    "3. Ensure the search text hasn't been modified by previous blocks or user edits\n"
                    "4. Check for typos or case sensitivity issues"
                )

                errors.append(error_msg)
                continue

            occurrences = current_content.count(search)
            if not allow_multiple and occurrences > 1:
                error_msg = (
                    f"SEARCH/REPLACE block {i} failed: Search text found {occurrences} times "
                    f"in {filepath} but allow_multiple=False. "
                    f"Make the search pattern more specific or allow multiple replacements."
                )
                errors.append(error_msg)
                continue

            if occurrences > 1:
                warning_msg = (
                    f"Search text in block {i} appears {occurrences} times in the file. "
                    f"Only the first occurrence will be replaced. Consider making your "
                    f"search pattern more specific to avoid unintended changes."
                )
                warnings.append(warning_msg)

            current_content = current_content.replace(search, replace, 1)
            applied += 1
            total_replacements += 1

        # Check expected replacement count after all blocks processed
        if (
            expected_replacements is not None
            and total_replacements != expected_replacements
        ):
            count_error = (
                f"Expected {expected_replacements} replacements but got {total_replacements}. "
                f"File was not mutated — check search text and retry with corrected expectation."
            )
            # Prepend so it's the primary error
            errors.insert(0, count_error)

        return BlockApplyResult(
            content=current_content, applied=applied, errors=errors, warnings=warnings
        )

    @final
    @staticmethod
    def _find_fuzzy_match_context(
        content: str, search_text: str, threshold: float = 0.9
    ) -> str | None:
        best_match = SearchReplace._find_best_fuzzy_match(
            content, search_text, threshold
        )

        if not best_match:
            return None

        diff = SearchReplace._create_unified_diff(
            search_text, best_match.text, "SEARCH", "CLOSEST MATCH"
        )

        similarity_pct = best_match.similarity * 100

        return (
            f"Closest fuzzy match (similarity {similarity_pct:.1f}%) "
            f"at lines {best_match.start_line}–{best_match.end_line}:\n"
            f"```diff\n{diff}\n```"
        )

    @final
    @staticmethod
    def _find_best_fuzzy_match(  # noqa: PLR0914
        content: str, search_text: str, threshold: float = 0.9
    ) -> FuzzyMatch | None:
        content_lines = content.split("\n")
        search_lines = search_text.split("\n")
        window_size = len(search_lines)

        if window_size == 0:
            return None

        non_empty_search = [line for line in search_lines if line.strip()]
        if not non_empty_search:
            return None

        first_anchor = non_empty_search[0]
        last_anchor = (
            non_empty_search[-1] if len(non_empty_search) > 1 else first_anchor
        )

        candidate_starts = set()
        spread = 5

        for i, line in enumerate(content_lines):
            if first_anchor in line or last_anchor in line:
                start_min = max(0, i - spread)
                start_max = min(len(content_lines) - window_size + 1, i + spread + 1)
                for s in range(start_min, start_max):
                    candidate_starts.add(s)

        if not candidate_starts:
            max_positions = min(len(content_lines) - window_size + 1, 100)
            candidate_starts = set(range(0, max_positions))

        best_match = None
        best_similarity = 0.0

        for start in candidate_starts:
            end = start + window_size
            window_text = "\n".join(content_lines[start:end])

            matcher = difflib.SequenceMatcher(None, search_text, window_text)
            similarity = matcher.ratio()

            if similarity >= threshold and similarity > best_similarity:
                best_similarity = similarity
                best_match = FuzzyMatch(
                    similarity=similarity,
                    start_line=start + 1,  # 1-based line numbers
                    end_line=end,
                    text=window_text,
                )

        return best_match

    @final
    @staticmethod
    def _create_unified_diff(
        text1: str, text2: str, label1: str = "SEARCH", label2: str = "CLOSEST MATCH"
    ) -> str:
        lines1 = text1.splitlines(keepends=True)
        lines2 = text2.splitlines(keepends=True)

        lines1 = [line if line.endswith("\n") else line + "\n" for line in lines1]
        lines2 = [line if line.endswith("\n") else line + "\n" for line in lines2]

        diff = difflib.unified_diff(
            lines1, lines2, fromfile=label1, tofile=label2, lineterm="", n=3
        )

        diff_lines = list(diff)

        if diff_lines and not diff_lines[0].startswith("==="):
            diff_lines.insert(2, "=" * 67 + "\n")

        result = "".join(diff_lines)

        max_chars = 2000
        if len(result) > max_chars:
            result = result[:max_chars] + "\n...(diff truncated)"

        return result.rstrip()

    @final
    @staticmethod
    def _parse_search_replace_blocks(content: str) -> list[SearchReplaceBlock]:
        """Parse SEARCH/REPLACE blocks from content.

        Supports two formats:
        1. With code block fences (```...```)
        2. Without code block fences
        """
        matches = SEARCH_REPLACE_BLOCK_WITH_FENCE_RE.findall(content)

        if not matches:
            matches = SEARCH_REPLACE_BLOCK_RE.findall(content)

        return [
            SearchReplaceBlock(
                search=search.rstrip("\r\n"), replace=replace.rstrip("\r\n")
            )
            for search, replace in matches
        ]

    @final
    @staticmethod
    def _find_search_context(
        content: str, search_text: str, max_context: int = 5
    ) -> str:
        lines = content.split("\n")
        search_lines = search_text.split("\n")

        if not search_lines:
            return "Search text is empty"

        first_search_line = search_lines[0].strip()
        if not first_search_line:
            return "First line of search text is empty or whitespace only"

        matches = []
        for i, line in enumerate(lines):
            if first_search_line in line:
                matches.append(i)

        if not matches:
            return f"First search line '{first_search_line}' not found anywhere in file"

        context_lines = []
        for match_idx in matches[:3]:
            start = max(0, match_idx - max_context)
            end = min(len(lines), match_idx + max_context + 1)

            context_lines.append(f"\nPotential match area around line {match_idx + 1}:")
            for i in range(start, end):
                marker = ">>>" if i == match_idx else "   "
                context_lines.append(f"{marker} {i + 1:3d}: {lines[i]}")

        return "\n".join(context_lines)
