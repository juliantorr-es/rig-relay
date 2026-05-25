"""Content-light apply receipt for proposal-based mutations.

Records the durable evidence that an admitted proposal was lawfully
applied under active campaign authority. Consumed by checkpoint
authorization.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationApplyReceipt(BaseModel):
    """Content-light receipt for a lawfully applied mutation.

    Carries only identities, hashes, status, and metadata.
    Never raw source, payload content, SEARCH/REPLACE blocks, or patch body.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.mutation_apply_receipt.v1"
    receipt_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    admission_decision_id: str = Field(min_length=1)
    canonical_path: str = Field(min_length=1)
    before_sha256: str = Field(min_length=1)
    candidate_after_sha256: str = Field(min_length=1)
    actual_after_sha256: str = Field(min_length=1)
    payload_sha256: str = Field(min_length=1)
    apply_status: Literal["applied", "recovered"] = "applied"
    apply_sequence: int = Field(ge=0)
    event_identity: str = ""
    event_ledger_ref: str = ""
    content_light_marker: Literal[True] = True
    recorded_at: str = Field(default_factory=lambda: str(int(time.time())))


def compute_apply_event_identity(
    *,
    campaign_id: str,
    mission_id: str,
    proposal_id: str,
    admission_decision_id: str,
    canonical_path: str,
    actual_after_sha256: str,
) -> str:
    """Compute a stable event identity for an authoritative apply event.

    Excludes ``apply_status`` — ``applied`` and ``recovered``
    observations of the same mutation produce the same identity.
    Binds only the fields that constitute the authoritative event:
    campaign, mission, proposal, admission, path, and resulting hash.
    """
    raw = json.dumps(
        {
            "schema": "rig.relay.mutation_apply_event_identity.v1",
            "campaign_id": campaign_id,
            "mission_id": mission_id,
            "proposal_id": proposal_id,
            "admission_decision_id": admission_decision_id,
            "canonical_path": canonical_path,
            "actual_after_sha256": actual_after_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_apply_receipt(
    campaign_id: str,
    mission_id: str,
    proposal_id: str,
    admission_decision_id: str,
    canonical_path: str,
    before_sha256: str,
    candidate_after_sha256: str,
    actual_after_sha256: str,
    payload_sha256: str,
    apply_sequence: int = 0,
) -> MutationApplyReceipt:
    receipt_id = hashlib.sha256(
        json.dumps(
            {
                "campaign": campaign_id,
                "mission": mission_id,
                "proposal": proposal_id,
                "admission": admission_decision_id,
                "path": canonical_path,
                "actual_after": actual_after_sha256,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return MutationApplyReceipt(
        receipt_id=receipt_id,
        campaign_id=campaign_id,
        mission_id=mission_id,
        proposal_id=proposal_id,
        admission_decision_id=admission_decision_id,
        canonical_path=canonical_path,
        before_sha256=before_sha256,
        candidate_after_sha256=candidate_after_sha256,
        actual_after_sha256=actual_after_sha256,
        payload_sha256=payload_sha256,
        apply_sequence=apply_sequence,
        event_identity=compute_apply_event_identity(
            campaign_id=campaign_id,
            mission_id=mission_id,
            proposal_id=proposal_id,
            admission_decision_id=admission_decision_id,
            canonical_path=canonical_path,
            actual_after_sha256=actual_after_sha256,
        ),
    )


def save_apply_receipt(
    receipt: MutationApplyReceipt, campaign_id: str, root: Path
) -> Path:
    apply_dir = root / ".rig" / "relay" / "campaigns" / campaign_id / "apply_receipts"
    apply_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = apply_dir / f"{receipt.receipt_id}.json"
    receipt_path.write_text(receipt.model_dump_json(indent=2))
    return receipt_path


def load_apply_receipt(
    receipt_id: str, campaign_id: str, root: Path
) -> MutationApplyReceipt | None:
    receipt_path = (
        root
        / ".rig"
        / "relay"
        / "campaigns"
        / campaign_id
        / "apply_receipts"
        / f"{receipt_id}.json"
    )
    if not receipt_path.exists():
        return None
    return MutationApplyReceipt.model_validate_json(receipt_path.read_text())
