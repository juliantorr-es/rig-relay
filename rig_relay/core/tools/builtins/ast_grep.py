from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolPermission,
)
from rig_relay.core.types import ToolStreamEvent

if TYPE_CHECKING:
    from rig_relay.core.tools.base import InvokeContext


_LANG_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".swift": "swift",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".js": "javascript",
    ".json": "json",
    ".yml": "yml",
    ".yaml": "yml",
}

_SUPPORTED_LANGUAGES: frozenset[str] = frozenset(_LANG_EXT_MAP.values())

_MAX_SNIPPET_BYTES = 2048
_MAX_TOTAL_OUTPUT_BYTES = 64000
_SAFE_MAX_MATCHES = 200
_SAFE_MAX_FILES = 500

_PROBE_SOURCE: dict[str, str] = {
    "python": "x = 1",
    "typescript": "const x = 1;",
    "tsx": "const x = 1;",
    "rust": "let x = 1;",
    "swift": "let x = 1",
    "java": "class X { int x = 1; }",
    "cpp": "int x = 1;",
    "go": "var x = 1",
    "javascript": "const x = 1;",
    "json": '{"x": 1}',
    "yml": "x: 1",
}


class AstGrepConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class AstGrepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(
        description=(
            "Structural pattern. $A matches one AST node, $$$ARGS matches "
            "a sequence of nodes. Pattern must be valid parseable code in "
            "the target language. Example: 'except $E: pass' finds swallowed "
            "typed exceptions. 'ToolRuntimeRequest($$$ARGS)' finds all "
            "ToolRuntimeRequest constructions."
        )
    )
    language: str | None = Field(
        default=None,
        description=(
            "Language identifier. Required for repository-wide or mixed-language "
            "scans. Narrowly inferred for single-file or single-language explicit "
            "path sets. Values: python, typescript, tsx, rust, swift, java, "
            "cpp, go, javascript, json, yml."
        ),
    )
    paths: list[str] = Field(
        default_factory=list,
        description=(
            "Repository-relative files or directories to search. "
            "Empty = repository-wide only when language is supplied."
        ),
    )
    max_matches: int = Field(
        default=200,
        description="Maximum structural matches across all files. Capped at 200.",
    )
    max_files: int = Field(
        default=500, description="Maximum files to scan. Capped at 500."
    )
    context_lines: int = Field(
        default=1,
        description="Lines of source context around each match. Capped at 1 per side.",
    )


class AstGrepMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    snippet: str
    snippet_truncated: bool = False


class AstGrepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_outcome: str
    matches: list[AstGrepMatch] = Field(default_factory=list)
    matches_returned: int = 0
    matched_files: int = 0
    scanned_files: int = 0
    failed_files: int = 0
    was_truncated: bool = False
    truncation_reason: str | None = None
    language: str = ""
    error_kind: str | None = None
    suggested_next_action: str | None = None


def _infer_language(path_list: list[Path], raw_paths: list[str]) -> str | None:
    langs: set[str] = set()
    for p in path_list:
        if p.is_file():
            ext = p.suffix.lower()
            lang = _LANG_EXT_MAP.get(ext)
            if lang:
                langs.add(lang)
        elif p.is_dir() and raw_paths:
            return None
    if len(langs) == 1:
        return next(iter(langs))
    return None


def _resolve_files(
    paths: list[str], language: str | None, max_files: int
) -> list[str] | None:
    result: list[str] = []
    exts = {ext for ext, lang in _LANG_EXT_MAP.items()}
    if language:
        exts = {ext for ext, lang in _LANG_EXT_MAP.items() if lang == language}

    if not paths:
        if not language:
            return None
        for ext in sorted(exts):
            for p in sorted(Path(".").rglob(f"*{ext}")):
                if len(result) >= max_files:
                    break
                if ".git/" in str(p) or "__pycache__" in str(p) or ".venv/" in str(p):
                    continue
                result.append(str(p))
            if len(result) >= max_files:
                break
        return result[:max_files]

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        if p.is_file():
            ext = p.suffix.lower()
            if ext in exts:
                result.append(str(p))
        elif p.is_dir():
            for ext in sorted(exts):
                for py_file in sorted(p.rglob(f"*{ext}")):
                    if len(result) >= max_files:
                        break
                    if (
                        ".git/" in str(py_file)
                        or "__pycache__" in str(py_file)
                        or ".venv/" in str(py_file)
                    ):
                        continue
                    result.append(str(py_file))
                if len(result) >= max_files:
                    break

    return result[:max_files]


def _check_paths_in_workspace(files: list[str], ctx: InvokeContext | None) -> list[str]:
    refused: list[str] = []
    for f in files:
        p = Path(f).resolve()
        workspace = Path.cwd().resolve()
        try:
            p.relative_to(workspace)
        except ValueError:
            refused.append(f)
    return refused


class AstGrep(BaseTool[AstGrepArgs, AstGrepResult, AstGrepConfig, BaseToolState]):
    description: ClassVar[str] = (
        "AST-aware structural search. Matches code SHAPES rather than text "
        "strings. Uses Tree-sitter-backed parsers. "
        "Metavariables: $A matches one AST node, $$$ARGS matches a sequence. "
        "Use ast_grep when the question is about code structure (function "
        "definitions, call patterns, class hierarchies, decorators, import "
        "shapes). Use grep when the question is about text, identifiers, "
        "comments, or strings. Use read_file when the target file is known."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    def _load_lib(self) -> type:
        import ast_grep_py

        return ast_grep_py

    async def run(
        self, args: AstGrepArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | AstGrepResult, None]:
        try:
            ast_grep_py = self._load_lib()
        except ImportError:
            yield AstGrepResult(
                query_outcome="unavailable",
                error_kind="tool_unavailable",
                suggested_next_action="Structural search unavailable. Use grep for text search.",
            )
            return

        max_matches = max(1, min(args.max_matches, _SAFE_MAX_MATCHES))
        max_files = max(1, min(args.max_files, _SAFE_MAX_FILES))

        language = args.language
        path_list = [Path(p) for p in args.paths if Path(p).exists()]

        if language is None:
            language = _infer_language(path_list, args.paths)
            if language is None:
                yield AstGrepResult(
                    query_outcome="language_required",
                    error_kind="language_required_for_multi_file_scan",
                    suggested_next_action="Specify 'language' for repository-wide structural search.",
                )
                return

        if language is not None and language not in _SUPPORTED_LANGUAGES:
            yield AstGrepResult(
                query_outcome="unsupported_language",
                error_kind="unsupported_language",
                suggested_next_action=(
                    f"Supported languages: {', '.join(sorted(_SUPPORTED_LANGUAGES))}. "
                    "Use grep for text search in unsupported languages."
                ),
            )
            return

        resolved_files = _resolve_files(args.paths, language, max_files)
        if resolved_files is None:
            yield AstGrepResult(
                query_outcome="language_required",
                error_kind="language_required_for_multi_file_scan",
                suggested_next_action="Specify 'language' for repository-wide structural search.",
            )
            return

        probe_lang = language
        if probe_lang is None:
            probe_lang = "python"
        try:
            probe = ast_grep_py.SgRoot(
                _PROBE_SOURCE.get(probe_lang, "x = 1"), probe_lang
            )
        except Exception:
            yield AstGrepResult(
                query_outcome="unsupported_language",
                error_kind="unsupported_language",
                suggested_next_action=f"Parser for '{probe_lang}' unavailable.",
            )
            return

        try:
            probe.root().find_all(pattern=args.pattern)
        except Exception:
            yield AstGrepResult(
                query_outcome="invalid_pattern",
                error_kind="invalid_structural_pattern",
                suggested_next_action=(
                    "Revise the structural pattern. Check metavariable syntax "
                    "($A for single node, $$$B for sequence) and language-appropriate "
                    "node names."
                ),
            )
            return

        refused_paths = _check_paths_in_workspace(resolved_files, ctx)
        if refused_paths:
            yield AstGrepResult(
                query_outcome="path_refused",
                error_kind="path_outside_verified_worktree",
                suggested_next_action="Search within repository-relative paths only.",
            )
            return

        all_matches: list[AstGrepMatch] = []
        matched_files_set: set[str] = set()
        scanned = 0
        failed = 0
        total_output_bytes = 0
        truncated = False
        truncation_reason = None

        for file_path in resolved_files:
            if scanned >= max_files:
                truncated = True
                truncation_reason = "max_files_reached"
                break

            try:
                src = Path(file_path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                failed += 1
                continue

            try:
                root = ast_grep_py.SgRoot(src, language)
            except Exception:
                failed += 1
                continue

            try:
                hits = root.root().find_all(pattern=args.pattern)
            except Exception:
                failed += 1
                continue

            scanned += 1

            for hit in hits:
                if len(all_matches) >= max_matches:
                    truncated = True
                    truncation_reason = "max_matches_reached"
                    break

                range_obj = hit.range()
                start_line = range_obj.start.line + 1
                start_col = range_obj.start.column
                end_line = range_obj.end.line + 1
                end_col = range_obj.end.column

                snippet = hit.text()
                snippet_truncated = False
                if len(snippet.encode("utf-8")) > _MAX_SNIPPET_BYTES:
                    snippet = (
                        snippet[: int(_MAX_SNIPPET_BYTES * 0.75)] + "\n# ... truncated"
                    )
                    snippet_truncated = True

                snippet_bytes = len(snippet.encode("utf-8"))
                if total_output_bytes + snippet_bytes > _MAX_TOTAL_OUTPUT_BYTES:
                    truncated = True
                    truncation_reason = truncation_reason or "max_output_bytes"
                    break
                total_output_bytes += snippet_bytes

                match_obj = AstGrepMatch(
                    file=str(file_path),
                    start_line=start_line,
                    start_column=start_col,
                    end_line=end_line,
                    end_column=end_col,
                    snippet=snippet,
                    snippet_truncated=snippet_truncated,
                )
                all_matches.append(match_obj)
                matched_files_set.add(str(file_path))

            if truncated:
                break

        if not all_matches:
            yield AstGrepResult(
                query_outcome="no_match",
                language=language or "",
                scanned_files=scanned,
                failed_files=failed,
                suggested_next_action="Verify the code shape exists in the searched paths, or broaden the query.",
            )
            return

        yield AstGrepResult(
            query_outcome="truncated" if truncated else "matches",
            matches=all_matches,
            matches_returned=len(all_matches),
            matched_files=len(matched_files_set),
            scanned_files=scanned,
            failed_files=failed,
            was_truncated=truncated,
            truncation_reason=truncation_reason,
            language=language or "",
            suggested_next_action=(
                "Narrow search scope with more specific pattern or paths."
                if truncated
                else None
            ),
        )


__all__ = ["AstGrep", "AstGrepArgs", "AstGrepMatch", "AstGrepResult"]
