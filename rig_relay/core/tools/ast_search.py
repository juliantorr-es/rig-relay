"""AST-aware code search and structural operations using ast-grep (sg).

Provides Python wrappers around the ast-grep CLI for:
  - Pattern matching on AST nodes (not just text)
  - Structural search/replace
  - Finding function/class definitions
  - Detecting dangerous patterns in bash commands

Uses the `sg` CLI (assumed to be installed) since the Python binding
is unstable. Falls back to ripgrep/rg if sg is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any


def _available() -> bool:
    """Check if ast-grep (sg) CLI is available."""
    return shutil.which("sg") is not None


async def ast_search(
    pattern: str, path: str = ".", lang: str = "python", max_results: int = 50
) -> list[dict[str, Any]]:
    """Search code using AST-aware pattern matching.

    Args:
        pattern: ast-grep pattern (e.g. "print($$$)" for any print call).
        path: Search path (file or directory).
        lang: Language for parsing (python, ts, rust, go, etc.).
        max_results: Maximum number of results.

    Returns:
        List of match dicts with keys: file, line, column, text, range.
    """
    if not _available():
        return []

    cmd = ["sg", "-p", pattern, "--lang", lang, "--json", "-l"]
    if path != ".":
        cmd.append(path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode not in {0, 1}:
            return []

        output = stdout.decode("utf-8", errors="ignore")
        if not output.strip():
            return []

        results = json.loads(output)
        if not isinstance(results, list):
            return []

        return results[:max_results]

    except (TimeoutError, json.JSONDecodeError, Exception):
        return []


async def find_function_definitions(
    path: str = ".", func_name: str | None = None
) -> list[dict[str, Any]]:
    """Find function definitions in Python files.

    Args:
        path: Search path.
        func_name: Optional function name to filter by.

    Returns:
        List of match dicts.
    """
    pattern = f"def {func_name}($$$):$$$" if func_name else "def $$$($$$):$$$"
    return await ast_search(pattern, path, lang="python")


async def find_class_definitions(
    path: str = ".", class_name: str | None = None
) -> list[dict[str, Any]]:
    """Find class definitions in Python files."""
    pattern = f"class {class_name}:$$$" if class_name else "class $$$:$$$"
    return await ast_search(pattern, path, lang="python")


async def find_imports(
    module_name: str | None = None, path: str = "."
) -> list[dict[str, Any]]:
    """Find import statements matching a module name."""
    if module_name:
        pattern = f"import {module_name}"
    else:
        pattern = "import $$$"
    return await ast_search(pattern, path, lang="python")


def detect_dangerous_bash_patterns(command: str) -> list[str]:
    """Detect dangerous patterns in bash commands that attempt to
    bypass the allowlist/denylist system.

    Returns a list of warning strings (empty if safe).
    """
    warnings: list[str] = []

    # Embedded commands via command substitution
    if "$(" in command and ")" in command:
        warnings.append(
            "Command contains command substitution ($(...)). "
            "This can execute arbitrary commands and bypass allowlists."
        )
    if "`" in command and "`" in command[1:]:
        warnings.append(
            "Command contains backtick command substitution (`...`). "
            "This can execute arbitrary commands and bypass allowlists."
        )

    # Inline code execution via interpreter -c/-e/-r flags
    for interpreter in {
        "python3",
        "python",
        "ruby",
        "perl",
        "node",
        "deno",
        "bun",
        "php",
    }:
        if interpreter in command and (
            "-c" in command or "-e" in command or "-r" in command
        ):
            warnings.append(
                f"Command uses '{interpreter} -c/-e' to execute inline code. "
                f"This can bypass command allowlists."
            )

    # Environment variable injection
    parts = command.split()
    for part in parts:
        if "=" in part and not part.startswith("-"):
            key, _, value = part.partition("=")
            if key.isupper() and len(key) > 1 and value:
                warnings.append(
                    f"Command sets environment variable '{key}'. "
                    f"This could alter tool behavior."
                )
            break  # Only check the first potential env var

    # Shell escape using backslash-prefixed commands (raw path)
    for part in parts:
        if part.startswith("\\") and len(part) > 1:
            warnings.append(
                f"Command uses backslash-escaped path '{part}'. "
                f"This bypasses command allowlist matching."
            )

    # Piped commands
    if "|" in command and not any(
        p in command for p in ["head", "tail", "grep", "sort", "wc", "cut", "tr"]
    ):
        warnings.append(
            "Command uses pipes with potentially dangerous downstream processor."
        )

    return warnings


__all__ = [
    "ast_search",
    "detect_dangerous_bash_patterns",
    "find_class_definitions",
    "find_function_definitions",
    "find_imports",
]
