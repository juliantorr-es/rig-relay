"""PatchGatingService — pure policy check for mutation tool gating.

Step 4 of AgentLoop mixin refactor. Extracted from PatchGatingMixin
into a standalone service with explicit dependencies. No MRO-based
self.* access, no side effects.

Accepts session_id, workspace_root, and agent_profile at construction.
The check() method is a pure policy check: it returns a ToolResultEvent
if the tool should be blocked (patch_proposal_mode), or None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rig_relay.core.types import ToolResultEvent

if TYPE_CHECKING:
    from pathlib import Path

    from rig_relay.core.agents.models import AgentProfile
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.tools.base import BaseTool


class PatchGatingService:
    """Pure policy check for patch proposal gating of mutation tools.

    When the agent profile has patch_proposal_mode=True, write/delete/
    checkpoint tools produce a PatchProposal receipt instead of
    executing directly. The user must approve before workspace mutation.
    """

    __slots__ = ("_session_id", "_workspace_root", "_agent_profile")

    def __init__(
        self, *, session_id: str, workspace_root: Path, agent_profile: AgentProfile
    ) -> None:
        self._session_id = session_id
        self._workspace_root = workspace_root
        self._agent_profile = agent_profile

    def check(
        self, tool_call: ResolvedToolCall, tool_instance: BaseTool
    ) -> ToolResultEvent | None:
        """Check if a mutation tool should be gated by patch proposal mode.

        Returns a ToolResultEvent with skip_reason if gated, or None
        if the tool should execute normally.
        """
        if not self._agent_profile.patch_proposal_mode:
            return None

        mutation_cls = getattr(tool_instance, "mutation_class", None)
        if mutation_cls is None:
            return None

        mutation_str = str(mutation_cls.value)
        mutation_write = mutation_str in {
            "FILE_WRITE",
            "FILE_DELETE",
            "WORKTREE_CHECKPOINT",
        }
        if not mutation_write:
            return None

        from rig_relay.coordination.patch_proposal import PatchProposal
        from rig_relay.coordination.patch_workflow import PatchWorkflowStore

        store = PatchWorkflowStore(
            self._workspace_root / ".rig" / "relay" / "coordination"
        )

        proposal = PatchProposal(
            proposal_id=f"prop-{tool_call.call_id}",
            mission_id=self._session_id,
            agent_id=self._agent_profile.name,
            title=f"Proposed {tool_call.tool_name}",
            summary=(
                f"Agent '{self._agent_profile.name}' proposes a {tool_call.tool_name} "
                f"operation on {getattr(tool_call.validated_args, 'path', 'unknown')}"
            ),
            touched_paths=getattr(tool_call.validated_args, "path", [])
            if hasattr(tool_call.validated_args, "path")
            else [],
        )
        store.save_proposal(proposal)

        return ToolResultEvent(
            tool_name=tool_call.tool_name,
            tool_class=tool_call.tool_class,
            skipped=True,
            skip_reason=(
                f"Patch proposal created: {proposal.proposal_id}. "
                f"Approve in Rig Relay before mutation is applied."
            ),
            tool_call_id=tool_call.call_id,
        )


# ── Legacy mixin (kept for MRO compatibility during migration) ──


class PatchGatingMixin:
    """[DEPRECATED] Replaced by PatchGatingService.

    Kept only for AgentLoop MRO compatibility during migration.
    """

    def _check_patch_proposal_gating(
        self, tool_call: object, tool_instance: object
    ) -> ToolResultEvent | None:
        raise NotImplementedError(
            "PatchGatingMixin._check_patch_proposal_gating is deprecated. "
            "Use PatchGatingService.check() instead."
        )
