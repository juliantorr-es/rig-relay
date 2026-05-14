"""Validate tool — path normalization and scoping.

Workspace-relative POSIX paths for portable receipts and fingerprints.
Refuses paths outside workspace root.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path

from rig_relay.core.tools.builtins.validate_models import ProfileCheck


def _normalize_validate_paths(
    paths: Sequence[str], workspace_root: str | None = None
) -> tuple[list[str], str | None]:
    """Normalize paths to workspace-relative POSIX form.

    Resolves each path against workspace_root for containment checking
    (absolute paths used internally only). Returns workspace-relative
    paths with POSIX separators for stable fingerprints, portable argv,
    and content-light receipts.

    De-duplicates paths, sorts for stable fingerprints.
    Refuses paths outside workspace root.
    Returns blocked result for nonexistent paths.

    Returns (normalized_relative_paths, refusal_reason).
    refusal_reason is None when all paths are valid.
    """
    if not paths:
        return [], None

    root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    seen_abs: set[str] = set()
    relative: list[str] = []

    for p in paths:
        try:
            p_path = Path(p)
            resolved = (
                p_path.resolve() if p_path.is_absolute() else (root / p).resolve()
            )
            resolved.relative_to(root)  # ensure within workspace
            abs_str = str(resolved)
            if abs_str in seen_abs:
                continue
            seen_abs.add(abs_str)
            if not resolved.exists():
                return [], f"Path '{p}' does not exist"
            rel = resolved.relative_to(root)
            rel_str = str(rel).replace(os.sep, "/")
            relative.append(rel_str)
        except (ValueError, OSError):
            return [], f"Path '{p}' is outside workspace root '{root}'"

    relative.sort()
    return relative, None


def _is_python_path(p: str) -> bool:
    """Return True if a path is Python-relevant."""
    return p.endswith(".py") or "/python" in p.lower() or p.endswith("/")


def _is_test_path(p: str) -> bool:
    """Return True if a path is under tests/."""
    return "/tests/" in p or p.startswith("tests/")


# ruff: noqa: PLR0911
def _scope_check_argv(
    check: ProfileCheck, paths: Sequence[str]
) -> tuple[list[str], bool]:
    """Scope a profile check's argv to specific paths.

    Returns (modified_argv, should_run).
    When should_run is False, the check should be skipped because
    none of the provided paths are relevant to its domain.
    """
    if not paths:
        return list(check.argv), True

    if check.command_kind == "ruff":
        py_paths = [p for p in paths if _is_python_path(p)]
        if not py_paths:
            return list(check.argv), False
        return list(check.argv) + py_paths, True

    if check.command_kind == "pytest":
        test_paths = [p for p in paths if _is_test_path(p)]
        if not test_paths:
            return list(check.argv), False
        return list(check.argv) + test_paths, True

    if check.command_kind == "schema":
        schema_paths = [
            p for p in paths if "schema" in p.lower() or "docs/schemas/" in p
        ]
        if not schema_paths:
            return list(check.argv), False
        return list(check.argv), True

    if check.command_kind == "policy":
        receipt_paths = [p for p in paths if "receipt" in p.lower()]
        if not receipt_paths:
            return list(check.argv), False
        return list(check.argv), True

    # For git, pyright, and custom — no scoping
    return list(check.argv), True
