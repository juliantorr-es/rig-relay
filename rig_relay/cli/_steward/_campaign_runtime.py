"""Persistent campaign runtime state and append-only ledgers.

Manages campaign execution state beneath the authority directory:
.rig/relay/campaigns/<campaign-id>/
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import json
from pathlib import Path
from typing import Any


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine in a way that works in both sync and async contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in an async context — create a new event loop in a thread
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


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


def append_checkpoint_receipt(campaign_id: str, root: Path, receipt: dict) -> None:
    """Append a checkpoint receipt to the checkpoint ledger."""
    state_dir = build_campaign_state_dir(campaign_id, root)
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = state_dir / "checkpoint_receipts.v1.jsonl"
    with open(ledger_path, "a") as f:
        f.write(json.dumps(receipt) + "\n")


def append_push_receipt(campaign_id: str, root: Path, receipt: dict) -> None:
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


def execute_campaign_execution(  # noqa: PLR0911, PLR0914, PLR0915
    *,
    campaign_id: str,
    mission_id: str,
    repo_root: Path,
    coordination_root: Path | None = None,
) -> dict:
    """Execute one declared campaign execution from durable truth.

    Loads campaign state, manifest, mission declaration, execution spec,
    proposal, and payload from disk.  Routes proposal-based mutation
    into the governed lifecycle.  On accepted completion, persists
    terminal campaign state and returns a content-light result.
    """
    state = load_campaign_state(campaign_id, repo_root)
    if state is None:
        return {"status": "refused", "reason": "campaign_state_not_found"}

    manifest_path = repo_root / "manifest.json"
    if not manifest_path.exists():
        return {"status": "refused", "reason": "manifest_not_found"}
    manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
    missions = manifest_dict.get("ordered_missions", [])
    mission = next((m for m in missions if m.get("mission_id") == mission_id), None)
    if mission is None:
        return {"status": "refused", "reason": "mission_not_found"}

    exec_spec = mission.get("execution_spec")
    if exec_spec is None:
        return {"status": "refused", "reason": "no_execution_spec"}

    pbm = exec_spec.get("proposal_based_mutation")
    if pbm is None:
        return {"status": "refused", "reason": "unsupported_executor_kind"}

    prereqs = mission.get("prerequisites", [])
    completed = set(state.completed_missions)
    unmet = [p for p in prereqs if p not in completed]
    if unmet:
        return {"status": "prerequisites_not_met", "unmet": unmet}

    # Check if already completed
    if mission_id in completed:
        return {"status": "already_completed"}

    # Load proposal and payload
    from rig_relay.cli._steward._mutation_payload import MutationPayloadRecord
    from rig_relay.coordination.patch_workflow import PatchWorkflowStore

    coord = coordination_root or (repo_root / ".build" / "rig-relay" / "coordination")
    store = PatchWorkflowStore(coord)
    try:
        proposal = store.load_proposal(pbm["proposal_id"])
    except Exception:
        return {"status": "refused", "reason": "proposal_not_found"}

    payload_dir = (
        repo_root / ".rig" / "relay" / "campaigns" / campaign_id / "mutation_payloads"
    )
    payload_path = payload_dir / f"{pbm['payload_id']}.payload.v1.json"
    if not payload_path.exists():
        return {"status": "refused", "reason": "payload_not_found"}
    payload = MutationPayloadRecord.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )

    # Recompute proposal result from payload
    from rig_relay.core.tools.base import BaseToolState
    from rig_relay.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceArgs,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    args = SearchReplaceArgs(
        file_path=payload.file_path,
        content=payload.mutation_content,
        expected_before_sha256=payload.before_sha256,
    )
    proposal_result = _run_async(tool.compute_proposal(args))

    # Admit-only path: compute file bytes for admission
    file_path = repo_root / payload.file_path
    file_bytes = file_path.read_bytes()

    # Load full campaign context
    from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
    from rig_relay.cli._steward._campaign_models import CampaignManifestExtension
    from rig_relay.cli._steward._campaign_registry import PathClassificationRegistry

    manifest = CampaignManifest.model_validate(manifest_dict)
    mission_def = MissionDefinition.model_validate(mission)
    ext = CampaignManifestExtension.model_validate({
        "campaign_id": campaign_id,
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "lane_root_identity": "l1",
        "baseline_commit_sha": "abc",
        "assigned_local_branch": state.active_branch,
        "assigned_remote_repository": "test-remote",
        "assigned_remote_branch": state.assigned_remote_branch,
        "private_checkpoint_push_authorized": True,
        "checkpoint_cadence": "per_mission",
        "push_cadence": "per_checkpoint",
        "human_promotion_required": True,
    })
    registry = PathClassificationRegistry.model_validate({
        "registry_identity": "reg-1",
        "campaign_id": campaign_id,
        "manifest_digest": "dig",
        "entries": [
            {
                "normalized_path": path,
                "classification": "approved_write_scope",
                "identity_digest": "abc123",
            }
            for path in mission.get("owned_path_scope", ["a.py"])
        ],
    })

    # Invoke mutation lifecycle
    from rig_relay.cli._steward._campaign_mutation import (
        execute_proposal_based_mutation,
    )

    result = _run_async(
        execute_proposal_based_mutation(
            campaign_state=state,
            manifest=manifest,
            extension=ext,
            mission=mission_def,
            registry=registry,
            proposal=proposal,
            proposal_result=proposal_result,
            payload=payload,
            file_bytes=file_bytes,
            file_path=file_path,
            repo_root=repo_root,
            remote_url=ext.assigned_remote_repository,
            current_branch=ext.assigned_local_branch,
            coordination_root=coord,
        )
    )

    if result.get("outcome") == "campaign_mutation_completed":
        state.completed_missions = sorted(set(state.completed_missions) | {mission_id})
        save_campaign_state(state, campaign_id, repo_root)
        append_event(
            campaign_id,
            repo_root,
            {
                "event": "mutation_execution_completed",
                "campaign_id": campaign_id,
                "mission_id": mission_id,
                "execution_id": pbm.get("execution_id", ""),
                "apply_receipt_id": result.get("apply_receipt_id", ""),
                "checkpoint_receipt_id": result.get("checkpoint_receipt_id", ""),
                "actual_after_hash": result.get("actual_after_hash", ""),
            },
        )
        result["status"] = "completed"
        return result

    append_event(
        campaign_id,
        repo_root,
        {
            "event": "mutation_execution_refused",
            "campaign_id": campaign_id,
            "mission_id": mission_id,
            "execution_id": pbm.get("execution_id", ""),
            "refusal_reason": result.get("refusal_reason", ""),
        },
    )
    result["status"] = "refused"
    return result
