"""Validate tool — check execution and classification.

Subprocess execution with output caps, timeout, dependency checking,
failure classification, and command fingerprinting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
import os
import shutil
import time

from vibe.core.tools.builtins.validate_models import (
    RECEIPT_SCRIPT,
    SCHEMA_SCRIPT,
    ValidateCheckResult,
)
from vibe.core.tools.builtins.validate_summaries import _parse_check_summary

# ruff: noqa: PLR0911 — classify_failure has one return per supported command kind


def classify_failure(command_kind: str, exit_code: int, stderr: str) -> str:
    """Map a command result to a blocker kind.

    Args:
        command_kind: The kind of check (pytest, ruff, pyright, etc.).
        exit_code: Process exit code (0 = success).
        stderr: Stderr text for heuristic matching.
    """
    if exit_code == 0:
        return ""

    if exit_code < 0:
        return "timeout"

    lower = stderr.lower()

    if command_kind == "pytest":
        if "failed" in lower or "failure" in lower:
            return "test_failure"
        return "test_failure"

    if command_kind == "ruff":
        return "lint_failure"

    if command_kind == "pyright":
        if "error" in lower or "cannot find" in lower or "import" in lower:
            return "typecheck_failure"
        return "typecheck_failure"

    if command_kind == "schema":
        return "schema_failure"

    if command_kind == "policy":
        return "governance_failure"

    if command_kind == "git":
        return "dirty_workspace"

    return "unknown_failure"


def check_missing_dependency(argv: Sequence[str]) -> str | None:
    """Check if the primary executable exists.

    Only checks the first token of argv. This avoids misclassifying
    subcommands or arguments as missing dependencies (e.g., in
    'git status' or 'uv run pytest', only 'git' or 'uv' are checked).
    """
    if not argv:
        return None

    main_bin = argv[0]
    if not shutil.which(main_bin):
        return main_bin
    return None


def _infer_kind_from_argv(argv: Sequence[str]) -> str:
    """Infer command_kind from argv."""
    cmd_str = " ".join(argv)
    if "pytest" in cmd_str:
        return "pytest"
    if "ruff" in cmd_str:
        return "ruff"
    if "pyright" in cmd_str:
        return "pyright"
    if "validate_schemas" in cmd_str or SCHEMA_SCRIPT in cmd_str:
        return "schema"
    if "validate_tool_receipts" in cmd_str or RECEIPT_SCRIPT in cmd_str:
        return "policy"
    if "git" in cmd_str:
        return "git"
    return "custom"


def _compute_fingerprint(argv: Sequence[str]) -> str:
    """Stable fingerprint for a normalized command."""
    normalized = [os.path.normpath(a) for a in argv]
    raw = "|".join(normalized).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# ruff: noqa: PLR0914  -- _run_check needs many local vars
async def _run_check(
    argv: list[str], *, output_cap: int, timeout: int, cwd: str | None
) -> ValidateCheckResult:
    """Run a single check as a subprocess and return a structured result.

    Uses argv-based execution (no shell). Captures stdout/stderr with
    byte caps, computes hashes, measures duration, and classifies failures.
    """
    start = time.perf_counter()
    check_id = _compute_fingerprint(argv)

    missing = check_missing_dependency(argv)
    if missing:
        elapsed = (time.perf_counter() - start) * 1000
        return ValidateCheckResult(
            check_id=check_id,
            command_kind=_infer_kind_from_argv(argv),
            command_display=" ".join(argv),
            command_fingerprint=check_id,
            status="blocked",
            duration_ms=elapsed,
            failure_kind="missing_dependency",
            stdout_bytes=0,
            stderr_bytes=0,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
    except FileNotFoundError:
        elapsed = (time.perf_counter() - start) * 1000
        return ValidateCheckResult(
            check_id=check_id,
            command_kind=_infer_kind_from_argv(argv),
            command_display=" ".join(argv),
            command_fingerprint=check_id,
            status="blocked",
            duration_ms=elapsed,
            failure_kind="missing_dependency",
            stdout_bytes=0,
            stderr_bytes=0,
        )

    try:
        raw_stdout, raw_stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        elapsed = (time.perf_counter() - start) * 1000
        return ValidateCheckResult(
            check_id=check_id,
            command_kind=_infer_kind_from_argv(argv),
            command_display=" ".join(argv),
            command_fingerprint=check_id,
            status="timed_out",
            duration_ms=elapsed,
            failure_kind="timeout",
            stdout_bytes=0,
            stderr_bytes=0,
        )

    elapsed = (time.perf_counter() - start) * 1000
    total_stdout_bytes = len(raw_stdout) if raw_stdout else 0
    total_stderr_bytes = len(raw_stderr) if raw_stderr else 0

    stdout_str = (
        raw_stdout.decode("utf-8", errors="replace")[:output_cap] if raw_stdout else ""
    )
    stderr_str = (
        raw_stderr.decode("utf-8", errors="replace")[:output_cap] if raw_stderr else ""
    )

    stdout_truncated = total_stdout_bytes > output_cap
    stderr_truncated = total_stderr_bytes > output_cap
    returncode = proc.returncode or 0

    stdout_sha256 = hashlib.sha256(raw_stdout or b"").hexdigest()
    stderr_sha256 = hashlib.sha256(raw_stderr or b"").hexdigest()

    command_kind = _infer_kind_from_argv(argv)

    if returncode == 0:
        status = "passed"
        failure_kind = None
    else:
        status = "failed"
        failure_kind = classify_failure(command_kind, returncode, stderr_str)

    parsed_summary = _parse_check_summary(
        command_kind, stdout_str, stderr_str, returncode
    )

    return ValidateCheckResult(
        check_id=check_id,
        command_kind=command_kind,
        command_display=" ".join(argv),
        command_fingerprint=check_id,
        status=status,
        exit_code=returncode,
        duration_ms=elapsed,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        stdout_bytes=total_stdout_bytes,
        stderr_bytes=total_stderr_bytes,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        failure_kind=failure_kind,
        parsed_summary=parsed_summary,
    )
