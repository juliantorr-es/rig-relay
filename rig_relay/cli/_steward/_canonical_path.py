"""Canonical path identity helper for proposal admission.

Separates operational absolute filesystem paths from canonical
authority-relative identities used for registry lookup, mission
scope checks, and content-light evidence.
"""

from __future__ import annotations

from pathlib import Path


def resolve_canonical_identity(operational_path: str | Path, repo_root: Path) -> str:
    """Convert an operational path to a canonical root-relative identity.

    Resolves symlinks and .., validates containment, and returns
    a POSIX-relative identity suitable for registry lookup,
    mission scope comparison, and content-light evidence.

    Raises ValueError if the path is outside the repository root.
    """
    root = repo_root.resolve()
    op = Path(operational_path).resolve()

    try:
        rel = op.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"operational path '{operational_path}' is outside repository root '{root}'"
        ) from e

    return rel.as_posix()


def validate_operational_containment(
    operational_path: str | Path, repo_root: Path
) -> Path:
    """Validate operational path is within repo root. Returns resolved Path."""
    root = repo_root.resolve()
    op = Path(operational_path).resolve()

    try:
        op.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"operational path '{operational_path}' is outside repository root '{root}'"
        ) from e

    return op
