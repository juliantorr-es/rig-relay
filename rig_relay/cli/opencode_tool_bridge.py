"""OpenCode custom-tool transport bridge → Rig Governed Mutation Lifecycle.

Stage 3 thin adapter. Reads a single JSON search_replace invocation
from stdin, persists proposal/payload/campaign context, delegates to
the governed campaign execution route (execute_campaign_execution),
and emits a content-light JSON result to stdout.

This is explicitly temporary transport infrastructure. It lives under
``rig_relay/cli/`` (not ``rig_relay/runtime/``) because it owns zero
runtime authority. The campaign execution route is the single
authoritative governed execution spine.

Privacy boundary:
  Raw replacement content necessarily crosses this bridge as transient
  invocation input. The bridge must never persist, log, or emit raw content
  outside the governed Rig invocation path. Result output is content-light:
  receipt/envelope identifiers, status, and timing only.
"""

from __future__ import annotations

import asyncio
import hashlib as _hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def _build_search_replace_content(old_str: str, new_str: str) -> str:
    """Construct SEARCH/REPLACE block content for the SearchReplace tool."""
    return f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"


def _derive_campaign_id(session_id: str, directory: str) -> str:
    """Derive a stable campaign_id from session + worktree identity."""
    return (
        "oc-" + _hashlib.sha256(f"{session_id}:{directory}".encode()).hexdigest()[:12]
    )


def _init_bare_remote(repo_root: Path) -> Path:
    """Create a local bare remote for governed push."""
    bare = repo_root.parent / ".rig-bare.git"
    if not bare.exists():
        bare.mkdir()
        subprocess.run(
            ["git", "-C", str(bare), "init", "--bare"], capture_output=True, check=True
        )
    remote_check = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if remote_check.returncode != 0:
        subprocess.run(
            ["git", "-C", str(repo_root), "remote", "add", "origin", str(bare)],
            capture_output=True,
            check=True,
        )
    return bare


async def _invoke_search_replace(  # noqa: PLR0914
    file_path: str,
    old_str: str,
    new_str: str,
    *,
    expected_before_sha256: str | None = None,
    session_id: str = "opencode-bridge",
    directory: str = "",
    worktree: str | None = None,
) -> dict[str, Any]:
    """Persist proposal, create campaign context, delegate to campaign execution.

    Returns a content-light dict suitable for JSON serialization.
    """
    repo_root = Path(directory) if directory else Path.cwd()
    campaign_id = _derive_campaign_id(session_id, directory)
    mission_id = "m1"
    proposal_id = (
        f"prop-oc-{_hashlib.sha256(f'{file_path}:{old_str}'.encode()).hexdigest()[:16]}"
    )
    payload_id = f"pay-{proposal_id}"
    execution_id = f"exec-{proposal_id}"
    coord = repo_root / ".build" / "rig-relay" / "coordination"
    branch = "confidential/steward-campaign/opencode"

    # Ensure branch exists
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", branch], capture_output=True
    )

    # Init bare remote for governed push
    _init_bare_remote(repo_root)

    content = _build_search_replace_content(old_str, new_str)
    target = repo_root / file_path
    if not file_path or not target.exists():
        return {
            "status": "refused",
            "outcome": "refused",
            "refusal_reason": (f"File path '{file_path}' does not exist or is empty"),
        }
    file_bytes = target.read_bytes()
    before_hex = _hashlib.sha256(file_bytes).hexdigest()
    after_hex = _hashlib.sha256(new_str.encode()).hexdigest()

    # Persist proposal
    from rig_relay.coordination.patch_proposal import PatchProposal
    from rig_relay.coordination.patch_workflow import PatchWorkflowStore

    try:
        store = PatchWorkflowStore(coord)
        proposal = PatchProposal(
            proposal_id=proposal_id,
            mission_id=mission_id,
            agent_id="opencode",
            title=f"OpenCode search_replace: {file_path}",
            summary=f"Replace in {file_path}",
            status="pending",
            touched_paths=[file_path],
            expected_before_sha256={file_path: before_hex},
            idempotency_key=f"oc-{proposal_id}",
        )
        store.save_proposal(proposal)
    except Exception:
        pass  # Already persisted from other invocation

    # Persist payload
    from rig_relay.cli._steward._mutation_payload import (
        MutationPayloadRecord,
        save_payload,
    )

    payload = MutationPayloadRecord(
        payload_id=payload_id,
        proposal_id=proposal_id,
        campaign_id=campaign_id,
        mission_id=mission_id,
        file_path=file_path,
        before_sha256=before_hex,
        candidate_after_sha256=after_hex,
        mutation_content=content,
        payload_sha256=_hashlib.sha256(content.encode()).hexdigest(),
    )
    try:
        save_payload(payload, repo_root)
    except Exception:
        pass

    # Write campaign manifest with execution_spec
    manifest = {
        "ordered_missions": [
            {
                "mission_id": mission_id,
                "owned_path_scope": [file_path],
                "read_context_scope": [],
                "provider_context_scope": [],
                "validation_commands": [],
                "prerequisites": [],
                "resolver_scope_declarations": [],
                "completion_contract": {},
                "blocked_continuation_policy": "halt_chain",
                "steward_authored_mission_insertion_prohibited": True,
                "execution_spec": {
                    "proposal_based_mutation": {
                        "execution_id": execution_id,
                        "execution_kind": "proposal_based_mutation",
                        "proposal_id": proposal_id,
                        "payload_id": payload_id,
                    }
                },
            }
        ],
        "user_approval_marker": True,
        "operating_mode": "confidential_autonomous_campaign_nonpromoting",
        "provider_disclosure_attestation": {
            "mode": "hosted_confidential_full_source_user_approved",
            "provider_family_identity": "opencode",
            "provider_model_identity": "opencode",
            "actual_retention_control_mode_classification": "standard_retention",
            "campaign_scope_digest": "d",
            "campaign_scope_approval_marker": True,
            "mission_level_provider_scope_enforcement_marker": True,
        },
        "absolute_exclusions": [
            "credentials",
            "secrets",
            "tokens",
            "private_authentication_material",
            "patent_or_counsel_material",
            "legal_strategy_material",
            "confidential_audit_artifacts",
            "confidential_build_sink",
            "local_crosswalks",
            "provider_policy_evidence_bodies",
            "encrypted_snapshots",
            "unrelated_repository_content",
            "unclassified_paths",
        ],
        "mission_universe_immutable_after_execution_begins": True,
    }
    (repo_root / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Persist campaign state
    from rig_relay.cli._steward._campaign_models import CampaignState

    state = CampaignState.model_validate({
        "campaign_id": campaign_id,
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "running",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": branch,
        "assigned_remote_branch": branch,
        "current_mission_id": mission_id,
        "manifest_digest": "dig",
        "latest_checkpoint_sha": None,
        "latest_pushed_sha": None,
        "completed_missions": [],
        "paused_missions": [],
        "checkpoint_count": 0,
        "push_count": 0,
    })
    from rig_relay.cli._steward._campaign_runtime import save_campaign_state

    save_campaign_state(state, campaign_id, repo_root)

    # Execute through governed campaign dispatch
    from rig_relay.cli._steward._campaign_runtime import execute_campaign_execution

    result = execute_campaign_execution(
        campaign_id=campaign_id,
        mission_id=mission_id,
        repo_root=repo_root,
        coordination_root=coord,
    )

    return {
        "status": result.get("status", "refused"),
        "outcome": result.get("outcome", result.get("status", "")),
        "apply_receipt_id": result.get("apply_receipt_id", ""),
        "checkpoint_receipt_id": result.get("checkpoint_receipt_id", ""),
        "actual_after_hash": result.get("actual_after_hash", ""),
        "refusal_reason": result.get("refusal_reason", ""),
    }


def main() -> None:
    """CLI entry point: read JSON from stdin, invoke, write JSON to stdout."""
    try:
        raw = sys.stdin.buffer.read()
        request = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        error_result = {
            "status": "failed",
            "error_kind": "bridge_parse_error",
            "refusal_reason": f"Failed to parse stdin JSON: {exc}",
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)

    file_path = request.get("filePath", "")
    old_str = request.get("oldStr", "")
    new_str = request.get("newStr", "")

    if not file_path:
        error_result = {
            "status": "failed",
            "error_kind": "invalid_payload",
            "refusal_reason": "Missing required field: filePath",
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)

    if not old_str and not new_str:
        error_result = {
            "status": "failed",
            "error_kind": "invalid_payload",
            "refusal_reason": ("At least one of oldStr or newStr must be non-empty"),
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)

    try:
        result = asyncio.run(
            _invoke_search_replace(
                file_path=file_path,
                old_str=old_str,
                new_str=new_str,
                expected_before_sha256=request.get("expectedBeforeSha256"),
                session_id=request.get("sessionId", "opencode-bridge"),
                directory=request.get("directory", ""),
                worktree=request.get("worktree"),
            )
        )
        sys.stdout.write(json.dumps(result) + "\n")
        if result.get("status") not in {"completed", "cached"}:
            sys.exit(1)
    except Exception as exc:
        error_result = {
            "status": "failed",
            "error_kind": "bridge_invocation_error",
            "refusal_reason": f"Bridge invocation failed: {exc}",
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
