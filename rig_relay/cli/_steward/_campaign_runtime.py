"""Persistent campaign runtime state and append-only ledgers.

Manages campaign execution state beneath the authority directory:
.rig/relay/campaigns/<campaign-id>/
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.cli._steward._campaign_models import (
    CampaignState,
    build_campaign_state_dir,
)


def init_campaign_dir(campaign_id: str, root: Path) -> Path:
    """Create and return the campaign state directory."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_campaign_state(campaign_id: str, root: Path) -> CampaignState | None:
    """Load the campaign state projection from disk.

    Returns None if no state file exists.
    """
    state_path = (
        build_campaign_state_dir(campaign_id, root) / "state_projection.v1.json"
    )
    if not state_path.exists():
        return None
    return CampaignState.model_validate(json.loads(state_path.read_text()))


def save_campaign_state(state: CampaignState, campaign_id: str, root: Path) -> None:
    """Save the campaign state projection to disk."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state_projection.v1.json"
    state_path.write_text(json.dumps(state.model_dump(), indent=2))


def append_event(campaign_id: str, root: Path, event: dict[str, Any]) -> None:
    """Append a content-light event to the campaign event ledger."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = state_dir / "events.v1.jsonl"
    with open(ledger_path, "a") as f:
        f.write(json.dumps(event) + "\n")


def append_finding(campaign_id: str, root: Path, finding: dict[str, Any]) -> None:
    """Append a structured finding to the campaign findings ledger."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    findings_path = state_dir / "findings.v1.jsonl"
    with open(findings_path, "a") as f:
        f.write(json.dumps(finding) + "\n")


def append_checkpoint_receipt(
    campaign_id: str, root: Path, receipt: dict[str, Any]
) -> None:
    """Append a checkpoint receipt to the checkpoint ledger."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = state_dir / "checkpoint_receipts.v1.jsonl"
    with open(ledger_path, "a") as f:
        f.write(json.dumps(receipt) + "\n")


def append_push_receipt(campaign_id: str, root: Path, receipt: dict[str, Any]) -> None:
    """Append a push receipt to the push ledger."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = state_dir / "private_push_receipts.v1.jsonl"
    with open(ledger_path, "a") as f:
        f.write(json.dumps(receipt) + "\n")


def save_completion_packet(
    campaign_id: str, root: Path, packet: dict[str, Any]
) -> None:
    """Save the completion packet to disk."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    packet_path = state_dir / "completion.v1.json"
    packet_path.write_text(json.dumps(packet, indent=2))
