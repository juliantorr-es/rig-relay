"""Proposal admission model and decision gate.

Evaluates whether a computed proposal is within the active campaign
mission or repair scope, produces a content-light admission decision,
and routes security/confidentiality refusals through the accepted
campaign halt policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_registry import (
    PathClassificationRegistry,
    is_write_allowed,
)
from rig_relay.cli._steward._canonical_path import resolve_canonical_identity
from rig_relay.cli._steward._mutation_payload import (
    MutationPayloadRecord,
    verify_payload_binding,
)
from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.core.tools.builtins.search_replace import SearchReplaceProposalResult

AdmissionStatus = Literal[
    "admitted", "refused", "stale", "expired", "applied", "apply_failed"
]


AdmissionReasonCode = Literal[
    "admitted_for_apply",
    "proposal_not_pending",
    "campaign_not_active",
    "registry_classification_denies_write",
    "path_not_in_mission_scope",
    "payload_binding_invalid",
    "payload_proposal_mismatch",
    "payload_campaign_mismatch",
    "payload_mission_mismatch",
    "baseline_hash_mismatch",
    "missing_candidate_hash",
]


@dataclass(frozen=True)
class _AdmissionRefusal:
    status: AdmissionStatus
    reason_code: AdmissionReasonCode
    before_sha256: str | None = None
    payload_sha256: str | None = None


class ProposalAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.proposal_admission_decision.v1"
    decision_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    admission_status: AdmissionStatus
    authority_source: str = Field(default="campaign_runtime_admission_gate")
    reason_code: str = Field(min_length=1)
    refusal_reason: str | None = None
    before_sha256: str = ""
    candidate_after_sha256: str = ""
    payload_sha256: str = ""
    registry_digest: str = ""
    issued_at: str = Field(default_factory=lambda: str(int(time.time())))
    content_light_marker: Literal[True] = True


def _mk(
    proposal_id: str,
    campaign_id: str,
    mission_id: str,
    file_path: str,
    status: AdmissionStatus,
    reason: str,
    *,
    before_sha256: str = "",
    candidate_after_sha256: str = "",
    payload_sha256: str = "",
) -> ProposalAdmissionDecision:
    did = hashlib.sha256(
        json.dumps(
            {"p": proposal_id, "c": campaign_id, "s": status, "t": int(time.time())},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return ProposalAdmissionDecision(
        decision_id=did,
        proposal_id=proposal_id,
        campaign_id=campaign_id,
        mission_id=mission_id,
        file_path=file_path,
        admission_status=status,
        reason_code=reason,
        content_light_marker=True,
        before_sha256=before_sha256,
        candidate_after_sha256=candidate_after_sha256,
        payload_sha256=payload_sha256,
    )


# ---- Private gate evaluators -----------------------------------------


def _validate_proposal_pending(proposal: PatchProposal) -> _AdmissionRefusal | None:
    if proposal.status == "pending":
        return None
    return _AdmissionRefusal("refused", "proposal_not_pending")


def _validate_campaign_active(state: CampaignState) -> _AdmissionRefusal | None:
    if state.phase in {"running", "resolver_active", "repair_active"}:
        return None
    return _AdmissionRefusal("refused", "campaign_not_active")


def _validate_registry_and_scope(
    registry: PathClassificationRegistry, canonical: str, mission: MissionDefinition
) -> _AdmissionRefusal | None:
    if not is_write_allowed(registry, canonical):
        return _AdmissionRefusal("refused", "registry_classification_denies_write")
    if canonical not in frozenset(mission.owned_path_scope):
        return _AdmissionRefusal("refused", "path_not_in_mission_scope")
    return None


def _validate_payload_binding_refusal(
    payload: MutationPayloadRecord,
    proposal: PatchProposal,
    campaign_id: str,
    mission_id: str,
) -> _AdmissionRefusal | None:
    if not verify_payload_binding(payload):
        return _AdmissionRefusal("refused", "payload_binding_invalid")
    if payload.proposal_id != proposal.proposal_id:
        return _AdmissionRefusal("refused", "payload_proposal_mismatch")
    if payload.campaign_id != campaign_id:
        return _AdmissionRefusal("refused", "payload_campaign_mismatch")
    if payload.mission_id != mission_id:
        return _AdmissionRefusal("refused", "payload_mission_mismatch")
    return None


def _validate_hash_chain(
    current_hash: str, p_before: str, p_after: str, payload: MutationPayloadRecord
) -> _AdmissionRefusal | None:
    if current_hash != p_before:
        return _AdmissionRefusal(
            "stale",
            "baseline_hash_mismatch",
            before_sha256=p_before,
            payload_sha256=payload.payload_sha256,
        )
    if not p_after:
        return _AdmissionRefusal(
            "refused",
            "missing_candidate_hash",
            before_sha256=p_before,
            payload_sha256=payload.payload_sha256,
        )
    return None


# ---- Public admission gate -------------------------------------------


def admit_patch_proposal(
    proposal: PatchProposal,
    proposal_result: SearchReplaceProposalResult,
    state: CampaignState,
    manifest: CampaignManifest,
    mission: MissionDefinition,
    registry: PathClassificationRegistry,
    payload: MutationPayloadRecord,
    current_file_bytes: bytes,
    repo_root: Path,
) -> ProposalAdmissionDecision:
    pid = proposal.proposal_id
    cid = state.campaign_id
    mid = mission.mission_id
    op_path = proposal_result.file
    path_obj = (
        (repo_root / op_path).resolve()
        if not Path(op_path).is_absolute()
        else Path(op_path).resolve()
    )
    canonical = resolve_canonical_identity(path_obj, repo_root)
    current_hash = hashlib.sha256(current_file_bytes).hexdigest()

    bm = proposal_result.before_file_sha256
    p_before = list(bm.values())[0].replace("sha256:", "") if bm else ""
    am = proposal_result.after_file_sha256
    p_after = list(am.values())[0].replace("sha256:", "") if am else ""

    gates = [
        lambda: _validate_proposal_pending(proposal),
        lambda: _validate_campaign_active(state),
        lambda: _validate_registry_and_scope(registry, canonical, mission),
        lambda: _validate_payload_binding_refusal(payload, proposal, cid, mid),
        lambda: _validate_hash_chain(current_hash, p_before, p_after, payload),
    ]

    for gate in gates:
        refusal = gate()
        if refusal is not None:
            return _mk(
                pid,
                cid,
                mid,
                canonical,
                refusal.status,
                refusal.reason_code,
                before_sha256=refusal.before_sha256 or "",
                payload_sha256=refusal.payload_sha256 or "",
            )

    return _mk(
        pid,
        cid,
        mid,
        canonical,
        "admitted",
        "admitted_for_apply",
        before_sha256=p_before,
        candidate_after_sha256=p_after,
        payload_sha256=payload.payload_sha256,
    )
