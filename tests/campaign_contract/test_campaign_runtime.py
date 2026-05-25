"""Tests for campaign runtime, checkpoint, push, and completion.

Tests exercise real production boundaries with real temporary Git
repositories and local bare remotes.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from pydantic import ValidationError
import pytest

from rig_relay.campaign_contract.models import BoundedIncidentalUnblockRepairDecision
from rig_relay.cli._steward._campaign_checkpoint import (
    issue_campaign_checkpoint_receipt,
    validate_campaign_checkpoint_request,
)
from rig_relay.cli._steward._campaign_completion import (
    build_campaign_completion_packet,
    emit_campaign_completion,
)
from rig_relay.cli._steward._campaign_manifest import (
    CampaignManifestLoadError,
    load_campaign_manifest,
)
from rig_relay.cli._steward._campaign_models import (
    CampaignState,
    compute_manifest_digest,
)
from rig_relay.cli._steward._campaign_push import validate_campaign_push_request
from rig_relay.cli._steward._campaign_runtime import (
    append_checkpoint_receipt,
    append_event,
    append_finding,
    append_push_receipt,
    init_campaign_dir,
    load_campaign_state,
    save_campaign_state,
)
from rig_relay.cli._steward._campaign_scheduler import (
    evaluate_bounded_repair,
    evaluate_resolver_promotion,
    find_next_eligible_mission,
    record_mission_outcome,
)
from rig_relay.cli._steward._campaign_tools import validate_campaign_tool_write

# ---- Helpers ---------------------------------------------------------

_EXCLUSIONS = [
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
]


def _mission_dict(mission_id: str, owned=None, read=None, provider=None, prereqs=None):
    return {
        "mission_id": mission_id,
        "owned_path_scope": owned or [f"{mission_id}_owned"],
        "read_context_scope": read or [f"{mission_id}_read"],
        "provider_context_scope": provider or [f"{mission_id}_prov"],
        "validation_commands": ["uv", "run", "pytest"],
        "prerequisites": prereqs or [],
        "resolver_scope_declarations": ["mission_impl"],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    }


def _base_manifest_dict(missions=None):
    return {
        "record_stage": "approved_definition",
        "manifest": {
            "ordered_missions": missions or [_mission_dict("m1")],
            "user_approval_marker": True,
            "operating_mode": "confidential_autonomous_campaign_nonpromoting",
            "provider_disclosure_attestation": {
                "mode": "hosted_confidential_full_source_user_approved",
                "provider_family_identity": "fam",
                "provider_model_identity": "model1",
                "actual_retention_control_mode_classification": "standard_retention",
                "campaign_scope_digest": "dig",
                "campaign_scope_approval_marker": True,
                "mission_level_provider_scope_enforcement_marker": True,
            },
            "absolute_exclusions": list(_EXCLUSIONS),
            "mission_universe_immutable_after_execution_begins": True,
        },
        "lane_policy": {
            "lane_identity": "lane1",
            "additive_accumulated_delta_marker": True,
            "write_scope": "isolated_campaign_lane_only",
            "checkpoint_prohibited": True,
            "commit_prohibited": True,
            "promotion_prohibited": True,
            "push_prohibited": True,
            "publication_prohibited": True,
            "git_history_mutation_prohibited": True,
            "upload_prohibited": True,
            "public_render_prohibited": True,
            "telemetry_export_prohibited": True,
            "human_promotion_marker": True,
        },
        "implementation_entry_gate": {
            "entries": [
                {
                    "required_gate_identity": "g1",
                    "required_status": "satisfied",
                    "current_satisfaction_status": True,
                    "content_light_evidence_reference": "ref1",
                    "blocks_runtime_implementation": False,
                    "blocks_live_steward_execution": True,
                    "blocks_real_campaign_execution": True,
                    "blocks_promotion_authority": True,
                }
            ]
        },
    }


def _campaign_manifest_dict(
    campaign_id="test-campaign",
    missions=None,
    branch="confidential/steward-campaign/test-campaign",
):
    contract = _base_manifest_dict(missions)
    runtime = {
        "campaign_id": campaign_id,
        "operating_mode": (
            "confidential_autonomous_campaign_with_private_checkpoint_push"
        ),
        "lane_root_identity": "lane1",
        "baseline_commit_sha": "0000000000000000000000000000000000000000",
        "assigned_local_branch": branch,
        "assigned_remote_repository": "juliantorr-es/rig-relay",
        "assigned_remote_branch": branch,
        "private_checkpoint_push_authorized": True,
        "checkpoint_cadence": "per_mission",
        "push_cadence": "per_checkpoint",
        "path_classification_registry_digest": "",
        "allowed_validation_commands": ["uv", "run", "pytest"],
        "halt_policy": "stop_on_security_or_confidentiality",
        "human_promotion_required": True,
        "merge_to_main_allowed": False,
        "publication_allowed": False,
        "release_allowed": False,
        "force_push_allowed": False,
        "ref_deletion_allowed": False,
        "tag_creation_allowed": False,
    }
    return {"contract": contract, "runtime": runtime}


def _write_manifest(tmp_path, manifest_dict):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest_dict))
    return p


def _campaign_state(
    campaign_id="test-campaign",
    phase="running",
    completed=None,
    paused=None,
    checkpoint_count=0,
):
    return CampaignState.model_validate({
        "campaign_id": campaign_id,
        "operating_mode": (
            "confidential_autonomous_campaign_with_private_checkpoint_push"
        ),
        "phase": phase,
        "lane_identity": "lane1",
        "baseline_sha": "0000000000000000000000000000000000000000",
        "active_branch": f"confidential/steward-campaign/{campaign_id}",
        "assigned_remote_branch": (f"confidential/steward-campaign/{campaign_id}"),
        "current_mission_id": "m1",
        "completed_missions": completed or [],
        "paused_missions": paused or [],
        "pending_missions": [],
        "checkpoint_count": checkpoint_count,
        "manifest_digest": compute_manifest_digest(
            _campaign_manifest_dict(campaign_id=campaign_id)
        ),
    })


# ---- Phase 0: Plugin fail-closed test --------------------------------


def test_plugin_deny_syntax(tmp_path):
    """Classification: contract/adversarial

    The TypeScript plugin source contains NO fail-open fallback.
    Any catch block must return allowed: false.
    """
    plugin_path = (
        Path(__file__).parents[3] / ".opencode" / "plugins" / "rig-roadmap-steward.ts"
    )
    if not plugin_path.exists():
        pytest.skip("plugin file not found in expected location")
    content = plugin_path.read_text()
    # No fallback allowance
    assert "allowed: true" not in content
    # Always deny in catch blocks
    assert "allowed: false" in content
    # No filename-based heuristic as sole protection
    assert '.endsWith(".env")' not in content


# ---- Phase 1: Manifest loading tests ---------------------------------


def test_contract_integration_valid_campaign_manifest_loads(tmp_path):
    """Classification: contract/integration
    A valid campaign manifest with approved missions and runtime
    extensions loads successfully.
    """
    manifest_dict = _campaign_manifest_dict()
    path = _write_manifest(tmp_path, manifest_dict)
    ext, digest = load_campaign_manifest(path)
    assert ext.campaign_id == "test-campaign"
    assert ext.operating_mode == (
        "confidential_autonomous_campaign_with_private_checkpoint_push"
    )
    assert len(digest) == 64


def test_contract_sabotage_invalid_mode_refuses(tmp_path):
    """Classification: contract/sabotage
    An unsupported operating mode refuses.
    """
    manifest_dict = _campaign_manifest_dict()
    manifest_dict["runtime"]["operating_mode"] = "bogus_mode"
    path = _write_manifest(tmp_path, manifest_dict)
    with pytest.raises(CampaignManifestLoadError):
        load_campaign_manifest(path)


def test_contract_sabotage_protected_branch_refuses(tmp_path):
    """Classification: contract/sabotage
    A manifest assigning main as the campaign branch refuses.
    """
    manifest_dict = _campaign_manifest_dict(branch="main")
    path = _write_manifest(tmp_path, manifest_dict)
    with pytest.raises(CampaignManifestLoadError):
        load_campaign_manifest(path)


def test_contract_sabotage_invalid_json_refuses(tmp_path):
    """Classification: contract/sabotage
    Invalid JSON refuses with CampaignManifestLoadError.
    """
    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(CampaignManifestLoadError):
        load_campaign_manifest(p)


# ---- Phase 2: Runtime state tests ------------------------------------


def test_contract_integration_runtime_state_persists(tmp_path):
    """Classification: contract/integration
    Campaign state can be saved and loaded from the authority directory.
    """
    state = _campaign_state()
    save_campaign_state(state, "test-campaign", tmp_path)
    loaded = load_campaign_state("test-campaign", tmp_path)
    assert loaded is not None
    assert loaded.campaign_id == "test-campaign"
    assert loaded.completed_missions == []


def test_contract_integration_event_ledger_appends(tmp_path):
    """Classification: contract/integration
    Events append to the campaign event ledger.
    """
    init_campaign_dir("test-campaign", tmp_path)
    append_event("test-campaign", tmp_path, {"type": "mission_started"})
    append_event("test-campaign", tmp_path, {"type": "mission_done"})
    ledger = tmp_path / ".rig/relay/campaigns/test-campaign/events.v1.jsonl"
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 2


def test_contract_integration_findings_ledger_appends(tmp_path):
    """Classification: contract/integration
    Findings append to the campaign findings ledger.
    """
    init_campaign_dir("test-campaign", tmp_path)
    append_finding("test-campaign", tmp_path, {"class": "blocker"})
    ledger = tmp_path / ".rig/relay/campaigns/test-campaign/findings.v1.jsonl"
    assert ledger.exists()


# ---- Phase 3: Scheduler tests ----------------------------------------


def test_contract_integration_finds_next_eligible_mission(tmp_path):
    """Classification: contract/integration
    The scheduler finds the next eligible mission in order.
    """
    manifest_dict = _campaign_manifest_dict(
        missions=[_mission_dict("m1"), _mission_dict("m2", prereqs=["m1"])]
    )
    path = _write_manifest(tmp_path, manifest_dict)
    ext, _ = load_campaign_manifest(path)
    state = _campaign_state(completed=["m1"])
    from rig_relay.campaign_contract.models import CampaignManifest as CM

    manifest = CM.model_validate(manifest_dict["contract"]["manifest"])
    next_mission = find_next_eligible_mission(manifest, state)
    assert next_mission is not None
    assert next_mission.mission_id == "m2"


def test_contract_sabotage_resolver_not_eligible_if_completed(tmp_path):
    """Classification: contract/sabotage
    An already-completed mission is not considered as a resolver.
    """
    manifest_dict = _campaign_manifest_dict(
        missions=[_mission_dict("m1"), _mission_dict("m2")]
    )
    path = _write_manifest(tmp_path, manifest_dict)
    ext, _ = load_campaign_manifest(path)
    from rig_relay.campaign_contract.models import CampaignManifest as CM

    manifest = CM.model_validate(manifest_dict["contract"]["manifest"])
    state = _campaign_state(completed=["m2"])
    blocked = manifest.ordered_missions[0]
    resolver = evaluate_resolver_promotion(manifest, blocked, state)
    assert resolver is None


def test_contract_integration_bounded_repair_accepts_valid(tmp_path):
    """Classification: contract/integration
    A valid bounded repair passes all constraints.
    """
    repair = BoundedIncidentalUnblockRepairDecision.model_validate({
        "operation_kind": "bounded_incidental_unblock_repair",
        "no_eligible_manifest_resolver_marker": True,
        "low_blast_radius": True,
        "non_architectural": True,
        "compatibility_preserving": True,
        "no_security_boundary_change": True,
        "no_disclosure_boundary_change": True,
        "no_dependency_change": True,
        "no_policy_config_schema_family_change": True,
        "no_shared_module_refactor": True,
        "no_unsafe_fallback": True,
        "no_test_weakening": True,
        "pre_edit_decision_recorded": True,
        "targeted_validation_plan": "t",
        "validation_result_required_before_resume": True,
        "out_of_scope_source_path_count": 1,
        "broad_refactor_prohibited": True,
        "bypass_prohibited": True,
        "global_fixture_prohibited": True,
        "lint_suppression_prohibited": True,
    })
    assert evaluate_bounded_repair(repair) is True


def test_contract_sabotage_bounded_repair_rejects_dep_change(tmp_path):
    """Classification: contract/sabotage
    A bounded repair with dependency change rejects at the model level.
    """
    with pytest.raises(ValidationError):
        BoundedIncidentalUnblockRepairDecision.model_validate({
            "operation_kind": "bounded_incidental_unblock_repair",
            "no_eligible_manifest_resolver_marker": True,
            "low_blast_radius": True,
            "non_architectural": True,
            "compatibility_preserving": True,
            "no_security_boundary_change": True,
            "no_disclosure_boundary_change": True,
            "no_dependency_change": False,
            "no_policy_config_schema_family_change": True,
            "no_shared_module_refactor": True,
            "no_unsafe_fallback": True,
            "no_test_weakening": True,
            "pre_edit_decision_recorded": True,
            "targeted_validation_plan": "t",
            "validation_result_required_before_resume": True,
            "out_of_scope_source_path_count": 0,
            "broad_refactor_prohibited": True,
            "bypass_prohibited": True,
            "global_fixture_prohibited": True,
            "lint_suppression_prohibited": True,
        })


# ---- Phase 4: Tools gateway tests ------------------------------------


def test_contract_integration_write_in_scope_succeeds(tmp_path):
    """Classification: contract/integration
    A write to an active mission's owned_path_scope succeeds.
    """
    from rig_relay.campaign_contract.models import CampaignManifest as CM

    manifest_dict = _campaign_manifest_dict()
    manifest = CM.model_validate(manifest_dict["contract"]["manifest"])
    state = _campaign_state()
    mission = manifest.ordered_missions[0]
    err = validate_campaign_tool_write(state, manifest, mission, "m1_owned", tmp_path)
    assert err is None


def test_contract_sabotage_write_outside_scope_refuses(tmp_path):
    """Classification: contract/sabotage
    A write outside active mission scope refuses.
    """
    from rig_relay.campaign_contract.models import CampaignManifest as CM

    manifest_dict = _campaign_manifest_dict()
    manifest = CM.model_validate(manifest_dict["contract"]["manifest"])
    state = _campaign_state()
    mission = manifest.ordered_missions[0]
    err = validate_campaign_tool_write(
        state, manifest, mission, "outside_path", tmp_path
    )
    assert err is not None


def test_contract_sabotage_write_authority_path_refuses(tmp_path):
    """Classification: contract/sabotage
    A write to a campaign authority path refuses.
    """
    from rig_relay.campaign_contract.models import CampaignManifest as CM

    manifest_dict = _campaign_manifest_dict(
        missions=[
            _mission_dict("m1", owned=[".rig/relay/campaigns/test-campaign/state.json"])
        ]
    )
    manifest = CM.model_validate(manifest_dict["contract"]["manifest"])
    state = _campaign_state()
    mission = manifest.ordered_missions[0]
    err = validate_campaign_tool_write(
        state,
        manifest,
        mission,
        ".rig/relay/campaigns/test-campaign/state.json",
        tmp_path,
    )
    assert err is not None


# ---- Phase 5: Checkpoint tests ---------------------------------------


def test_contract_integration_checkpoint_receipt_issues(tmp_path):
    """Classification: contract/integration
    A valid campaign checkpoint receipt is issued.
    """
    ext, digest = load_campaign_manifest(
        _write_manifest(tmp_path, _campaign_manifest_dict())
    )
    state = _campaign_state()
    receipt = issue_campaign_checkpoint_receipt(
        ext, state, "m1", ["m1_owned/foo.py"], digest, "validated"
    )
    assert receipt["schema_version"] == "rig.relay.step_up_authorization_receipt.v1"
    assert receipt["action"] == "checkpoint.commit"
    assert receipt["action_scope"]["branch"] == (
        "confidential/steward-campaign/test-campaign"
    )


def test_contract_sabotage_checkpoint_refuses_prohibited_paths(tmp_path):
    """Classification: contract/sabotage
    Checkpoint request with prohibited paths refuses.
    """
    ext, _ = load_campaign_manifest(
        _write_manifest(tmp_path, _campaign_manifest_dict())
    )
    state = _campaign_state()
    err = validate_campaign_checkpoint_request(
        ext, state, [".build/rig-relay/confidential/secret.json"], tmp_path
    )
    assert err is not None


# ---- Phase 6: Push tests (real local bare remote) --------------------


def _setup_bare_remote(tmp_path):
    """Create a local bare remote for push testing."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(
        ["git", "-C", str(bare), "init", "--bare"], check=True, capture_output=True
    )
    return bare


def _setup_working_repo(tmp_path, bare_remote):
    """Create a working repo with a commit to push."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "-C", str(work), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "remote", "add", "origin", str(bare_remote)],
        check=True,
        capture_output=True,
    )
    (work / "test.txt").write_text("hello")
    subprocess.run(
        ["git", "-C", str(work), "add", "test.txt"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return work


def test_integration_real_artifact_push_succeeds_to_assigned_branch(tmp_path):
    """Classification: integration/real-artifact
    A fast-forward push to the assigned campaign branch succeeds on a
    real local bare remote.
    """
    bare = _setup_bare_remote(tmp_path)
    work = _setup_working_repo(tmp_path, bare)
    branch = "confidential/steward-campaign/test-campaign"
    subprocess.run(
        ["git", "-C", str(work), "checkout", "-b", branch],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "-C", str(work), "push", "origin", f"{branch}:{branch}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_contract_sabotage_push_request_main_branch_refuses(tmp_path):
    """Classification: contract/sabotage
    Push request targeting main refuses.
    """
    manifest_dict = _campaign_manifest_dict(branch="main")
    path = _write_manifest(tmp_path, manifest_dict)
    with pytest.raises(CampaignManifestLoadError):
        load_campaign_manifest(path)


def test_contract_sabotage_push_denied_without_authorization(tmp_path):
    """Classification: contract/sabotage
    Push request denied when push not authorized.
    """
    manifest_dict = _campaign_manifest_dict()
    manifest_dict["runtime"]["private_checkpoint_push_authorized"] = False
    ext, _ = load_campaign_manifest(_write_manifest(tmp_path, manifest_dict))
    state = _campaign_state()
    err = validate_campaign_push_request(
        ext,
        state,
        "confidential/steward-campaign/test-campaign",
        "juliantorr-es/rig-relay",
        tmp_path,
    )
    assert err is not None


# ---- Phase 8: Completion packet tests --------------------------------


def test_contract_integration_completion_packet_builds(tmp_path):
    """Classification: contract/integration
    A completion packet is built with all required fields.
    """
    ext, _ = load_campaign_manifest(
        _write_manifest(tmp_path, _campaign_manifest_dict())
    )
    state = _campaign_state(completed=["m1"], checkpoint_count=1, phase="completed")
    packet = build_campaign_completion_packet(ext, state, tmp_path)
    assert packet["campaign_id"] == "test-campaign"
    assert packet["completed_missions"] == ["m1"]
    assert packet["checkpoint_count"] == 1
    assert packet["human_promotion_required"] is True
    assert packet["checkpoint_performed"] is True
    assert packet["promotion_performed"] is False


def test_contract_integration_completion_writes_to_disk(tmp_path):
    """Classification: contract/integration
    The completion packet is persisted to the campaign directory.
    """
    ext, _ = load_campaign_manifest(
        _write_manifest(tmp_path, _campaign_manifest_dict())
    )
    state = _campaign_state(completed=["m1"])
    emit_campaign_completion(ext, state, tmp_path)
    full_path = tmp_path / ".rig/relay/campaigns/test-campaign/completion.v1.json"
    assert full_path.exists()
    data = json.loads(full_path.read_text())
    assert data["campaign_id"] == "test-campaign"


# ---- E2E campaign test -----------------------------------------------


def test_e2e_real_artifact_multi_mission_campaign_with_checkpoint_and_push(tmp_path):
    """Classification: E2E/real-artifact
    A fixture campaign with two missions, a checkpoint, and a push to a
    local bare remote exercises the full runtime boundary.

    Mission m1 completes, checkpoint is created on campaign branch,
    checkpoint is pushed to assigned remote branch. Mission m2 continues.
    """
    bare = _setup_bare_remote(tmp_path)
    work = _setup_working_repo(tmp_path, bare)
    branch = "confidential/steward-campaign/e2e-test"
    subprocess.run(
        ["git", "-C", str(work), "checkout", "-b", branch],
        check=True,
        capture_output=True,
    )

    # Create manifest and runtime
    manifest_dict = _campaign_manifest_dict(
        campaign_id="e2e-test",
        branch=branch,
        missions=[_mission_dict("m1"), _mission_dict("m2", prereqs=["m1"])],
    )
    ext, digest = load_campaign_manifest(_write_manifest(tmp_path, manifest_dict))
    assert ext.campaign_id == "e2e-test"

    # Initialize state
    state = _campaign_state(campaign_id="e2e-test", phase="running", completed=[])
    state.active_branch = branch
    state.manifest_digest = digest
    save_campaign_state(state, "e2e-test", tmp_path)

    # Simulate mission m1: write file, checkpoint
    (work / "m1_file.py").write_text("x = 1")
    subprocess.run(["git", "-C", str(work), "add", "m1_file.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "m1 changes"], capture_output=True
    )
    head1 = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # Issue checkpoint receipt and record
    receipt = issue_campaign_checkpoint_receipt(
        ext, state, "m1", ["m1_file.py"], digest
    )
    append_checkpoint_receipt("e2e-test", tmp_path, receipt)

    state = record_mission_outcome(state, "m1", "success", "ok")
    state.checkpoint_count = 1
    state.latest_checkpoint_sha = head1
    save_campaign_state(state, "e2e-test", tmp_path)

    # Push
    state.push_count = 1
    push_result = subprocess.run(
        ["git", "-C", str(work), "push", "origin", f"{branch}:{branch}"],
        capture_output=True,
        text=True,
    )
    assert push_result.returncode == 0

    push_receipt = {
        "receipt_id": "pr1",
        "campaign_id": "e2e-test",
        "push_sequence": 1,
        "succeeded": True,
        "remote_repository": "juliantorr-es/rig-relay",
        "destination_branch": branch,
        "pushed_head_sha": head1,
    }
    append_push_receipt("e2e-test", tmp_path, push_receipt)

    # Verify remote branch exists
    remote_refs = subprocess.run(
        ["git", "-C", str(bare), "show-ref"], capture_output=True, text=True
    )
    assert f"refs/heads/{branch}" in remote_refs.stdout

    # Verify main is untouched
    main_refs = subprocess.run(
        ["git", "-C", str(bare), "show-ref", "refs/heads/main"],
        capture_output=True,
        text=True,
    )
    assert main_refs.returncode == 1
    assert "refs/heads/main" not in main_refs.stdout

    # Complete campaign
    state.phase = "completed"
    save_campaign_state(state, "e2e-test", tmp_path)
    emit_campaign_completion(ext, state, tmp_path)
    packet_path = tmp_path / ".rig/relay/campaigns/e2e-test/completion.v1.json"
    assert packet_path.exists()
    packet_data = json.loads(packet_path.read_text())
    assert packet_data["campaign_id"] == "e2e-test"
    assert packet_data["human_promotion_required"] is True
    assert packet_data["promotion_performed"] is False


# ---- Registry tests --------------------------------------------------

from rig_relay.cli._steward._campaign_registry import (
    PathClassificationRegistry,
    compute_registry_digest,
    is_classification_refused,
    is_write_allowed,
    load_path_registry,
    save_path_registry,
)


def test_contract_integration_registry_save_and_load(tmp_path):
    """Classification: contract/integration
    A path classification registry is saved and loaded from the
    campaign authority directory.
    """
    registry = PathClassificationRegistry.model_validate({
        "registry_identity": "reg1",
        "campaign_id": "test-campaign",
        "manifest_digest": "abc123",
        "entries": [
            {
                "normalized_path": "src/app.py",
                "classification": "approved_write_scope",
                "identity_digest": "d1",
            },
            {
                "normalized_path": "tests/test_app.py",
                "classification": "approved_read_context",
                "identity_digest": "d2",
            },
        ],
    })
    saved = save_path_registry(registry, "test-campaign", tmp_path)
    assert saved.exists()
    loaded = load_path_registry("test-campaign", tmp_path)
    assert loaded is not None
    assert loaded.campaign_id == "test-campaign"
    assert len(loaded.entries) == 2


def test_contract_integration_registry_write_allowed(tmp_path):
    """Classification: contract/integration
    A path classified as approved_write_scope is write-allowed.
    """
    registry = PathClassificationRegistry.model_validate({
        "registry_identity": "reg1",
        "campaign_id": "c1",
        "manifest_digest": "abc",
        "entries": [
            {
                "normalized_path": "src/app.py",
                "classification": "approved_write_scope",
                "identity_digest": "d1",
            }
        ],
    })
    assert is_write_allowed(registry, "src/app.py") is True
    assert is_write_allowed(registry, "unknown.py") is False


def test_contract_sabotage_registry_classification_refused_halts(tmp_path):
    """Classification: contract/sabotage
    A path classified as credential_or_secret_refused is refused.
    """
    registry = PathClassificationRegistry.model_validate({
        "registry_identity": "reg1",
        "campaign_id": "c1",
        "manifest_digest": "abc",
        "entries": [
            {
                "normalized_path": "secrets.env",
                "classification": "credential_or_secret_refused",
                "identity_digest": "d1",
            }
        ],
    })
    assert is_classification_refused(registry, "secrets.env") is True
    assert is_write_allowed(registry, "secrets.env") is False


def test_contract_integration_registry_digest_deterministic(tmp_path):
    """Classification: contract/integration
    The registry digest is deterministic.
    """
    registry = PathClassificationRegistry.model_validate({
        "registry_identity": "reg1",
        "campaign_id": "c1",
        "manifest_digest": "abc",
        "entries": [],
    })
    d1 = compute_registry_digest(registry)
    d2 = compute_registry_digest(registry)
    assert d1 == d2
    assert len(d1) == 64


# ---- Phase 7: Campaign execution dispatch (dogfood) -----------------


def test_mutation_execution_routes_through_public_runtime(tmp_path, monkeypatch):
    """S5-A: Declared mutation execution through public campaign dispatch."""
    repo = _setup_working_repo(tmp_path, _setup_bare_remote(tmp_path))
    monkeypatch.chdir(repo)

    branch = "confidential/steward-campaign/c1"
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True
    )
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True
    )

    from rig_relay.governance.dirty_guard import get_guard, reset_guard

    reset_guard()
    get_guard().capture()
    get_guard().mark_touched(repo / "a.py")

    import hashlib

    coord = tmp_path / "coordination"

    # Persist proposal
    from rig_relay.coordination.patch_workflow import PatchWorkflowStore
    from rig_relay.coordination.patch_proposal import PatchProposal

    store = PatchWorkflowStore(coord)
    proposal = PatchProposal(
        proposal_id="prop-s5",
        mission_id="m1",
        agent_id="a1",
        title="test",
        summary="test",
        status="pending",
        touched_paths=["a.py"],
        expected_before_sha256={},
    )
    store.save_proposal(proposal)

    # Persist payload
    from rig_relay.cli._steward._mutation_payload import (
        MutationPayloadRecord,
        save_payload,
    )

    blocks = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
    payload = MutationPayloadRecord(
        payload_id="pay-s5",
        proposal_id="prop-s5",
        campaign_id="c1",
        mission_id="m1",
        file_path="a.py",
        before_sha256=hashlib.sha256(b"x = 1\n").hexdigest(),
        candidate_after_sha256=hashlib.sha256(b"x = 2\n").hexdigest(),
        mutation_content=blocks,
        payload_sha256=hashlib.sha256(blocks.encode()).hexdigest(),
    )
    save_payload(payload, repo)

    # Write manifest with execution_spec
    manifest = {
        "ordered_missions": [
            {
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
                "execution_spec": {
                    "proposal_based_mutation": {
                        "execution_id": "exec-1",
                        "execution_kind": "proposal_based_mutation",
                        "proposal_id": "prop-s5",
                        "payload_id": "pay-s5",
                    }
                },
            }
        ],
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
    }
    (repo / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Construct CampaignState separately with only its accepted fields
    state_dict: dict[str, object] = {
        "campaign_id": "c1",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "running",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": branch,
        "assigned_remote_branch": branch,
        "current_mission_id": "m1",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": None,
        "latest_pushed_sha": None,
        "completed_missions": [],
        "paused_missions": [],
        "checkpoint_count": 0,
        "push_count": 0,
    }
    from rig_relay.cli._steward._campaign_models import CampaignState

    state = CampaignState.model_validate(state_dict)

    from rig_relay.cli._steward._campaign_runtime import save_campaign_state

    save_campaign_state(state, "c1", repo)

    # Execute through public runtime
    from rig_relay.cli._steward._campaign_runtime import execute_campaign_execution

    result = execute_campaign_execution(
        campaign_id="c1", mission_id="m1", repo_root=repo, coordination_root=coord
    )
    assert result["outcome"] == "campaign_mutation_completed"
    assert result.get("status") == "completed"

    # Verify file was mutated
    assert (repo / "a.py").read_text() == "x = 2\n"

    # Restart — reload state and call again
    state2 = CampaignState.model_validate_json(
        (
            repo / ".rig" / "relay" / "campaigns" / "c1" / "state_projection.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert "m1" in state2.completed_missions

    result2 = execute_campaign_execution(
        campaign_id="c1", mission_id="m1", repo_root=repo, coordination_root=coord
    )
    assert result2.get("status") == "already_completed"

    # Source unchanged after restart
    assert (repo / "a.py").read_text() == "x = 2\n"
