"""Repository intake service — read-only preview of an unfamiliar repository.

Slice 1A: Desktop Repository Preview Intake v1.
Gate 0: Zero writes to the user repository. All results are ephemeral
in-memory previews. No claims, receipts, or mission state are created.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import DigestionTelemetryProjection

from rig_relay.digestion.ecosystem_detector import detect_ecosystems
from rig_relay.digestion.freshness import compute_dirty_state_digest, compute_freshness
from rig_relay.digestion.identity import (
    derive_repository_identity_candidate,
    is_github_backed,
    parse_dirty_state_from_porcelain,
    resolve_git_branch,
    resolve_git_head_sha,
    resolve_git_porcelain_v2,
    resolve_git_remotes,
    resolve_git_worktree_root,
)
from rig_relay.digestion.instruction_scanner import discover_instructions
from rig_relay.digestion.mission_proposer import propose_mission
from rig_relay.digestion.models import (
    LocalRepositoryOperatingPicture,
    OpenedRepository,
    StructuralCapabilities,
)
from rig_relay.digestion.telemetry_projection import build_telemetry_projection
from rig_relay.digestion.topology_mapper import map_topology
from rig_relay.digestion.validation_detector import detect_validation_candidates


@dataclass(frozen=True)
class IntakeResult:
    """Result of repository preview intake. All data is ephemeral in-memory.

    No durable state is persisted. No claims, receipts, or mission state
    are created. User must explicitly register and admit a mission.
    """

    repository: OpenedRepository
    operating_picture: LocalRepositoryOperatingPicture
    telemetry_projection: DigestionTelemetryProjection


class RepositoryIntakeService:
    """Read-only repository preview intake.

    Opens a local Git repository, inspects it without modifying it,
    and produces a preview operating picture. All results are ephemeral;
    no durable state is persisted until the user registers the repository
    in a future slice.
    """

    def open_local_repository(self, selected_path: Path) -> IntakeResult:
        """Open a local Git repository and produce a preview operating picture.

        Gate 0: Zero writes to selected_path. All state is in-memory only.

        Args:
            selected_path: Path to the repository directory selected by the user.

        Returns:
            IntakeResult with repository reference, operating picture, and
            content-light telemetry projection.

        Raises:
            ValueError: If the path is not accessible or not a Git repo.
        """
        resolved = selected_path.resolve()

        if not resolved.is_dir():
            raise ValueError(f"Selected path is not a directory: {resolved}")

        # Validate git worktree
        git_root = resolve_git_worktree_root(resolved)
        if git_root is None:
            raise ValueError(
                "The selected folder does not appear to be a Git repository. "
                "Rig Relay currently requires Git repositories."
            )

        # Resolve Git state
        branch = resolve_git_branch(git_root)
        head_sha = resolve_git_head_sha(git_root)
        remotes = resolve_git_remotes(git_root)
        github_backed = is_github_backed(remotes)
        porcelain = resolve_git_porcelain_v2(git_root)
        dirty_state = parse_dirty_state_from_porcelain(porcelain)

        # Build repository reference
        repo = OpenedRepository(
            root_path=str(git_root),
            git_root=str(git_root),
            is_git_repo=True,
            branch=branch,
            head_sha=head_sha,
            remotes=remotes,
            is_github_backed=github_backed,
            is_local_only=len(remotes) == 0,
        )

        # Ephemeral identity candidate — NOT durable
        identity = derive_repository_identity_candidate(
            git_root, remotes, github_backed
        )

        # Digest: ecosystem detection
        ecosystems = detect_ecosystems(git_root)
        detected_languages = [e.language for e in ecosystems]

        # Digest: instruction discovery
        instructions = discover_instructions(git_root)

        # Digest: topology
        topology = map_topology(git_root, detected_languages)

        # Digest: validation candidates
        commands = detect_validation_candidates(git_root, ecosystems)

        # Digest: freshness
        manifest_paths = _collect_manifest_paths(git_root, ecosystems)
        instruction_paths = [inst.scope.path for inst in instructions]
        dirty_digest = compute_dirty_state_digest(
            _dirty_paths_from_porcelain(porcelain)
        )
        freshness = compute_freshness(
            git_root, head_sha, dirty_digest, manifest_paths, instruction_paths
        )

        # Digest: mission proposal
        mission = propose_mission(topology, commands, repo.is_git_repo)

        # Structural capabilities
        capabilities = _detect_structural_capabilities()

        # Known gaps
        gaps: list[str] = []
        if github_backed and not remotes:
            gaps.append("GitHub remote detected but no URL resolved")
        if not ecosystems:
            gaps.append("No supported ecosystem detected")
        if mission.indeterminate_items:
            gaps.append("Indeterminate topology entries require manual review")

        # Recommendations
        recommendations: list[str] = []
        if ecosystems:
            lang_names = ", ".join(e.language for e in ecosystems)
            recommendations.append(
                f"Detected {lang_names}. Suggested validation commands are "
                f"available in the mission proposal."
            )
        if mission.checkpoint_supported:
            recommendations.append(
                "Governed checkpointing is supported on this repository."
            )
        recommendations.append(
            "Select 'Propose Mission' to prepare a bounded mission scope. "
            "No edits or commits will be made until you explicitly admit a mission."
        )

        # Assemble operating picture
        picture = LocalRepositoryOperatingPicture(
            repository=repo,
            identity_candidate=identity,
            dirty_state=dirty_state,
            detected_ecosystems=ecosystems,
            detected_commands=commands,
            instruction_files=instructions,
            topology=topology,
            structural_capabilities=capabilities,
            freshness=freshness,
            mission_proposal=mission,
            known_gaps=gaps,
            recommendations=recommendations,
        )

        # Content-light telemetry projection
        telemetry = build_telemetry_projection(picture)

        return IntakeResult(
            repository=repo, operating_picture=picture, telemetry_projection=telemetry
        )


def _collect_manifest_paths(repo_root: Path, ecosystems: list) -> list[str]:
    """Collect relative paths to manifest files from ecosystem evidence."""
    paths: list[str] = []
    for eco in ecosystems:
        for evidence in eco.evidence_files:
            try:
                rel = Path(evidence).relative_to(repo_root)
                paths.append(str(rel))
            except ValueError:
                paths.append(evidence)
    return paths


_PORCELAIN_V2_PATH_INDEX = 8
_PORCELAIN_V2_RENAME_SOURCE_INDEX = 9
_PORCELAIN_V2_MIN_PARTS_FOR_PATH = 9
_PORCELAIN_V2_MIN_PARTS_FOR_RENAME = 11
_RENAME_STATUS_CODES: set[str] = {"R", "C"}


def _dirty_paths_from_porcelain(porcelain: str) -> list[str]:
    """Extract dirty file paths from porcelain v2 output."""
    paths: list[str] = []
    for line in porcelain.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # porcelain v2 format: XY <sub> <mH> <mI> <mW> <hH> <hI> <path>
        # The path starts after the 7th space-delimited field
        parts = line.split()
        if len(parts) >= _PORCELAIN_V2_MIN_PARTS_FOR_PATH:
            path = parts[_PORCELAIN_V2_PATH_INDEX]
            paths.append(path)
            if (
                parts[0][0] in _RENAME_STATUS_CODES
                and len(parts) >= _PORCELAIN_V2_MIN_PARTS_FOR_RENAME
            ):
                paths.append(parts[_PORCELAIN_V2_RENAME_SOURCE_INDEX])
    return paths


def _detect_structural_capabilities() -> StructuralCapabilities:
    """Detect available structural inspection capabilities."""
    from importlib.util import find_spec

    caps = StructuralCapabilities()

    if find_spec("ast") is not None:
        caps.python_ast_available = True

    if find_spec("ast_grep_py") is not None:
        caps.ast_grep_available = True

    if find_spec("rig_relay.core.tools.builtins.inspect_structure") is not None:
        caps.inspect_structure_available = True

    return caps
