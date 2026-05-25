"""Mission proposal generation from repository operating picture.

Slice 1A: Desktop Repository Preview Intake v1.
Generates a MissionProposalInput. Does NOT create claims, install authority,
or start AgentLoop. User must explicitly admit the mission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import (
        DetectedCommand,
        MissionProposalInput,
        TopologyEntry,
    )


def propose_mission(
    topology: list[TopologyEntry], commands: list[DetectedCommand], is_git_repo: bool
) -> MissionProposalInput:
    """Generate a mission proposal from topology and detected commands.

    Categorizes directories into scope candidates and compiles validation
    commands. Tests are paired with source candidates, not excluded.

    Args:
        topology: Classified repository topology entries.
        commands: Detected validation command candidates.
        is_git_repo: Whether the repository is a valid Git worktree.

    Returns:
        A MissionProposalInput with categorized scope candidates.
    """
    from rig_relay.digestion.models import MissionProposalInput

    source_candidates: list[str] = []
    paired_test_candidates: list[str] = []
    doc_candidates: list[str] = []
    config_surfaces: list[str] = []
    generated_candidates: list[str] = []
    indeterminate: list[str] = []

    for entry in topology:
        kind = entry.kind
        if kind == "source":
            source_candidates.append(entry.name)
        elif kind == "test":
            paired_test_candidates.append(entry.name)
        elif kind == "docs":
            doc_candidates.append(entry.name)
        elif kind in {"schemas", "config"}:
            config_surfaces.append(entry.name)
        elif kind == "generated":
            generated_candidates.append(entry.name)
        elif kind == "unknown":
            indeterminate.append(entry.name)

    suggested: list[str] = []
    mutating: list[str] = []
    for cmd in commands:
        if cmd.safety_classification == "read_only_validation":
            suggested.append(cmd.command)
        elif cmd.safety_classification == "writes_workspace":
            mutating.append(cmd.command)

    checkpoint_supported = is_git_repo

    requires_confirmation: list[str] = []
    if mutating:
        requires_confirmation.append(
            f"Formatting commands are workspace-mutating: {', '.join(mutating[:3])}"
        )
    if indeterminate:
        requires_confirmation.append(
            f"Unclassified directories need manual scope review: {', '.join(indeterminate[:5])}"
        )

    return MissionProposalInput(
        source_candidates=source_candidates,
        paired_test_candidates=paired_test_candidates,
        doc_candidates=doc_candidates,
        config_surfaces_requiring_expansion=config_surfaces,
        generated_output_candidates=generated_candidates,
        suggested_validation_commands=suggested,
        potentially_mutating_commands=mutating,
        checkpoint_supported=checkpoint_supported,
        indeterminate_items=indeterminate,
        requires_user_confirmation=requires_confirmation,
        ci_workflow_command_extraction="deferred",
    )
