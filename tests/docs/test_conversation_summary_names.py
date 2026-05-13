"""Test conversation summary filename convention."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

CONVERSATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "conversations"
)
README = CONVERSATIONS_DIR / "README.md"

CANONICAL_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}--[a-z][a-z0-9-]*--[a-z][a-z0-9-]*--"
    r"[a-z][a-z0-9-]*(-[a-z][a-z0-9-]*){2,7}--"
    r"(summary|handoff|decision-log|incident|research|prompt-pack)\.md$"
)

ALLOWED_KINDS = frozenset({
    "summary",
    "handoff",
    "decision-log",
    "incident",
    "research",
    "prompt-pack",
})

VAGUE_NAMES = frozenset({"summary.md", "notes.md", "conversation.md", "README.md"})


def _conversation_files() -> list[Path]:
    if not CONVERSATIONS_DIR.is_dir():
        return []
    return sorted(
        p
        for p in CONVERSATIONS_DIR.iterdir()
        if p.is_file() and p.suffix == ".md" and p.name != "README.md"
    )


def test_readme_exists():
    """docs/conversations/README.md must exist."""
    assert README.is_file(), f"Missing README at {README}"


def test_no_vague_filenames():
    """No file should use vague names like summary.md or notes.md."""
    for f in _conversation_files():
        assert f.name not in VAGUE_NAMES, (
            f"Vague filename {f.name!r}; rename per YYYY-MM-DD--project--phase-range--topic--kind.md"
        )


def test_canonical_filename_pattern():
    """Every conversation file must match the canonical pattern."""
    for f in _conversation_files():
        assert CANONICAL_PATTERN.match(f.name), (
            f"{f.name!r} does not match pattern "
            f"YYYY-MM-DD--project--phase-range--topic--kind.md"
        )


def test_valid_kind():
    """Extract kind from filename and verify it's in the allowed set."""
    for f in _conversation_files():
        stem = f.stem  # strips .md
        kind = stem.split("--")[-1]
        assert kind in ALLOWED_KINDS, (
            f"{f.name!r}: invalid kind {kind!r}; must be one of {sorted(ALLOWED_KINDS)}"
        )


def test_topic_word_count():
    """Topic field must be 3-8 words."""
    for f in _conversation_files():
        stem = f.stem
        parts = stem.split("--")
        topic = parts[3] if len(parts) >= 4 else ""
        word_count = len(topic.split("-"))
        assert 3 <= word_count <= 8, (
            f"{f.name!r}: topic {topic!r} has {word_count} words; need 3-8"
        )


def test_project_is_kebab():
    """Project field must be lowercase kebab-case."""
    for f in _conversation_files():
        stem = f.stem
        parts = stem.split("--")
        project = parts[1] if len(parts) >= 2 else ""
        assert re.match(r"^[a-z][a-z0-9-]*$", project), (
            f"{f.name!r}: project {project!r} is not kebab-case"
        )


def test_phase_range_is_kebab():
    """Phase-range field must be lowercase kebab-case."""
    for f in _conversation_files():
        stem = f.stem
        parts = stem.split("--")
        phase = parts[2] if len(parts) >= 3 else ""
        assert re.match(r"^[a-z][a-z0-9-]*$", phase), (
            f"{f.name!r}: phase-range {phase!r} is not kebab-case"
        )


def test_indexed_files_exist():
    """Every file listed in the README index must exist on disk."""
    if not README.is_file():
        pytest.skip("README not yet created")
    text = README.read_text("utf-8")
    lines = text.splitlines()
    in_table = False
    indexed = []
    for line in lines:
        if line.startswith("|---"):
            in_table = True
            continue
        if in_table and line.strip() and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 6:
                file_cell = cells[5]
                # Extract filename from markdown link
                if "]" in file_cell:
                    file_cell = file_cell.split("](")[-1].rstrip(")")
                if file_cell.endswith(".md"):
                    indexed.append(file_cell)
        elif in_table and not line.strip():
            break
    for name in indexed:
        assert (CONVERSATIONS_DIR / name).is_file(), (
            f"Index references {name!r} but file does not exist"
        )
