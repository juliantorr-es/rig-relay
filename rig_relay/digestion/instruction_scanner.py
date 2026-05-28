"""Instruction and governance file discovery with scoped applicability.

Discovers AGENTS.md, CLAUDE.md, PROJECT.md, CONTRIBUTING.md, CODEOWNERS,
SECURITY.md, CI workflows, rule directories, and other instruction files.
Models scope and precedence with optional content loading.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from rig_relay.core.logger import logger
from rig_relay.core.utils.io import read_safe

if TYPE_CHECKING:
    from rig_relay.digestion.models import (
        InstructionFile,
        InstructionScope,
        InstructionScopeCollection,
    )


_MAX_CONTENT_BYTES = 1_048_576  # 1 MB


# Known instruction file names and their default kinds
_KNOWN_INSTRUCTION_FILES: dict[str, str] = {
    "AGENTS.md": "agent_instructions",
    "CLAUDE.md": "agent_instructions",
    "CLAUDE.local.md": "agent_instructions",
    "PROJECT.md": "agent_instructions",
    "CONTRIBUTING.md": "contributor_guide",
    "CONTRIBUTING.rst": "contributor_guide",
    "CODEOWNERS": "governance",
    "SECURITY.md": "security_policy",
    "CODE_OF_CONDUCT.md": "governance",
    "CHANGELOG.md": "unknown",
    "README.md": "unknown",
    "LICENSE": "governance",
    ".cursorrules": "agent_instructions",
    ".windsurfrules": "agent_instructions",
}

_KNOWN_RULE_DIRECTORIES: dict[str, str] = {
    ".cursor/rules": "agent_instructions",
    ".claude/rules": "agent_instructions",
    ".github/instructions": "agent_instructions",
}

_EXCLUDED_SCAN_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "target",
    "dist",
    "build",
})

_MIN_INSTRUCTIONS_FOR_CONFLICT_CHECK = 2

_CONTRADICTORY_KEYWORD_PAIRS: list[tuple[set[str], set[str]]] = [
    (
        {"poetry", "poetry.lock", "poetry add"},
        {"pip", "uv pip", "requirements.txt", "pip install"},
    ),
    ({"npm", "package.json", "npm install"}, {"yarn", "yarn.lock", "yarn add"}),
    ({"pnpm", "pnpm-lock.yaml"}, {"npm", "package.json"}),
    ({"prettier"}, {"eslint --fix"}),
    ({"cargo", "Cargo.toml"}, {"bazel", "BUILD"}),
    ({"tab", "\t"}, {"space", "  "}),
    ({"jest", "vitest"}, {"mocha", "jasmine"}),
]


def discover_instructions(repo_root: Path) -> list[InstructionFile]:
    """Discover instruction and governance files with scope metadata.

    Scans repo root, .github/, rule directories, and nested instruction
    files for scope-chain modeling.

    Does NOT load file content — only metadata and scope applicability.
    """
    from rig_relay.digestion.models import InstructionFile

    instructions: dict[str, InstructionScope] = {}
    root_path = repo_root.resolve()

    _scan_directory(root_path, root_path, "", 0, instructions)

    github_dir = root_path / ".github"
    if github_dir.is_dir():
        _scan_directory(root_path, github_dir, ".github", 1, instructions)
        workflows_dir = github_dir / "workflows"
        if workflows_dir.is_dir():
            _scan_workflows(root_path, workflows_dir, instructions)
        _scan_rule_directories(root_path, github_dir, ".github", instructions)

    _scan_rule_root_directories(root_path, instructions)
    _scan_tree(root_path, instructions)
    _build_scope_chain(instructions)

    return [
        InstructionFile(
            scope=scope, nested_instructions=_find_nested(scope, instructions)
        )
        for scope in instructions.values()
    ]


def discover_instructions_with_content(repo_root: Path) -> list[InstructionFile]:
    """Discover instruction files and load their content.

    Calls discover_instructions() and reads each discovered file's content
    using read_safe. Sets content_sha256 and content on each InstructionFile.
    Skips binary files and files over 1 MB.
    """
    instructions = discover_instructions(repo_root)
    loaded: list[InstructionFile] = []

    for inst in instructions:
        filepath = repo_root / inst.scope.path
        content: str | None = None
        content_sha256: str | None = None

        try:
            if not filepath.is_file():
                loaded.append(inst)
                continue

            size = filepath.stat().st_size
            if size > _MAX_CONTENT_BYTES:
                logger.debug(
                    "Skipping large instruction file size=%s path=%s",
                    size,
                    inst.scope.path,
                )
                loaded.append(inst)
                continue

            if _is_likely_binary(filepath):
                logger.debug(
                    "Skipping binary instruction file path=%s", inst.scope.path
                )
                loaded.append(inst)
                continue

            result = read_safe(filepath)
            content = result.text
            content_sha256 = hashlib.sha256(content.encode()).hexdigest()
        except OSError as exc:
            logger.warning(
                "Failed to read instruction file path=%s error=%s", inst.scope.path, exc
            )

        loaded.append(
            inst.model_copy(
                update={"content": content, "content_sha256": content_sha256}
            )
        )

    return loaded


def resolve_instruction_scope(repo_root: Path, target_path: str) -> str:
    """Resolve the full combined instruction text applicable to a path.

    Discovers instructions with content, finds those that apply to
    target_path via effective_instructions_for(), and concatenates
    their content in precedence order (broadest first, most specific last).
    """
    instructions = discover_instructions_with_content(repo_root)
    applicable = effective_instructions_for(instructions, target_path)

    parts: list[str] = []
    for inst in applicable:
        if inst.content:
            parts.append(inst.content)

    return "\n\n".join(parts)


def build_scope_map(instructions: list[InstructionFile]) -> InstructionScopeCollection:
    """Build an aggregated scope map from discovered instruction files.

    Computes applicable instructions for each top-level directory in the
    repo and detects conflicting instruction pairs via keyword overlap.
    """
    from rig_relay.digestion.models import InstructionScopeCollection

    scope_map: dict[str, list[str]] = {}

    # Collect unique scope roots from all instruction files
    all_roots: set[str] = {inst.scope.scope_root for inst in instructions}
    all_roots.add(".")

    for root in sorted(all_roots):
        applicable = effective_instructions_for(instructions, root)
        scope_map[root] = [inst.scope.path for inst in applicable]

    conflicts = _detect_instruction_conflicts(instructions)

    return InstructionScopeCollection(
        instruction_files=instructions, scope_map=scope_map, conflicts=conflicts
    )


# ── private scan helpers ──────────────────────────────────────────


def _scan_directory(
    repo_root: Path,
    directory: Path,
    dir_prefix: str,
    depth: int,
    instructions: dict[str, InstructionScope],
) -> None:
    from rig_relay.digestion.models import InstructionKind, InstructionScope

    for filename, kind in _KNOWN_INSTRUCTION_FILES.items():
        filepath = directory / filename
        if not filepath.is_file():
            continue

        rel_path = str(filepath.relative_to(repo_root))
        if rel_path in instructions:
            continue

        scope_root = dir_prefix if dir_prefix else "."

        applies_to_paths: list[str] = []
        if scope_root == ".":
            applies_to_paths = ["*"]
        else:
            applies_to_paths = [f"{scope_root}/*"]

        parent = None
        if depth > 0 and dir_prefix:
            parent_dir = str(Path(dir_prefix).parent)
            if parent_dir == ".":
                parent = "AGENTS.md" if (repo_root / "AGENTS.md").is_file() else None
            else:
                parent = f"{parent_dir}/AGENTS.md"

        instructions[rel_path] = InstructionScope(
            path=rel_path,
            kind=kind,
            scope_root=scope_root,
            scope_depth=depth,
            applies_to_paths=applies_to_paths,
            applies_to_kind="all",
            parent_instruction_path=parent,
            has_agent_guidance=(kind == InstructionKind.AGENT_INSTRUCTIONS),
            has_validation_commands=False,
        )


def _scan_workflows(
    repo_root: Path, workflows_dir: Path, instructions: dict[str, InstructionScope]
) -> None:
    from rig_relay.digestion.models import InstructionKind, InstructionScope

    for wf in workflows_dir.glob("*.yml"):
        rel_path = str(wf.relative_to(repo_root))
        instructions[rel_path] = InstructionScope(
            path=rel_path,
            kind=InstructionKind.CI_WORKFLOW,
            scope_root=".",
            scope_depth=1,
            applies_to_paths=["*"],
            applies_to_kind="all",
            parent_instruction_path=None,
            has_agent_guidance=False,
            has_validation_commands=False,
        )


def _scan_rule_root_directories(
    repo_root: Path, instructions: dict[str, InstructionScope]
) -> None:
    """Scan repo-root rule directories like .cursor/rules/ and .claude/rules/."""
    for rule_dir_rel, kind in _KNOWN_RULE_DIRECTORIES.items():
        if rule_dir_rel.startswith(".github"):
            continue  # Handled in _scan_rule_directories via github_dir

        rule_dir = repo_root / rule_dir_rel
        if not rule_dir.is_dir():
            continue

        _scan_single_rule_directory(
            repo_root, rule_dir, rule_dir_rel, 1, kind, instructions
        )


def _scan_rule_directories(
    repo_root: Path,
    base_dir: Path,
    dir_prefix: str,
    instructions: dict[str, InstructionScope],
) -> None:
    """Scan rule directories nested under a base directory (e.g. .github/instructions/)."""
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        entry_name = entry.name
        rel_rule_path = f"{dir_prefix}/{entry_name}"
        if rel_rule_path in _KNOWN_RULE_DIRECTORIES:
            kind = _KNOWN_RULE_DIRECTORIES[rel_rule_path]
            _scan_single_rule_directory(
                repo_root,
                entry,
                str(entry.relative_to(repo_root)),
                2,
                kind,
                instructions,
            )


def _scan_single_rule_directory(
    repo_root: Path,
    rule_dir: Path,
    rule_dir_rel: str,
    depth: int,
    kind: str,
    instructions: dict[str, InstructionScope],
) -> None:
    """Scan a single rule directory for .md files with optional frontmatter."""
    from rig_relay.digestion.models import InstructionKind, InstructionScope

    for md_file in sorted(rule_dir.glob("*.md")):
        rel_path = str(md_file.relative_to(repo_root))
        if rel_path in instructions:
            continue

        applies_to_paths = _parse_frontmatter_paths(md_file)
        if not applies_to_paths:
            applies_to_paths = [f"{rule_dir_rel}/*"]

        scope_root = str(Path(rel_path).parent)

        instructions[rel_path] = InstructionScope(
            path=rel_path,
            kind=kind,
            scope_root=scope_root,
            scope_depth=depth,
            applies_to_paths=applies_to_paths,
            applies_to_kind="all",
            parent_instruction_path=None,
            has_agent_guidance=(kind == InstructionKind.AGENT_INSTRUCTIONS),
            has_validation_commands=False,
        )


def _parse_frontmatter_paths(md_file: Path) -> list[str]:
    """Parse YAML frontmatter from a markdown file for path patterns.

    Looks for --- delimited YAML blocks at the start of the file
    containing `paths:`, `applyTo:`, or `globs:` values.
    Returns the extracted path patterns or an empty list.
    """
    try:
        result = read_safe(md_file)
        text = result.text
    except OSError:
        return []

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None or end_idx <= 1:
        return []

    frontmatter = lines[1:end_idx]
    paths: list[str] = []

    for line in frontmatter:
        stripped = line.strip()
        value = _extract_frontmatter_field(stripped)
        if value is not None:
            paths.extend(_parse_frontmatter_path_value(value))

    return paths


def _extract_frontmatter_field(stripped_line: str) -> str | None:
    for prefix in ("paths:", "applyTo:", "globs:"):
        if stripped_line.startswith(prefix):
            return stripped_line[len(prefix) :].strip()
    return None


def _parse_frontmatter_path_value(value: str) -> list[str]:
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [
            item.strip().strip("'").strip('"')
            for item in inner.split(",")
            if item.strip()
        ]
    return [value]


def _scan_tree(repo_root: Path, instructions: dict[str, InstructionScope]) -> None:
    from rig_relay.digestion.models import InstructionKind, InstructionScope

    for dirpath, dirnames, filenames in repo_root.walk():
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _EXCLUDED_SCAN_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            if filename not in _KNOWN_INSTRUCTION_FILES:
                continue

            full_path = dirpath / filename
            if not full_path.is_file():
                continue

            rel_path = str(full_path.relative_to(repo_root))
            if rel_path in instructions:
                continue

            scope_root = str(Path(rel_path).parent)
            scope_depth = 0 if scope_root == "." else len(Path(rel_path).parent.parts)

            kind = _KNOWN_INSTRUCTION_FILES[filename]

            applies_to_paths: list[str]
            if scope_root == ".":
                applies_to_paths = ["*"]
            else:
                applies_to_paths = [f"{scope_root}/*"]

            instructions[rel_path] = InstructionScope(
                path=rel_path,
                kind=kind,
                scope_root=scope_root,
                scope_depth=scope_depth,
                applies_to_paths=applies_to_paths,
                applies_to_kind="all",
                parent_instruction_path=None,
                has_agent_guidance=(kind == InstructionKind.AGENT_INSTRUCTIONS),
                has_validation_commands=False,
            )


def _build_scope_chain(instructions: dict[str, InstructionScope]) -> None:
    sorted_paths = sorted(instructions.keys(), key=lambda p: p.count("/"))
    for path in sorted_paths:
        scope = instructions[path]
        if scope.parent_instruction_path is not None:
            continue

        parent_dir = str(Path(path).parent)
        while parent_dir and parent_dir != ".":
            for candidate in sorted_paths:
                if str(Path(candidate).parent) == parent_dir:
                    scope.parent_instruction_path = candidate
                    break
            if scope.parent_instruction_path is not None:
                break
            parent_dir = str(Path(parent_dir).parent)


def _find_nested(
    scope: InstructionScope, instructions: dict[str, InstructionScope]
) -> list[str]:
    nested: list[str] = []
    scope_dir = scope.scope_root
    if scope_dir == ".":
        scope_dir = ""
    for path, other in instructions.items():
        if other is scope:
            continue
        if other.parent_instruction_path == scope.path:
            nested.append(path)
    return nested


def effective_instructions_for(
    instructions: list[InstructionFile], target_path: str
) -> list[InstructionFile]:
    """Find all instruction files that apply to a given path.

    Orders from broadest (scope_depth=0) to most specific (highest depth).
    The most specific scope wins on conflicting directives.

    Args:
        instructions: All discovered instruction files.
        target_path: Repo-relative path to check.

    Returns:
        Applicable instruction files ordered broadest → most specific.
    """
    applicable: list[tuple[int, InstructionFile]] = []
    target = Path(target_path)

    for inst in instructions:
        scope = inst.scope
        scope_path = Path(scope.scope_root) if scope.scope_root != "." else Path(".")
        try:
            target.relative_to(scope_path)
            applicable.append((scope.scope_depth, inst))
        except ValueError:
            continue

    applicable.sort(key=lambda x: x[0])
    return [inst for _, inst in applicable]


def _detect_instruction_conflicts(
    instructions: list[InstructionFile],
) -> list[tuple[str, str, str]]:
    """Detect conflicting instruction declarations via keyword overlap.

    When two agent instruction files at the same scope depth contain
    keywords from known contradictory pairs, record a conflict.
    """
    conflicts: list[tuple[str, str, str]] = []

    agent_instructions = [
        inst for inst in instructions if inst.content and inst.scope.has_agent_guidance
    ]
    if len(agent_instructions) < _MIN_INSTRUCTIONS_FOR_CONFLICT_CHECK:
        return conflicts

    for i in range(len(agent_instructions)):
        for j in range(i + 1, len(agent_instructions)):
            inst_a = agent_instructions[i]
            inst_b = agent_instructions[j]

            if inst_a.scope.scope_depth != inst_b.scope.scope_depth:
                continue

            if inst_a.content is None or inst_b.content is None:
                continue
            content_a_lower = inst_a.content.lower()
            content_b_lower = inst_b.content.lower()

            for set_a, set_b in _CONTRADICTORY_KEYWORD_PAIRS:
                a_hit = any(kw in content_a_lower for kw in set_a)
                b_hit = any(kw in content_b_lower for kw in set_b)
                b_alt = any(kw in content_b_lower for kw in set_a)
                a_alt = any(kw in content_a_lower for kw in set_b)

                if (a_hit and b_hit) and not (a_alt and b_alt):
                    conflicts.append((
                        inst_a.scope.path,
                        inst_b.scope.path,
                        f"contradictory declarations: {_describe_pair(set_a)} vs {_describe_pair(set_b)}",
                    ))
                    break

    return conflicts


def _describe_pair(pair: set[str]) -> str:
    representative = next(iter(sorted(pair)))
    return representative


def _is_likely_binary(filepath: Path) -> bool:
    """Check if a file is likely binary by reading its first 1024 bytes."""
    try:
        raw = filepath.read_bytes()[:1024]
    except OSError:
        return True
    return b"\0" in raw
