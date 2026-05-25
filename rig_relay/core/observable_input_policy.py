from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Disposable directory names (path components, not string prefixes) ──
_DISPOSABLE_DIR_NAMES: frozenset[str] = frozenset({
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "build",
    "dist",
})

# ── Observable file extensions ──────────────────────────────────────
_OBSERVABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".env",
    ".cfg",
    ".ini",
    ".sql",
    ".sh",
    ".bash",
})

# ── Prefix-excluded disposable path starts (for repo-root dirs like build/ dist/) ──
_DISPOSABLE_PATH_PREFIXES: tuple[str, ...] = tuple(
    f"{d}/" for d in _DISPOSABLE_DIR_NAMES
)


@dataclass
class IgnoredInputAssessment:
    """Result of classifying ignored untracked paths.

    All counts and categories are content-light — no raw file paths.
    Agent-visible paths are stored separately in the local tool result.
    """

    disposable_categories: set[str] = field(default_factory=set)
    disposable_count: int = 0
    observable_count: int = 0
    unknown_count: int = 0
    observable_paths: list[str] = field(default_factory=list)
    unknown_paths: list[str] = field(default_factory=list)
    blocked: bool = False
    blocking_reason: str | None = None

    def to_receipt_fields(self) -> dict[str, Any]:
        """Content-light fields for the durable validation receipt."""
        return {
            "ignored_disposable_exclusion_categories": sorted(
                self.disposable_categories
            ),
            "ignored_observable_candidate_count": self.observable_count,
            "ignored_disposable_count": self.disposable_count,
            "unknown_ignored_count": self.unknown_count,
        }


def classify_ignored_observable_inputs(
    ignored_paths: list[str],
) -> IgnoredInputAssessment:
    """Classify ignored untracked paths into disposable, observable, or unknown.

    Disposable matching uses PATH COMPONENTS, not string prefixes.
    A file named 'build-output.py' at the repo root is NOT classified
    as disposable because it doesn't live inside a 'build/' directory.

    Args:
        ignored_paths: Repository-relative paths from git ls-files --others --ignored.

    Returns:
        IgnoredInputAssessment with classification and blocking status.
    """
    assessment = IgnoredInputAssessment()

    for raw_path in ignored_paths:
        path = Path(raw_path)

        # ── Disposable by directory ancestry ──────────────────────────
        is_disposable = False
        for parent in path.parents:
            if parent.name in _DISPOSABLE_DIR_NAMES:
                is_disposable = True
                assessment.disposable_categories.add(parent.name)
                break

        # Also check path prefix for top-level directories (build/file, dist/file)
        if not is_disposable:
            for prefix in _DISPOSABLE_PATH_PREFIXES:
                if raw_path.startswith(prefix):
                    dir_name = prefix.rstrip("/")
                    if dir_name in _DISPOSABLE_DIR_NAMES:
                        is_disposable = True
                        assessment.disposable_categories.add(dir_name)
                        break

        if is_disposable:
            assessment.disposable_count += 1
            continue

        # ── Observable by extension ───────────────────────────────────
        suffix = path.suffix.lower()
        if suffix in _OBSERVABLE_EXTENSIONS:
            assessment.observable_count += 1
            assessment.observable_paths.append(raw_path)
            continue

        # ── Unknown ───────────────────────────────────────────────────
        assessment.unknown_count += 1
        assessment.unknown_paths.append(raw_path)

    # ── Decide blocking ──────────────────────────────────────────────
    if assessment.observable_count > 0:
        assessment.blocked = True
        assessment.blocking_reason = (
            f"{assessment.observable_count} ignored observable input(s) exist"
        )
    elif assessment.unknown_count > 0:
        assessment.blocked = True
        assessment.blocking_reason = (
            f"{assessment.unknown_count} unknown ignored file(s) exist"
        )

    return assessment


__all__ = ["IgnoredInputAssessment", "classify_ignored_observable_inputs"]
