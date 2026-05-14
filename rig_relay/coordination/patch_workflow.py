from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from rig_relay.coordination.patch_proposal import PatchDecision, PatchProposal

_DECISIONS_DIR = ".fleet/patch-decisions"
_PROPOSALS_DIR = ".fleet/patch-proposals"


class PatchWorkflowError(Exception):
    pass


class PatchProposalNotFoundError(PatchWorkflowError):
    pass


class PatchProposalStateError(PatchWorkflowError):
    pass


class PatchWorkflowStore:
    def __init__(self, coordination_root: Path) -> None:
        self._root = coordination_root

    def proposal_path(self, proposal_id: str) -> Path:
        return self._root / _PROPOSALS_DIR / f"{proposal_id}.json"

    def decision_path(self, decision_id: str) -> Path:
        return self._root / _DECISIONS_DIR / f"{decision_id}.json"

    def load_proposal(self, proposal_id: str) -> PatchProposal:
        path = self.proposal_path(proposal_id)
        if not path.is_file():
            raise PatchProposalNotFoundError(proposal_id)
        return PatchProposal.model_validate_json(path.read_text(encoding="utf-8"))

    def save_proposal(self, proposal: PatchProposal) -> Path:
        path = self.proposal_path(proposal.proposal_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_decision(self, decision: PatchDecision) -> Path:
        path = self.decision_path(decision.decision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
        return path


def record_patch_decision(
    coordination_root: Path, decision: PatchDecision
) -> tuple[PatchProposal, PatchDecision]:
    store = PatchWorkflowStore(coordination_root)
    proposal = store.load_proposal(decision.proposal_id)
    if proposal.status != "pending":
        raise PatchProposalStateError(
            f"proposal {proposal.proposal_id} is not pending: {proposal.status}"
        )

    next_status = _decision_to_status(decision.decision)
    proposal = proposal.model_copy(update={"status": next_status})
    store.save_proposal(proposal)
    store.save_decision(decision)
    return proposal, decision


def create_patch_decision(
    *,
    proposal_id: str,
    decided_by: str,
    decision: Literal["accepted", "rejected", "needs_revision", "superseded"],
    reason: str,
    decision_id: str | None = None,
) -> PatchDecision:
    return PatchDecision(
        decision_id=decision_id
        or f"dec-{proposal_id}-{datetime.now(UTC).timestamp():.0f}",
        proposal_id=proposal_id,
        decided_by=decided_by,
        decision=decision,
        reason=reason,
    )


def _decision_to_status(decision: str) -> str:
    match decision:
        case "accepted":
            return "accepted"
        case "rejected":
            return "rejected"
        case "needs_revision":
            return "needs_revision"
        case "superseded":
            return "superseded"
        case _:
            raise PatchWorkflowError(f"unknown decision: {decision}")


__all__ = [
    "PatchProposalNotFoundError",
    "PatchProposalStateError",
    "PatchWorkflowError",
    "PatchWorkflowStore",
    "create_patch_decision",
    "record_patch_decision",
]
