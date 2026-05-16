"""Patch proposal gating mixin for AgentLoop.

Extracted from agent_loop.py. Provides _check_patch_proposal_gating,
which intercepts mutation tools when the agent profile has
patch_proposal_mode=True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rig_relay.core.types import ToolResultEvent

if TYPE_CHECKING:
    from rig_relay.core.llm.format import ResolvedToolCall
    from rig_relay.core.tools.base import BaseTool


class PatchGatingMixin:
    """Mixin providing patch proposal gating for mutation tools."""

    def _check_patch_proposal_gating(
        self,
        tool_call: ResolvedToolCall,
        tool_instance: BaseTool,
    ) -> ToolResultEvent | None:
        """Gate mutation tools when agent profile has patch_proposal_mode=True.

        When patch_proposal_mode is active, write/delete/checkpoint tools
        produce a PatchProposal receipt instead of executing directly.
        The user must approve the proposal before the workspace is mutated.
        """
        if not self.agent_profile.patch_proposal_mode:
            return None

        mutation_cls = getattr(tool_instance, "mutation_class", None)
        if mutation_cls is None:
            return None

        mutation_str = str(mutation_cls.value)
        mutation_write = mutation_str in {
            "FILE_WRITE", "FILE_DELETE", "WORKTREE_CHECKPOINT",
        }
        if not mutation_write:
            return None

        from rig_relay.coordination.patch_proposal import PatchProposal
        from rig_relay.coordination.patch_workflow import PatchWorkflowStore

        store = PatchWorkflowStore(self._workspace_root / ".rig" / "relay" / "coordination")

        proposal = PatchProposal(
            proposal_id=f"prop-{tool_call.call_id}",
            mission_id=self.session_id,
            agent_id=self.agent_profile.name,
            title=f"Proposed {tool_call.tool_name}",
            summary=(
                f"Agent '{self.agent_profile.name}' proposes a {tool_call.tool_name} "
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
