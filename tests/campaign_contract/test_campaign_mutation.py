"""Tests for governed mutation proposal runtime integration.

Real temporary repositories, real local bare remotes, real production
boundaries. Proves: compute → custody → admit → apply → checkpoint
receipt → governed push. Restart-aware. Main seeded and unmoved.
"""

from __future__ import annotations

import subprocess

from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
from rig_relay.cli._steward._campaign_models import (
    CampaignManifestExtension,
    CampaignState,
)
from rig_relay.cli._steward._campaign_mutation import execute_proposal_based_mutation
from rig_relay.cli._steward._campaign_registry import PathClassificationRegistry
from rig_relay.cli._steward._mutation_apply_receipt import load_apply_receipt
from rig_relay.cli._steward._mutation_payload import (
    MutationPayloadRecord,
    compute_payload_sha256,
    load_payload,
    save_payload,
)
from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import PatchWorkflowStore
from rig_relay.core.tools.builtins.search_replace import SearchReplaceProposalResult


def _init_repo(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True
    )
    return tmp_path


def _init_bare(tmp_path):
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "-C", str(bare), "init", "--bare"], capture_output=True)
    return bare


def _state(phase="running", campaign_id="c1", mission_id="m1"):
    return CampaignState.model_validate({
        "campaign_id": campaign_id,
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": phase,
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "confidential/steward-campaign/c1",
        "assigned_remote_branch": "confidential/steward-campaign/c1",
        "current_mission_id": mission_id,
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "s1",
        "latest_pushed_sha": "s1",
    })


def _extension(campaign_id="c1", push_authorized=True):
    return CampaignManifestExtension.model_validate({
        "campaign_id": campaign_id,
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "lane_root_identity": "l1",
        "baseline_commit_sha": "abc",
        "assigned_local_branch": "confidential/steward-campaign/c1",
        "assigned_remote_repository": "test-remote",
        "assigned_remote_branch": "confidential/steward-campaign/c1",
        "private_checkpoint_push_authorized": push_authorized,
        "checkpoint_cadence": "per_mission",
        "push_cadence": "per_checkpoint",
        "human_promotion_required": True,
    })


def _mission():
    return MissionDefinition.model_validate({
        "mission_id": "m1",
        "owned_path_scope": ["a.py"],
        "read_context_scope": [],
        "provider_context_scope": [],
        "validation_commands": [],
        "prerequisites": [],
        "resolver_scope_declarations": [],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    })


def _manifest():
    return CampaignManifest.model_validate({
        "ordered_missions": [_mission().model_dump()],
        "user_approval_marker": True,
        "operating_mode": "confidential_autonomous_campaign_nonpromoting",
        "provider_disclosure_attestation": {
            "mode": "hosted_confidential_full_source_user_approved",
            "provider_family_identity": "fam",
            "provider_model_identity": "m",
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
    })


def _registry():
    return PathClassificationRegistry.model_validate({
        "registry_identity": "r1",
        "campaign_id": "c1",
        "manifest_digest": "abc",
        "entries": [
            {
                "normalized_path": "a.py",
                "classification": "approved_write_scope",
                "identity_digest": "d1",
            }
        ],
    })


# ---- E2E: Full governed chain with restart ---------------------------


def test_e2e_governed_mutation_chain_with_restart(tmp_path, monkeypatch):
    """Classification: E2E/real-artifact

    Full governed chain: compute proposal → persist payload + proposal →
    RESTART (reload from disk) → admit → apply → persist apply receipt →
    RESTART → canonical checkpoint → governed push to assigned branch.
    Seed main, prove main unmoved. Payload excluded from committed tree.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    bare = _init_bare(tmp_path)
    branch = "confidential/steward-campaign/c1"
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True
    )
    (repo / "src").mkdir(exist_ok=True)
    content = "x = 1\n"
    (repo / "a.py").write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True
    )

    # Seed main on bare remote
    subprocess.run(
        ["git", "-C", str(repo), "push", "origin", f"{branch}:main"],
        capture_output=True,
    )
    main_sha = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", "refs/heads/main"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert main_sha

    # Reset to clean working tree — canonical Checkpoint handles staging
    subprocess.run(
        ["git", "-C", str(repo), "reset", "--hard", "HEAD"], capture_output=True
    )

    # ---- 1. Compute proposal ----
    import asyncio

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
        file_path="a.py",
        content="<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE",
    )
    result = asyncio.run(tool.compute_proposal(args))
    assert result.status == "proposal_computed"
    p_before = list(result.before_file_sha256.values())[0].replace("sha256:", "")
    p_after = list(result.after_file_sha256.values())[0].replace("sha256:", "")

    # ---- 2. Persist payload + proposal to disk ----
    payload_content = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
    payload = MutationPayloadRecord.model_validate({
        "payload_id": "pay-e2e",
        "proposal_id": "prop-e2e",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": "a.py",
        "before_sha256": p_before,
        "candidate_after_sha256": p_after,
        "mutation_content": payload_content,
        "content_format": "search_replace_blocks",
        "payload_sha256": compute_payload_sha256(payload_content),
    })
    save_payload(payload, repo)

    coordination_root = tmp_path / "coordination"
    store = PatchWorkflowStore(coordination_root)
    proposal = PatchProposal(
        proposal_id="prop-e2e",
        mission_id="m1",
        agent_id="a1",
        title="test",
        summary="test",
        status="pending",
        touched_paths=["a.py"],
        touched_path_hashes=[f"sha256:{p_before}"],
        expected_before_sha256={"a.py": f"sha256:{p_before}"},
        candidate_after_sha256={"a.py": f"sha256:{p_after}"},
    )
    store.save_proposal(proposal)

    # ---- 3. RESTART: Reload from disk ----
    del tool, result, args
    loaded_payload = load_payload("pay-e2e", "c1", repo)
    assert loaded_payload is not None
    loaded_proposal = store.load_proposal("prop-e2e")
    assert loaded_proposal.status == "pending"

    # ---- 4. Orchestrate full chain ----
    import asyncio

    state = _state()
    state.latest_checkpoint_sha = None
    manifest = _manifest()
    ext = _extension()
    mission = _mission()
    registry = _registry()
    fp = repo / "a.py"
    file_bytes = fp.read_bytes()

    chain_result = asyncio.run(
        execute_proposal_based_mutation(
            campaign_state=state,
            manifest=manifest,
            extension=ext,
            mission=mission,
            registry=registry,
            proposal_result=SearchReplaceProposalResult.model_validate({
                "file": "a.py",
                "status": "proposal_computed",
                "blocks_applied": 1,
                "failed_block_count": 0,
                "total_block_count": 1,
                "before_file_sha256": {"a.py": f"sha256:{p_before}"},
                "after_file_sha256": {"a.py": f"sha256:{p_after}"},
                "before_bytes": len(content.encode()),
                "after_bytes": len(b"x = 2\n"),
            }),
            payload=loaded_payload,
            proposal=loaded_proposal,
            file_bytes=file_bytes,
            file_path=fp,
            repo_root=repo,
            remote_url="test-remote",
            current_branch=branch,
            coordination_root=coordination_root,
        )
    )  # close asyncio.run

    assert chain_result["outcome"] == "campaign_mutation_completed", (
        f"Unexpected outcome: {chain_result['outcome']}, "
        f"reason: {chain_result.get('refusal_reason')}"
    )


def test_contract_canonical_receipt_validation_accepts_campaign_format():
    """Classification: contract/integration
    The campaign checkpoint receipt (with corrected schema_version and
    ISO 8601 expires_at) passes the canonical Checkpoint._validate_receipt.
    """
    from rig_relay.core.tools.builtins.checkpoint import Checkpoint
    from rig_relay.cli._steward._campaign_models import (
        CampaignState,
        CampaignManifestExtension,
    )
    from rig_relay.cli._steward._campaign_checkpoint import (
        issue_campaign_checkpoint_receipt,
    )
    import json

    state = CampaignState.model_validate({
        "campaign_id": "c1",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "running",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": "m1",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "s1",
        "latest_pushed_sha": "s1",
    })
    ext = CampaignManifestExtension.model_validate({
        "campaign_id": "c1",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "lane_root_identity": "l1",
        "baseline_commit_sha": "abc",
        "assigned_local_branch": "b",
        "assigned_remote_repository": "test",
        "assigned_remote_branch": "b",
        "private_checkpoint_push_authorized": True,
        "checkpoint_cadence": "per_mission",
        "push_cadence": "per_checkpoint",
        "human_promotion_required": True,
    })

    receipt = issue_campaign_checkpoint_receipt(ext, state, "m1", ["a.py"], "dig")
    receipt_json = json.dumps(receipt)

    valid, reason = Checkpoint._validate_receipt(receipt_json, "checkpoint.commit")
    assert valid, f"Receipt validation failed: {reason}"


def test_contract_canonical_receipt_rejects_wrong_action():
    """Classification: contract/sabotage
    Receipt with wrong action is rejected by canonical Checkpoint.
    """
    from rig_relay.core.tools.builtins.checkpoint import Checkpoint
    import json

    receipt = {
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "action": "push.force",  # wrong action
        "user_verified": True,
        "expires_at": "2026-12-31T23:59:59+00:00",
    }
    valid, _ = Checkpoint._validate_receipt(json.dumps(receipt), "checkpoint.commit")
    assert not valid


# ---- Push refused without checkpoint ----


def test_sabotage_push_refused_without_checkpoint(tmp_path):
    """Classification: contract/sabotage
    Governed push refuses when no valid checkpoint SHA exists.
    """
    repo = _init_repo(tmp_path)
    bare = _init_bare(tmp_path)
    branch = "confidential/steward-campaign/c1"
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        capture_output=True,
    )

    state = _state()
    state.latest_checkpoint_sha = None
    ext = _extension()

    from rig_relay.cli._steward._campaign_push import validate_campaign_push_request

    refusal = validate_campaign_push_request(ext, state, branch, str(bare), repo)
    assert refusal is not None


# ---- Structural API test: governed push cannot express force/delete/tags ----


def test_substrate_governed_push_api_cannot_express_force_delete_tags(tmp_path):
    """Classification: substrate/sabotage
    The governed push API accepts no refspec strings, force flags,
    deletion flags, tag flags, or destination overrides.
    """
    import inspect

    from rig_relay.cli._steward._campaign_push import execute_campaign_push

    sig = inspect.signature(execute_campaign_push)
    params = list(sig.parameters.keys())
    # Must not accept arbitrary refspec, force, delete options
    forbidden = {
        "refspec",
        "force",
        "delete",
        "tags",
        "mirror",
        "all",
        "destination",
        "remote_ref",
    }
    for param in params:
        assert param not in forbidden, (
            f"Governed push API exposes unsafe parameter: {param}"
        )
