"""Sealed mode completion packet generation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rig_relay.cli._steward._sealed_mode import SealedWorkspaceMode


class SealedCompletionPacket(BaseModel):
    """Content-light completion packet for sealed mode."""

    model_config = ConfigDict(extra="forbid")

    mode: SealedWorkspaceMode
    lane_id: str
    baseline_digest: str
    approved_path_set_digest: str
    changed_paths: list[str]
    diff_digest: str
    test_result_status: str
    context_egress_receipt_id: str | None
    refusal_counts: dict[str, int]
    
    checkpoint_performed: bool = False
    commit_performed: bool = False
    promotion_performed: bool = False
    push_performed: bool = False
    external_transmission_performed: bool = False
    human_promotion_required: bool = True


def build_completion_packet(
    lane_id: str,
    baseline_digest: str,
    approved_path_set_digest: str,
    changed_paths: list[str],
    diff_digest: str,
    test_result_status: str,
    context_egress_receipt_id: str | None,
    refusal_counts: dict[str, int],
) -> SealedCompletionPacket:
    return SealedCompletionPacket(
        mode=SealedWorkspaceMode(),
        lane_id=lane_id,
        baseline_digest=baseline_digest,
        approved_path_set_digest=approved_path_set_digest,
        changed_paths=changed_paths,
        diff_digest=diff_digest,
        test_result_status=test_result_status,
        context_egress_receipt_id=context_egress_receipt_id,
        refusal_counts=refusal_counts,
    )
