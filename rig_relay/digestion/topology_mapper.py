"""Repository topology mapping — language-aware subsystem classification.

Slice 1A: Desktop Repository Preview Intake v1.
Wraps repo_map.build_subsystem_map with ecosystem-aware classification.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import TopologyEntry


def map_topology(repo_root: Path, detected_languages: list[str]) -> list[TopologyEntry]:
    """Build a classified subsystem topology map from the repository layout.

    Reuses the generic repo_map.subsystem infrastructure, then applies
    language-aware classification from ecosystem detection results.

    Args:
        repo_root: The repository root path.
        detected_languages: List of language strings from ecosystem detection
            (e.g., ["python", "typescript"]).

    Returns:
        Classified topology entries sorted alphabetically by name.
    """
    from rig_relay.context.repo_map import build_subsystem_map
    from rig_relay.digestion.models import ProvenanceClass, TopologyEntry

    subsystems = build_subsystem_map(repo_root)
    entries: list[TopologyEntry] = []

    for sub in subsystems:
        kind = _classify_kind(
            sub.name,
            sub.tests,
            sub.docs,
            sub.schemas,
            sub.config_files,
            detected_languages,
        )
        dominant_lang = _dominant_language(sub.name, sub.paths, detected_languages)
        contains_ep = len(sub.entry_points) > 0

        entries.append(
            TopologyEntry(
                name=sub.name,
                kind=kind,
                file_count=len(sub.paths),
                dominant_language=dominant_lang,
                contains_entry_points=contains_ep,
                provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            )
        )

    return sorted(entries, key=lambda e: (_kind_sort_order(e.kind), e.name))


def _classify_kind(
    dir_name: str,
    tests: list[str],
    docs: list[str],
    schemas: list[str],
    config_files: list[str],
    detected_languages: list[str],
) -> str:
    """Classify a subsystem directory by its contents."""
    from rig_relay.digestion.models import TopologyKind

    name_lower = dir_name.lower()

    # Generated/build output
    if name_lower in {
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        "target",
        "dist",
        "build",
        "out",
        ".next",
        "generated",
        ".git",
    }:
        return TopologyKind.GENERATED

    # Test directories
    if name_lower in {"tests", "test", "spec", "__tests__"}:
        return TopologyKind.TEST
    if len(tests) > 0 and len(tests) >= len([p for p in tests if not p]):
        file_count = sum(1 for p in _flatten_paths(dir_name) if p)
        if file_count > 0:
            return TopologyKind.TEST

    # Documentation
    if name_lower in {"docs", "documentation", "doc"}:
        return TopologyKind.DOCS
    if len(docs) > len(tests) and len(docs) > len(schemas):
        return TopologyKind.DOCS

    # Schemas
    if name_lower in {"schemas", "schema"}:
        return TopologyKind.SCHEMAS
    if len(schemas) > 0:
        return TopologyKind.SCHEMAS

    # Scripts
    if name_lower in {"scripts", "tools", "bin"}:
        return TopologyKind.SCRIPTS

    # Config
    if name_lower in {"config", "configuration", ".github"}:
        return TopologyKind.CONFIG
    if len(config_files) > 5:
        return TopologyKind.CONFIG

    # Source — any directory that looks like it contains source files
    if _looks_like_source(dir_name, detected_languages):
        return TopologyKind.SOURCE

    return TopologyKind.UNKNOWN


def _looks_like_source(dir_name: str, detected_languages: list[str]) -> bool:
    """Heuristic: does this directory name suggest source code?"""
    name_lower = dir_name.lower()
    # Common source directory names
    if name_lower in {"src", "source", "lib", "pkg", "app", "core", "main"}:
        return True
    # Language-specific conventions
    if "python" in detected_languages and name_lower == name_lower:
        return True  # Most non-standard names are source in Python repos
    # Directories named after the project
    return not name_lower.startswith(".") and name_lower not in {
        "docs",
        "tests",
        "test",
        "schemas",
        "scripts",
        "tools",
        "config",
    }


def _dominant_language(
    _dir_name: str, paths: list[str], detected_languages: list[str]
) -> str | None:
    """Determine the dominant programming language from file extensions."""
    if not paths:
        return None

    ext_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
    }

    counts: dict[str, int] = {}
    for p in paths:
        for ext, lang in ext_map.items():
            if p.endswith(ext):
                counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return detected_languages[0] if detected_languages else None

    return max(counts, key=lambda k: counts[k])


def _kind_sort_order(kind: str) -> int:
    """Sort order for topology kinds."""
    order = {
        "source": 0,
        "test": 1,
        "docs": 2,
        "schemas": 3,
        "scripts": 4,
        "config": 5,
        "generated": 6,
        "unknown": 7,
    }
    return order.get(kind, 99)


def _flatten_paths(_dir_name: str) -> list[str]:
    """Dummy — returns empty list. Only used for size heuristic."""
    return []
