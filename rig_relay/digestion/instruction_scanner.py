"""Instruction and governance file discovery with scoped applicability.

Slice 1A: Desktop Repository Preview Intake v1.
Discovers AGENTS.md, CLAUDE.md, CONTRIBUTING.md, CODEOWNERS, SECURITY.md,
CI workflows, and other instruction files. Models scope and precedence
without loading file content.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import InstructionFile, InstructionScope


# Known instruction file names and their default kinds
_KNOWN_INSTRUCTION_FILES: dict[str, str] = {
    "AGENTS.md": "agent_instructions",
    "CLAUDE.md": "agent_instructions",
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


def discover_instructions(repo_root: Path) -> list[InstructionFile]:
    """Discover instruction and governance files with scope metadata.

    Scans repo root and .github/ for known instruction files. Also
    discovers nested instruction files for scope-chain modeling.

    Does NOT load file content — only metadata and scope applicability.
    """
    from rig_relay.digestion.models import InstructionFile

    instructions: dict[str, InstructionScope] = {}
    root_path = repo_root.resolve()

    # Scan for known instruction files
    _scan_directory(root_path, root_path, "", 0, instructions)

    # Scan .github/ directory
    github_dir = root_path / ".github"
    if github_dir.is_dir():
        _scan_directory(root_path, github_dir, ".github", 1, instructions)
        # Scan .github/workflows/ for CI workflow files
        workflows_dir = github_dir / "workflows"
        if workflows_dir.is_dir():
            _scan_workflows(root_path, workflows_dir, instructions)

    # Build parent-child chains for nested instructions
    _build_scope_chain(instructions)

    return [
        InstructionFile(
            scope=scope, nested_instructions=_find_nested(scope, instructions)
        )
        for scope in instructions.values()
    ]


def _scan_directory(
    repo_root: Path,
    directory: Path,
    dir_prefix: str,
    depth: int,
    instructions: dict[str, InstructionScope],
) -> None:
    """Scan a directory for known instruction files."""
    from rig_relay.digestion.models import InstructionKind, InstructionScope

    for filename, kind in _KNOWN_INSTRUCTION_FILES.items():
        filepath = directory / filename
        if not filepath.is_file():
            continue

        rel_path = str(filepath.relative_to(repo_root))
        if rel_path in instructions:
            continue

        scope_root = dir_prefix if dir_prefix else "."

        # Determine applies_to_paths from scope root
        applies_to_paths: list[str] = []
        if scope_root == ".":
            applies_to_paths = ["*"]
        else:
            applies_to_paths = [f"{scope_root}/*"]

        # Determine precedence and parent
        parent = None
        if depth > 0 and dir_prefix:
            # Find parent scope — the directory one level up
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
    """Discover CI workflow files as instruction surfaces.

    Does NOT extract commands from workflows in Phase 1A.
    """
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


def _build_scope_chain(instructions: dict[str, InstructionScope]) -> None:
    """Build parent-child scope chains for nested instruction files.

    A nested instruction at src/subpackage/AGENTS.md has:
    - parent_instruction_path = root AGENTS.md (if it exists)
    - scope_depth = depth of src/subpackage/
    """
    # Sort by path depth for deterministic parent assignment
    sorted_paths = sorted(instructions.keys(), key=lambda p: p.count("/"))
    for path in sorted_paths:
        scope = instructions[path]
        if scope.parent_instruction_path is not None:
            continue  # Parent already assigned

        # Find the nearest ancestor instruction file
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
    """Find instruction files nested within this scope."""
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
        # Check if the target path falls within the instruction's scope_root
        scope_path = Path(scope.scope_root) if scope.scope_root != "." else Path(".")
        try:
            target.relative_to(scope_path)
            applicable.append((scope.scope_depth, inst))
        except ValueError:
            continue

    applicable.sort(key=lambda x: x[0])
    return [inst for _, inst in applicable]
