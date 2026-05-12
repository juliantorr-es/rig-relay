from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tree_sitter import Language, Node, Parser
import tree_sitter_bash as tsbash

from vibe.core.scratchpad import is_scratchpad_path
from vibe.core.tools.base import ToolError


@lru_cache(maxsize=1)
def _get_bash_parser() -> Parser:
    return Parser(Language(tsbash.language()))


def normalize_tool_path(path_str: str, *, cwd: Path | None = None) -> Path:
    """Normalize a tool-provided path string.

    Rejects empty paths, expands ~, resolves relative against cwd.
    """
    if not path_str.strip():
        raise ToolError("Path cannot be empty")

    path = Path(path_str).expanduser()
    if not path.is_absolute():
        effective_cwd = (cwd or Path.cwd()).resolve()
        path = effective_cwd / path

    return path.resolve()


def require_path_within_workdir(path: Path, *, workdir: Path | None = None) -> Path:
    """Ensure the path is within the workdir (or scratchpad).

    Raises ToolError if outside.
    """
    if is_scratchpad_path(str(path)):
        return path

    effective_workdir = (workdir or Path.cwd()).resolve()
    try:
        # Resolve path to handle .. and symlinks
        resolved_path = path.resolve()
        resolved_path.relative_to(effective_workdir)
        return path
    except ValueError:
        raise ToolError(
            f"Security error: Path '{path}' is outside the project directory '{effective_workdir}'."
        )


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    """Truncate text to max_bytes safely at UTF-8 boundaries."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False

    # Truncate and then decode with ignore to avoid partial chars at the end
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated, True


def parse_shell_commands(command: str) -> list[str]:
    """Extract individual commands from a shell string using tree-sitter-bash."""
    try:
        parser = _get_bash_parser()
        tree = parser.parse(command.encode("utf-8"))

        commands: list[str] = []

        def find_commands(node: Node) -> None:
            if node.type == "command":
                parts = []
                for child in node.children:
                    if (
                        child.type
                        in {
                            "command_name",
                            "word",
                            "string",
                            "raw_string",
                            "concatenation",
                        }
                        and child.text is not None
                    ):
                        parts.append(child.text.decode("utf-8"))
                if parts:
                    commands.append(" ".join(parts))

            for child in node.children:
                find_commands(child)

        find_commands(tree.root_node)
        return commands
    except Exception:
        # Fall back to an empty list on any parsing or runtime failure
        # to ensure downstream permission logic remains conservative.
        return []
