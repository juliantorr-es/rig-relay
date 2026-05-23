from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rig_relay import RIG_ROOT

CONFIDENTIAL_ARTIFACT_ROOT = Path(".build") / "rig-relay" / "confidential"
_REPO_ROOT = RIG_ROOT.parent


def _resolve_repo_root(repo_root: Path | None = None) -> Path:
    root = repo_root or _REPO_ROOT
    try:
        return root.resolve(strict=False)
    except OSError:
        return root.absolute()


def resolve_confidential_artifact_root(repo_root: Path | None = None) -> Path:
    return _resolve_repo_root(repo_root) / CONFIDENTIAL_ARTIFACT_ROOT


def _resolve_candidate_path(path: Path | str, repo_root: Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = _resolve_repo_root(repo_root) / candidate
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate.absolute()


def _casefold_parts(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _contains_parts(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if len(needle) > len(haystack):
        return False
    limit = len(haystack) - len(needle) + 1
    for start in range(limit):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def is_confidential_artifact_path(
    path: Path | str, repo_root: Path | None = None
) -> bool:
    resolved = _resolve_candidate_path(path, repo_root)
    root = resolve_confidential_artifact_root(repo_root)
    resolved_parts = _casefold_parts(resolved)
    root_parts = _casefold_parts(root)
    artifact_parts = _casefold_parts(CONFIDENTIAL_ARTIFACT_ROOT)
    if _contains_parts(resolved_parts, artifact_parts):
        return True
    if len(resolved_parts) < len(root_parts):
        return False
    if resolved_parts[: len(root_parts)] == root_parts:
        return True
    return _contains_parts(resolved_parts, root_parts)


def refuse_confidential_input(
    path: Path | str, operation_kind: str, repo_root: Path | None = None
) -> tuple[bool, str]:
    if is_confidential_artifact_path(path, repo_root):
        return False, f"confidential_artifact_refused:{operation_kind}"
    return True, ""


def filter_exportable_artifact_paths(
    paths: Iterable[Path | str], repo_root: Path | None = None
) -> list[Path]:
    filtered: list[Path] = []
    for path in paths:
        candidate = Path(path)
        if not is_confidential_artifact_path(candidate, repo_root):
            filtered.append(candidate)
    return filtered


__all__ = [
    "CONFIDENTIAL_ARTIFACT_ROOT",
    "filter_exportable_artifact_paths",
    "is_confidential_artifact_path",
    "refuse_confidential_input",
    "resolve_confidential_artifact_root",
]
