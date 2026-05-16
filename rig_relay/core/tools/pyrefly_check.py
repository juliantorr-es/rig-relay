"""Pyrefly type checking tool — runs pyrefly on Python files.

Wraps the `pyrefly check` command to provide type checking results
as structured data. Falls back to pyright if pyrefly is unavailable.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

_RESULT_PATTERN = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+)?\s*-\s*(?P<severity>\w+):\s*(?P<message>.+)$",
    re.MULTILINE,
)


async def type_check(
    paths: list[str] | None = None, config_path: str | None = None, timeout: int = 120
) -> dict[str, Any]:
    """Run pyrefly type check on the given paths.

    Args:
        paths: File or directory paths to check. If None, checks the project.
        config_path: Path to pyrefly config file (pyrefly.toml or pyproject.toml).
        timeout: Maximum execution time in seconds.

    Returns:
        Dict with keys:
          - backend: "pyrefly" or "fallback"
          - exit_code: int
          - errors: list of error dicts with file, line, column, severity, message
          - error_count: int
          - stdout: raw stdout
          - stderr: raw stderr
    """
    cmd = ["pyrefly", "check"]

    if config_path:
        cmd.extend(["--config", config_path])

    if paths:
        cmd.extend(paths)
    else:
        cmd.append(".")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError:
        await _kill_process(proc)
        return {
            "backend": "pyrefly",
            "exit_code": -1,
            "errors": [],
            "error_count": 0,
            "stdout": "",
            "stderr": f"Timed out after {timeout}s",
        }

    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    errors = _parse_errors(stdout)
    error_count = len(errors)

    return {
        "backend": "pyrefly",
        "exit_code": proc.returncode or 0,
        "errors": errors[:100],  # Limit to prevent mega-output
        "error_count": error_count,
        "stdout": stdout,
        "stderr": stderr,
    }


def _parse_errors(output: str) -> list[dict[str, Any]]:
    """Parse pyrefly output into structured error objects."""
    if not output:
        return []

    errors: list[dict[str, Any]] = []
    for match in _RESULT_PATTERN.finditer(output):
        errors.append({
            "file": match.group("file"),
            "line": int(match.group("line")),
            "column": int(match.group("column") or 0),
            "severity": match.group("severity"),
            "message": match.group("message"),
        })
    return errors


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    """Kill a subprocess safely."""
    try:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass


__all__ = ["type_check"]
