from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any

from rig_relay.workspace.models import (
    FleetWorkspaceProjection,
    FleetWorkspaceProjectionItem,
    ManagedWorkspace,
    RecoveryState,
    WorkspaceState,
)

_ACTIVE_CLAIM_STATES: frozenset[str] = frozenset({
    "claimed",
    "editing",
    "tests_running",
    "ready_for_integration",
})
_BLOCKED_CLAIM_STATES: frozenset[str] = frozenset({"blocked"})


def _compute_claim_state(
    ws: ManagedWorkspace, workspace_claims: dict[str, list[Any]] | None
) -> str:
    if workspace_claims is None:
        return "unavailable"
    claims = workspace_claims.get(ws.identity.workspace_id, [])
    if not claims:
        return "unclaimed"
    for claim in claims:
        state = getattr(claim, "state", None)
        if state is None:
            continue
        state_val = state.value if hasattr(state, "value") else str(state)
        if state_val in _BLOCKED_CLAIM_STATES:
            return "conflict"
        if state_val in _ACTIVE_CLAIM_STATES:
            return "claimed"
    return "unclaimed"


def build_fleet_workspace_projection(
    workspaces: list[ManagedWorkspace],
    workspace_claims: dict[str, list[Any]] | None = None,
) -> FleetWorkspaceProjection:
    items: list[FleetWorkspaceProjectionItem] = []
    for ws in workspaces:
        claim_state = _compute_claim_state(ws, workspace_claims)
        items.append(_workspace_to_projection_item(ws, claim_state=claim_state))
    active_count = sum(1 for ws in workspaces if ws.state == WorkspaceState.ACTIVE)
    recovery_count = sum(1 for ws in workspaces if ws.recovery_state is not None)
    warnings: list[str] = []
    if recovery_count > 0:
        warnings.append(f"{recovery_count} workspace(s) require recovery")
    return FleetWorkspaceProjection(
        generated_at=datetime.now(UTC).isoformat(),
        total_workspaces=len(workspaces),
        active_workspaces=active_count,
        recovery_needed=recovery_count,
        workspaces=items,
        warnings=warnings,
    )


def _workspace_to_projection_item(
    ws: ManagedWorkspace, claim_state: str = "unavailable"
) -> FleetWorkspaceProjectionItem:
    worktree_hash = None
    if ws.worktree_path:
        worktree_hash = hashlib.sha256(ws.worktree_path.encode()).hexdigest()
    display_status = _derive_display_status(
        state=ws.state.value if hasattr(ws.state, "value") else str(ws.state),
        recovery_state=(
            ws.recovery_state.value
            if ws.recovery_state is not None and hasattr(ws.recovery_state, "value")
            else ws.recovery_state
        ),
        assignment_state=None,
    )
    return FleetWorkspaceProjectionItem(
        workspace_id=ws.identity.workspace_id,
        project_identity=ws.identity.project_identity,
        role=ws.identity.role,
        branch_summary=ws.branch_name,
        lifecycle_status=ws.state,
        recovery_required=ws.recovery_state is not None,
        changed_files_count=ws.changed_files_count,
        checkpoint_state="present" if ws.checkpoint_sha else "absent",
        claim_state=claim_state,
        safe_available_actions=_infer_safe_actions(ws.state, ws.recovery_state),
        base_sha=ws.base_commit_sha[:8] if ws.base_commit_sha else None,
        head_sha=ws.head_sha[:8] if ws.head_sha else None,
        branch_name=ws.branch_name,
        worktree_path_hash=worktree_hash,
        session_id=ws.session_id[:8] if ws.session_id else None,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        display_status=display_status,
    )


def _derive_display_status(
    state: str, recovery_state: str | None, assignment_state: str | None
) -> str:
    if recovery_state in {"session_detached", "recovery_required"}:
        return "Recovery Required"
    if recovery_state == "recovered":
        return "Work Preserved"
    if recovery_state in {
        "quarantined",
        "reservation_refused",
        "reset_refused",
        "removal_refused",
    }:
        return "Unavailable"
    state_map: dict[str, str] = {
        "requested": "Setup Required",
        "reserved": "Setup Required",
        "worktree_created": "Setup Required",
        "bootstrapping": "Setup Required",
        "ready": "Ready",
        "active": "Active",
        "validating": "Validation Required",
        "under_review": "Under Review",
        "checkpointed": "Released",
        "released_for_integration": "Released",
        "integrated": "Released",
        "published": "Released",
        "retired": "Retired",
    }
    return state_map.get(state, "Unavailable")


def _infer_safe_actions(
    state: WorkspaceState, recovery: RecoveryState | None
) -> list[str]:
    actions: list[str] = []
    match state:
        case WorkspaceState.REQUESTED:
            actions = ["reserve"]
        case WorkspaceState.RESERVED:
            actions = ["create_worktree"]
        case WorkspaceState.WORKTREE_CREATED:
            actions = ["bootstrap"]
        case WorkspaceState.BOOTSTRAPPING:
            actions = ["wait"]
        case WorkspaceState.READY:
            actions = ["activate"]
        case WorkspaceState.ACTIVE:
            actions = ["checkpoint", "validate", "release", "claim_boundary"]
        case WorkspaceState.VALIDATING:
            actions = ["review", "checkpoint", "claim_boundary"]
        case WorkspaceState.UNDER_REVIEW:
            actions = ["checkpoint", "release_for_integration", "claim_boundary"]
        case WorkspaceState.CHECKPOINTED:
            actions = ["release_for_integration"]
        case WorkspaceState.RELEASED_FOR_INTEGRATION:
            actions = ["mark_integrated", "claim_boundary"]
        case WorkspaceState.INTEGRATED:
            actions = ["mark_published"]
        case WorkspaceState.PUBLISHED:
            actions = ["retire"]
        case WorkspaceState.RETIRED:
            actions = []
    if recovery is not None:
        actions = list({*actions, "recover", "quarantine"})
    return actions


__all__ = ["build_fleet_workspace_projection"]
