"""Mission admission — bind authority to an execution workspace.

Slice 1C: Managed Worktree Provisioning and Mission Admission.
Admits a bounded mission against a provisioned execution workspace.
Authority is bound to execution_workspace_id, not source checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid


@dataclass(frozen=True)
class MissionAdmission:
    """Admitted mission bound to a specific execution workspace.

    The admission binds a coordination claim, authority, and dirty
    baseline to the execution workspace. The source checkout is never
    the target of mission authority.
    """

    admission_id: str
    execution_workspace_id: str
    repository_id: str
    source_checkout_id: str
    admitted_paths: list[str] = field(default_factory=list)
    admitted_validation_commands: list[str] = field(default_factory=list)
    checkpoint_admitted: bool = False
    generated_at: str = ""


def admit_mission(
    execution_workspace_id: str,
    repository_id: str,
    source_checkout_id: str,
    workspace_root: str,
    admitted_paths: list[str],
    admitted_validation_commands: list[str],
    checkpoint_admitted: bool = True,
) -> MissionAdmission:
    """Admit a bounded mission against a provisioned execution workspace.

    Does NOT install authority or initialize AgentLoop. That is Slice 1D.
    Produces a MissionAdmission record that binds the workspace identity
    to the admitted scope.

    Args:
        execution_workspace_id: The provisioned workspace identity.
        repository_id: Logical repository identity.
        source_checkout_id: Source checkout identity (for provenance).
        workspace_root: Absolute path to the managed workspace.
        admitted_paths: Paths admitted for writable scope within the workspace.
        admitted_validation_commands: Validation commands admitted for execution.
        checkpoint_admitted: Whether governed checkpointing is admitted.

    Returns:
        MissionAdmission with workspace-scoped authority binding.
    """
    from datetime import UTC, datetime

    return MissionAdmission(
        admission_id=str(uuid.uuid4()),
        execution_workspace_id=execution_workspace_id,
        repository_id=repository_id,
        source_checkout_id=source_checkout_id,
        admitted_paths=list(admitted_paths),
        admitted_validation_commands=list(admitted_validation_commands),
        checkpoint_admitted=checkpoint_admitted,
        generated_at=datetime.now(UTC).isoformat(),
    )
