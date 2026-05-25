"""Content-light telemetry projection from full-fidelity operating picture.

Slice 1A: Desktop Repository Preview Intake v1.
Excludes raw paths, repo names, command strings, instruction content,
filenames, and diffs. Safe for telemetry and external evidence.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import (
        DigestionTelemetryProjection,
        LocalRepositoryOperatingPicture,
    )


def build_telemetry_projection(
    picture: LocalRepositoryOperatingPicture,
) -> DigestionTelemetryProjection:
    """Build a content-light projection from a full operating picture.

    All raw local detail is stripped. Only categories, counts, status
    classes, confidence classes, and opaque digests remain.
    """
    from rig_relay.digestion.models import DigestionTelemetryProjection

    repo = picture.repository

    # Ecosystem summary — categories only
    ecosystem_summary: list[dict] = []
    for eco in picture.detected_ecosystems:
        ecosystem_summary.append({
            "language": eco.language,
            "confidence": eco.confidence,
            "package_manager_present": eco.package_manager is not None,
            "test_framework_count": len(eco.test_frameworks),
            "lint_tool_count": len(eco.lint_tools),
            "type_checker_count": len(eco.type_checkers),
            "formatter_count": len(eco.formatters),
            "entry_point_count": len(eco.entry_points),
        })

    # Command summary — by kind and safety
    command_summary: list[dict] = []
    for cmd in picture.detected_commands:
        command_summary.append({
            "kind": cmd.kind,
            "safety_classification": cmd.safety_classification,
            "provenance": cmd.provenance,
            "confidence": cmd.confidence,
        })

    # Instruction file summary — by kind, no paths
    instruction_summary: list[dict] = []
    for inst in picture.instruction_files:
        instruction_summary.append({
            "kind": inst.scope.kind,
            "scope_depth": inst.scope.scope_depth,
            "has_agent_guidance": inst.scope.has_agent_guidance,
            "has_validation_commands": inst.scope.has_validation_commands,
            "nested_count": len(inst.nested_instructions),
        })

    # Topology summary — by kind, no names
    topology_summary: list[dict] = []
    kind_counts: dict[str, int] = {}
    for entry in picture.topology:
        kind = entry.kind
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    for kind, count in sorted(kind_counts.items()):
        topology_summary.append({"kind": kind, "count": count})

    # Git state summary
    ds = picture.dirty_state
    git_state_summary = {
        "branch_present": repo.branch is not None,
        "dirty_files_total": ds.modified + ds.staged + ds.untracked + ds.deleted,
        "diverged": False,  # Not computed in Phase 1A
        "head_sha_present": repo.head_sha is not None,
    }

    # Structural capabilities
    sc = picture.structural_capabilities
    structural_caps = []
    if sc.ast_grep_available:
        structural_caps.append("ast_grep")
    if sc.inspect_structure_available:
        structural_caps.append("inspect_structure")
    if sc.python_ast_available:
        structural_caps.append("python_ast")

    # Freshness digest — opaque
    freshness_digest = hashlib.sha256(
        picture.freshness.generated_at.encode("utf-8")
    ).hexdigest()[:16]

    return DigestionTelemetryProjection(
        opaque_repository_id_digest=_opaque_digest(picture),
        is_git_repo=repo.is_git_repo,
        is_github_backed=repo.is_github_backed,
        is_local_only=repo.is_local_only,
        ecosystem_summary=ecosystem_summary,
        command_summary=command_summary,
        instruction_file_summary=instruction_summary,
        topology_summary=topology_summary,
        git_state_summary=git_state_summary,
        structural_inspection_capabilities=structural_caps,
        freshness_digest=freshness_digest,
        known_gap_count=len(picture.known_gaps),
        indeterminate_item_count=len(picture.mission_proposal.indeterminate_items),
        generated_at=picture.freshness.generated_at,
    )


def _opaque_digest(picture: LocalRepositoryOperatingPicture) -> str:
    """Derive an opaque digest that does not reveal repo identity details."""
    repo = picture.repository
    parts = [
        repo.is_git_repo,
        repo.is_github_backed,
        repo.is_local_only,
        str(len(picture.detected_ecosystems)),
        str(len(picture.detected_commands)),
        str(len(picture.instruction_files)),
        str(len(picture.topology)),
    ]
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
