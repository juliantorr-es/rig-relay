"""Local mutation payload custody for proposals.

Implements durable local-only custody for mutation instructions
required to apply an admitted proposal. Payloads are bound to
proposal identity, excluded from content-light ledgers, provider
context, checkpoints, and push artifacts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class MutationPayloadRecord(BaseModel):
    """A local-only mutation payload bound to a proposal.

    Stored under the campaign authority root, excluded from
    content-light ledgers, checkpoints, and remote push artifacts.

    The payload contains the minimum mutation instructions needed
    to reproduce/apply the proposed edit (SEARCH/REPLACE blocks or
    exact local patch body).

    Contains actual mutation content — MUST NOT appear in event
    ledgers, telemetry, provider context, public render, or
    completion packets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.mutation_payload_custody.v1"
    payload_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    before_sha256: str = Field(min_length=1)
    candidate_after_sha256: str = Field(min_length=1)
    mutation_content: str = Field(min_length=1)
    content_format: str = Field(default="search_replace_blocks")
    payload_sha256: str = Field(min_length=1)


def compute_payload_sha256(mutation_content: str) -> str:
    return hashlib.sha256(mutation_content.encode("utf-8")).hexdigest()


def build_payload_dir(campaign_id: str, root: Path) -> Path:
    return root / ".rig" / "relay" / "campaigns" / campaign_id / "mutation_payloads"


def save_payload(record: MutationPayloadRecord, root: Path) -> Path:
    payload_dir = build_payload_dir(record.campaign_id, root)
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = payload_dir / f"{record.payload_id}.payload.v1.json"
    payload_path.write_text(record.model_dump_json(indent=2))
    return payload_path


def load_payload(
    payload_id: str, campaign_id: str, root: Path
) -> MutationPayloadRecord | None:
    payload_dir = build_payload_dir(campaign_id, root)
    payload_path = payload_dir / f"{payload_id}.payload.v1.json"
    if not payload_path.exists():
        return None
    return MutationPayloadRecord.model_validate_json(payload_path.read_text())


def verify_payload_binding(record: MutationPayloadRecord) -> bool:
    """Verify the payload's SHA-256 matches its mutation content."""
    return record.payload_sha256 == compute_payload_sha256(record.mutation_content)


def delete_payload(payload_id: str, campaign_id: str, root: Path) -> bool:
    """Delete a payload after successful apply. Returns True if deleted."""
    payload_path = (
        build_payload_dir(campaign_id, root) / f"{payload_id}.payload.v1.json"
    )
    if payload_path.exists():
        payload_path.unlink()
        return True
    return False
