"""Governed apply gate for admitted proposals.

Applies only an admitted proposal with valid payload custody,
verifying workspace freshness and policy authority before mutation.
Supports interruption recovery: distinguishes pending/applying/applied
and recovers from hash state after crash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.cli._steward._mutation_payload import (
    MutationPayloadRecord,
    delete_payload,
    verify_payload_binding,
)
from rig_relay.cli._steward._proposal_admission import ProposalAdmissionDecision
from rig_relay.core.tools.builtins.search_replace import SearchReplace

ApplyStatus = Literal[
    "pending", "applying", "applied", "recovered", "refused", "stale", "divergent"
]


class ApplyResult(BaseModel):
    """Content-light apply result. No raw source or payload content."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.proposal_apply_result.v1"
    proposal_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    status: str = Field(min_length=1)
    applied_blocks: int = 0
    applied_bytes: int = 0
    before_sha256: str = ""
    after_sha256: str = ""
    refusal_reason: str | None = None
    payload_deleted: bool = False
    recovered: bool = False


_APPLY_STATE_FILE = "apply_state.json"


def _save_apply_state(
    campaign_id: str, proposal_id: str, status: str, root: Path
) -> None:
    state_dir = root / ".rig" / "relay" / "campaigns" / campaign_id / "apply_states"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{proposal_id}.json"
    state_path.write_text(
        json.dumps({
            "proposal_id": proposal_id,
            "status": status,
            "timestamp": int(time.time()),
        })
    )


def _load_apply_state(campaign_id: str, proposal_id: str, root: Path) -> str | None:
    state_path = (
        root
        / ".rig"
        / "relay"
        / "campaigns"
        / campaign_id
        / "apply_states"
        / f"{proposal_id}.json"
    )
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text())
        return data.get("status")
    except (json.JSONDecodeError, KeyError):
        return None


def apply_admitted_proposal(
    decision: ProposalAdmissionDecision,
    payload: MutationPayloadRecord,
    current_file_bytes: bytes,
    file_path: Path,
    campaign_id: str,
    root: Path,
) -> ApplyResult:
    """Apply an admitted proposal to the workspace.

    Verifies admission, payload binding, workspace freshness, and
    applies the exact verified candidate. Supports recovery from
    interrupted writes via hash-based state detection.
    """
    if decision.admission_status != "admitted":
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="refused",
            refusal_reason=f"proposal not admitted (status: {decision.admission_status})",
        )

    if not verify_payload_binding(payload):
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="refused",
            refusal_reason="payload_binding_invalid",
        )

    current_hash = hashlib.sha256(current_file_bytes).hexdigest()

    # ---- Recovery check: has the write already landed? ----
    if current_hash == decision.candidate_after_sha256:
        delete_payload(payload.payload_id, campaign_id, root)
        _save_apply_state(campaign_id, decision.proposal_id, "applied", root)
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="recovered",
            before_sha256=decision.before_sha256,
            after_sha256=current_hash,
            applied_bytes=len(current_file_bytes),
            payload_deleted=True,
            recovered=True,
        )

    # ---- Recovery check: is workspace in divergent state? ----
    if current_hash != decision.before_sha256:
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="divergent",
            before_sha256=current_hash,
            refusal_reason=f"workspace_hash_neither_before_nor_candidate: expected before "
            f"{decision.before_sha256[:16]}, got {current_hash[:16]}",
        )

    # ---- Transition to applying ----
    _save_apply_state(campaign_id, decision.proposal_id, "applying", root)

    # Parse, apply, and verify
    pre_check = _apply_decision_payload(
        decision, payload, current_file_bytes, file_path
    )
    if isinstance(pre_check, ApplyResult):
        _save_apply_state(campaign_id, decision.proposal_id, "refused", root)
        return pre_check

    modified_bytes, result = pre_check
    file_path.write_text(modified_bytes.decode("utf-8"), encoding="utf-8")
    deleted = delete_payload(payload.payload_id, campaign_id, root)

    after_hash = hashlib.sha256(modified_bytes).hexdigest()
    _save_apply_state(campaign_id, decision.proposal_id, "applied", root)

    return ApplyResult(
        proposal_id=decision.proposal_id,
        decision_id=decision.decision_id,
        file_path=str(file_path),
        status="applied",
        applied_blocks=result.applied,
        applied_bytes=len(modified_bytes),
        before_sha256=current_hash,
        after_sha256=after_hash,
        payload_deleted=deleted,
    )


def recover_apply_result(
    decision: ProposalAdmissionDecision, campaign_id: str, root: Path, file_path: Path
) -> ApplyResult | None:
    """Recover apply state after interruption.

    Returns an ApplyResult if recovery state exists, None otherwise.
    """
    state = _load_apply_state(campaign_id, decision.proposal_id, root)
    if state is None:
        return None

    current_bytes = file_path.read_bytes() if file_path.exists() else b""
    current_hash = hashlib.sha256(current_bytes).hexdigest()

    if state == "applied":
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="recovered",
            before_sha256=decision.before_sha256,
            after_sha256=current_hash,
            applied_bytes=len(current_bytes),
            recovered=True,
        )
    if state == "applying":
        if current_hash == decision.candidate_after_sha256:
            _save_apply_state(campaign_id, decision.proposal_id, "applied", root)
            return ApplyResult(
                proposal_id=decision.proposal_id,
                decision_id=decision.decision_id,
                file_path=str(file_path),
                status="recovered",
                before_sha256=decision.before_sha256,
                after_sha256=current_hash,
                applied_bytes=len(current_bytes),
                recovered=True,
            )
        return None  # applying but write didn't land — caller should retry
    return None


def _apply_decision_payload(
    decision: ProposalAdmissionDecision,
    payload: MutationPayloadRecord,
    current_file_bytes: bytes,
    file_path: Path,
) -> ApplyResult | tuple[bytes, object]:
    try:
        candidate_text, result = SearchReplace.recompute_candidate(
            payload.mutation_content, current_file_bytes.decode("utf-8"), file_path
        )
    except ValueError as e:
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="refused",
            refusal_reason=f"payload_parse_failed: {e}",
        )
    if result.errors:
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="refused",
            refusal_reason=f"blocks_failed: {'; '.join(result.errors)}",
        )
    modified_bytes = candidate_text.encode("utf-8")
    after_hash = hashlib.sha256(modified_bytes).hexdigest()
    if after_hash != decision.candidate_after_sha256:
        return ApplyResult(
            proposal_id=decision.proposal_id,
            decision_id=decision.decision_id,
            file_path=str(file_path),
            status="refused",
            before_sha256=hashlib.sha256(current_file_bytes).hexdigest(),
            after_sha256=after_hash,
            refusal_reason=f"candidate_hash_mismatch: expected "
            f"{decision.candidate_after_sha256[:16]}, got {after_hash[:16]}",
        )
    return (modified_bytes, result)
