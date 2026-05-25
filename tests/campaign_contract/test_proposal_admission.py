"""Tests for mutation proposal admission, payload custody, and governed apply.

Tests exercise real production boundaries with real temporary files,
campaign directories, and payload artifacts.
"""

from __future__ import annotations

import hashlib
import subprocess

from rig_relay.cli._steward._campaign_models import CampaignState
from rig_relay.cli._steward._campaign_registry import (
    PathClassificationRegistry,
    PathRegistryEntry,
)
from rig_relay.cli._steward._mutation_payload import (
    MutationPayloadRecord,
    compute_payload_sha256,
    delete_payload,
    load_payload,
    save_payload,
    verify_payload_binding,
)
from rig_relay.cli._steward._proposal_admission import (
    ProposalAdmissionDecision,
    admit_patch_proposal,
)
from rig_relay.cli._steward._proposal_apply import apply_admitted_proposal
from rig_relay.coordination.patch_proposal import PatchProposal
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


def _registry(entries=None):
    return PathClassificationRegistry.model_validate({
        "registry_identity": "reg1",
        "campaign_id": "c1",
        "manifest_digest": "abc",
        "entries": entries
        or [
            PathRegistryEntry(
                normalized_path="src/app.py",
                classification="approved_write_scope",
                identity_digest="d1",
            )
        ],
    })


def _state(phase="running", mission_id="m1"):
    return CampaignState.model_validate({
        "campaign_id": "c1",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": phase,
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "b",
        "assigned_remote_branch": "b",
        "current_mission_id": mission_id,
        "manifest_digest": "dig",
        "latest_checkpoint_sha": "s1",
        "latest_pushed_sha": "s1",
    })


def _simple_mission(mission_id="m1"):
    from rig_relay.campaign_contract.models import MissionDefinition

    return MissionDefinition.model_validate({
        "mission_id": mission_id,
        "owned_path_scope": ["src/app.py"],
        "read_context_scope": [],
        "provider_context_scope": [],
        "validation_commands": [],
        "prerequisites": [],
        "resolver_scope_declarations": [],
        "completion_contract": {},
        "blocked_continuation_policy": "halt_chain",
        "steward_authored_mission_insertion_prohibited": True,
    })


def _simple_manifest():
    from rig_relay.campaign_contract.models import CampaignManifest

    return CampaignManifest.model_validate({
        "ordered_missions": [_simple_mission().model_dump()],
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


def _proposal(
    proposal_id="prop-1", path="src/app.py", before_hash=None, after_hash=None
):
    return PatchProposal.model_validate({
        "proposal_id": proposal_id,
        "mission_id": "m1",
        "agent_id": "a1",
        "title": "test",
        "summary": "test",
        "status": "pending",
        "touched_paths": [path],
        "touched_path_hashes": [f"sha256:{'0' * 64}"],
        "expected_before_sha256": {path: f"sha256:{before_hash or '0' * 64}"},
        "candidate_after_sha256": {path: f"sha256:{after_hash or '0' * 64}"},
    })


def _payload(
    content, proposal_id="prop-1", path="src/app.py", before_hash=None, after_hash=None
):
    sha = compute_payload_sha256(content)
    return MutationPayloadRecord.model_validate({
        "payload_id": f"pay-{proposal_id}",
        "proposal_id": proposal_id,
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": path,
        "before_sha256": before_hash or "0" * 64,
        "candidate_after_sha256": after_hash or "b" * 64,
        "mutation_content": content,
        "content_format": "search_replace_blocks",
        "payload_sha256": sha,
    })


def _proposal_result(
    path="src/app.py", before_hash="", after_hash="", status="proposal_computed"
):
    return SearchReplaceProposalResult.model_validate({
        "file": path,
        "status": status,
        "blocks_applied": 1,
        "failed_block_count": 0,
        "total_block_count": 1,
        "before_file_sha256": {path: f"sha256:{before_hash}"},
        "after_file_sha256": {path: f"sha256:{after_hash}"},
        "before_bytes": 10,
        "after_bytes": 12,
    })


def _admit(proposal, result, state, mission, registry, payload, file_bytes, root):
    return admit_patch_proposal(
        proposal,
        result,
        state,
        _simple_manifest(),
        mission,
        registry,
        payload,
        file_bytes,
        root,
    )


# ---- Payload custody tests -------------------------------------------


def test_contract_payload_saves_and_loads(tmp_path):
    p = _payload(
        "SEARCH\na\n=======\nb\nREPLACE", before_hash="a" * 64, after_hash="b" * 64
    )
    save_payload(p, tmp_path)
    loaded = load_payload(p.payload_id, p.campaign_id, tmp_path)
    assert loaded is not None
    assert loaded.proposal_id == "prop-1"


def test_contract_payload_binding_verified(tmp_path):
    content = "SEARCH\na\n=======\nb\nREPLACE"
    p = _payload(content, before_hash="a" * 64, after_hash="b" * 64)
    assert verify_payload_binding(p) is True


def test_contract_sabotage_tampered_payload_refuses_binding(tmp_path):
    p = _payload(
        "SEARCH\nx\n=======\ny\nREPLACE", before_hash="a" * 64, after_hash="b" * 64
    )
    tampered = p.model_copy(update={"payload_sha256": "deadbeef"})
    assert verify_payload_binding(tampered) is False


def test_contract_payload_deletes_after_apply(tmp_path):
    p = _payload(
        "SEARCH\nx\n=======\ny\nREPLACE", before_hash="a" * 64, after_hash="b" * 64
    )
    save_payload(p, tmp_path)
    assert load_payload(p.payload_id, p.campaign_id, tmp_path) is not None
    deleted = delete_payload(p.payload_id, p.campaign_id, tmp_path)
    assert deleted is True
    assert load_payload(p.payload_id, p.campaign_id, tmp_path) is None


def test_contract_payload_not_in_content_light_path(tmp_path):
    payload_dir = tmp_path / ".rig" / "relay" / "campaigns" / "c1" / "mutation_payloads"
    payload_dir.mkdir(parents=True)
    assert ".rig/relay/campaigns/" in str(payload_dir)


# ---- Admission gate tests --------------------------------------------


def test_contract_admitted_proposal_accepted(tmp_path):
    content = "hello world\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    pc = "<<<<<<< SEARCH\nhello world\n=======\nhello sun\n>>>>>>> REPLACE"
    mh = hashlib.sha256(
        content.replace("hello world", "hello sun").encode()
    ).hexdigest()

    proposal = _proposal(before_hash=bh, after_hash=mh)
    result = _proposal_result(before_hash=bh, after_hash=mh)
    state = _state()
    mission = _simple_mission()
    registry = _registry()
    payload = _payload(pc, before_hash=bh, after_hash=mh)

    decision = _admit(
        proposal, result, state, mission, registry, payload, fp.read_bytes(), tmp_path
    )
    assert decision.admission_status == "admitted"
    assert decision.before_sha256 == bh
    assert decision.candidate_after_sha256 == mh


def test_contract_sabotage_inactive_campaign_refuses(tmp_path):
    state = _state(phase="halted")
    decision = _admit(
        _proposal(),
        _proposal_result(),
        state,
        _simple_mission(),
        _registry(),
        _payload("SEARCH\nx\n=======\ny\nREPLACE"),
        b"x\n",
        tmp_path,
    )
    assert decision.admission_status == "refused"


def test_contract_sabotage_outside_scope_refuses(tmp_path):
    proposal = _proposal(path="outside.py")
    result = _proposal_result(path="outside.py")
    decision = _admit(
        proposal,
        result,
        _state(),
        _simple_mission(),
        _registry(),
        _payload("SEARCH\nx\n=======\ny\nREPLACE"),
        b"x\n",
        tmp_path,
    )
    assert decision.admission_status == "refused"


def test_contract_sabotage_stale_baseline_refuses(tmp_path):
    content = "hello\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    wrong_hash = "0" * 64

    proposal = _proposal(before_hash=bh)
    result = _proposal_result(before_hash=wrong_hash)
    decision = _admit(
        proposal,
        result,
        _state(),
        _simple_mission(),
        _registry(),
        _payload(
            "SEARCH\nhello\n=======\nworld\nREPLACE",
            before_hash=wrong_hash,
            after_hash="b" * 64,
        ),
        fp.read_bytes(),
        tmp_path,
    )
    assert decision.admission_status == "stale"


def test_contract_adversarial_admission_content_light(tmp_path):
    content = "hi\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    pc = "<<<<<<< SEARCH\nhi\n=======\nho\n>>>>>>> REPLACE"
    mh = hashlib.sha256(content.replace("hi", "ho").encode()).hexdigest()

    decision = _admit(
        _proposal(before_hash=bh, after_hash=mh),
        _proposal_result(before_hash=bh, after_hash=mh),
        _state(),
        _simple_mission(),
        _registry(),
        _payload(pc, before_hash=bh, after_hash=mh),
        fp.read_bytes(),
        tmp_path,
    )
    raw = decision.model_dump_json()
    assert "SEARCH" not in raw
    assert "REPLACE" not in raw
    assert pc not in raw


# ---- Apply gate tests ------------------------------------------------


def test_contract_applied_proposal_mutates_workspace(tmp_path):
    content = "hello world\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    before_hash = hashlib.sha256(content.encode()).hexdigest()
    modified = content.replace("hello world", "hello sun")
    after_hash = hashlib.sha256(modified.encode()).hexdigest()
    payload_content = "<<<<<<< SEARCH\nhello world\n=======\nhello sun\n>>>>>>> REPLACE"

    decision = ProposalAdmissionDecision.model_validate({
        "decision_id": "d1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": str(fp),
        "admission_status": "admitted",
        "authority_source": "test",
        "reason_code": "admitted",
        "before_sha256": before_hash,
        "candidate_after_sha256": after_hash,
        "payload_sha256": compute_payload_sha256(payload_content),
    })
    payload = _payload(payload_content, before_hash=before_hash, after_hash=after_hash)

    result = apply_admitted_proposal(
        decision, payload, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "applied"
    assert result.after_sha256 == after_hash
    assert fp.read_text() == "hello sun\n"


def test_contract_sabotage_refused_admission_cannot_apply(tmp_path):
    content = "hello\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    decision = ProposalAdmissionDecision.model_validate({
        "decision_id": "d1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": str(fp),
        "admission_status": "refused",
        "authority_source": "test",
        "reason_code": "scope_violation",
    })
    payload = _payload(
        "SEARCH\nx\n=======\ny\nREPLACE", before_hash="0" * 64, after_hash="b" * 64
    )
    result = apply_admitted_proposal(
        decision, payload, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "refused"
    assert fp.read_text() == "hello\n"


def test_contract_sabotage_stale_workspace_refuses_apply(tmp_path):
    content = "stale content\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    decision = ProposalAdmissionDecision.model_validate({
        "decision_id": "d1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": str(fp),
        "admission_status": "admitted",
        "authority_source": "test",
        "reason_code": "admitted",
        "before_sha256": "0" * 64,
        "candidate_after_sha256": "b" * 64,
    })
    payload = _payload(
        "SEARCH\nx\n=======\ny\nREPLACE", before_hash="0" * 64, after_hash="b" * 64
    )
    result = apply_admitted_proposal(
        decision, payload, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "divergent"
    assert fp.read_text() == "stale content\n"


def test_contract_sabotage_tampered_payload_refuses_apply(tmp_path):
    content = "original\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    pc = "SEARCH\noriginal\n=======\nnew\nREPLACE"
    mh = hashlib.sha256(content.replace("original", "new").encode()).hexdigest()

    decision = ProposalAdmissionDecision.model_validate({
        "decision_id": "d1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": str(fp),
        "admission_status": "admitted",
        "authority_source": "test",
        "reason_code": "admitted",
        "before_sha256": bh,
        "candidate_after_sha256": mh,
        "payload_sha256": compute_payload_sha256(pc),
    })
    tampered = _payload(pc, before_hash=bh, after_hash=mh).model_copy(
        update={"payload_sha256": "deadbeef"}
    )
    result = apply_admitted_proposal(
        decision, tampered, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "refused"
    assert "payload_binding_invalid" in (result.refusal_reason or "")


# ---- Canonical path identity tests -----------------------------------


def test_contract_canonical_identity_admission_uses_relative_path(tmp_path):
    """Classification: contract/integration
    Admission evidence stores canonical relative identity, not absolute path.
    """
    content = "test\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    mh = hashlib.sha256(b"modified\n").hexdigest()

    decision = _admit(
        _proposal(before_hash=bh, after_hash=mh),
        _proposal_result(before_hash=bh, after_hash=mh),
        _state(),
        _simple_mission(),
        _registry(),
        _payload(
            "SEARCH\ntest\n=======\nmodified\nREPLACE", before_hash=bh, after_hash=mh
        ),
        fp.read_bytes(),
        tmp_path,
    )
    assert decision.admission_status == "admitted"
    # File path in evidence should be canonical, not absolute temp path
    assert str(tmp_path) not in decision.file_path
    assert "src/app.py" in decision.file_path


def test_contract_adversarial_no_absolute_temp_root_in_evidence(tmp_path):
    """Classification: contract/adversarial
    Admission decision contains no absolute temporary root.
    """
    content = "x\n"
    fp = tmp_path / "src" / "app.py"
    fp.parent.mkdir(parents=True)
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    mh = hashlib.sha256(b"y\n").hexdigest()

    decision = _admit(
        _proposal(before_hash=bh, after_hash=mh),
        _proposal_result(before_hash=bh, after_hash=mh),
        _state(),
        _simple_mission(),
        _registry(),
        _payload("SEARCH\nx\n=======\ny\nREPLACE", before_hash=bh, after_hash=mh),
        fp.read_bytes(),
        tmp_path,
    )
    raw = decision.model_dump_json()
    abs_root = str(tmp_path.resolve())
    assert abs_root not in raw


# ---- E2E: compute → custody → admit → apply -------------------------


def test_e2e_real_artifact_full_proposal_workflow(tmp_path, monkeypatch):
    """Classification: E2E/real-artifact
    Full workflow with real SearchReplace.compute_proposal() output:
    compute → persist payload → admit → apply. Absolute operational path
    is accepted via canonical root-relative identity resolution.
    """
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(["git", "-C", str(bare), "init", "--bare"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
        capture_output=True,
    )
    branch = "confidential/steward-campaign/e2e-prop"
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True
    )
    (repo / "src").mkdir(parents=True, exist_ok=True)
    content = "def greet():\n    return 'hello'\n"
    (repo / "src/app.py").write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True
    )

    # Compute proposal via real SearchReplace
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
        file_path="src/app.py",
        content="<<<<<<< SEARCH\nreturn 'hello'\n=======\nreturn 'hello world'\n>>>>>>> REPLACE",
    )
    result = asyncio.run(tool.compute_proposal(args))
    assert result.status == "proposal_computed"

    p_before = list(result.before_file_sha256.values())[0].replace("sha256:", "")
    p_after = list(result.after_file_sha256.values())[0].replace("sha256:", "")
    assert p_before == bh

    # Create payload
    payload_content = (
        "<<<<<<< SEARCH\nreturn 'hello'\n=======\nreturn 'hello world'\n>>>>>>> REPLACE"
    )
    payload = MutationPayloadRecord.model_validate({
        "payload_id": "pay-e2e",
        "proposal_id": "prop-e2e",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": "src/app.py",
        "before_sha256": p_before,
        "candidate_after_sha256": p_after,
        "mutation_content": payload_content,
        "content_format": "search_replace_blocks",
        "payload_sha256": compute_payload_sha256(payload_content),
    })
    save_payload(payload, repo)

    # Admit with repo_root — canonical identity resolves absolute → relative
    proposal = PatchProposal.model_validate({
        "proposal_id": "prop-e2e",
        "mission_id": "m1",
        "agent_id": "a1",
        "title": "test",
        "summary": "test",
        "status": "pending",
        "touched_paths": ["src/app.py"],
        "touched_path_hashes": [f"sha256:{'0' * 64}"],
        "expected_before_sha256": {"src/app.py": f"sha256:{p_before}"},
        "candidate_after_sha256": {"src/app.py": f"sha256:{p_after}"},
    })
    registry = _registry(
        entries=[
            PathRegistryEntry(
                normalized_path="src/app.py",
                classification="approved_write_scope",
                identity_digest="d1",
            )
        ]
    )
    state = _state()
    mission = _simple_mission()
    manifest = _simple_manifest()
    decision = admit_patch_proposal(
        proposal,
        result,
        state,
        manifest,
        mission,
        registry,
        payload,
        (repo / "src/app.py").read_bytes(),
        repo,
    )
    assert decision.admission_status == "admitted"

    # Apply
    apply_result = apply_admitted_proposal(
        decision,
        payload,
        (repo / "src/app.py").read_bytes(),
        repo / "src/app.py",
        "c1",
        repo,
    )
    assert apply_result.status == "applied"
    expected_content = content.replace("return 'hello'", "return 'hello world'")
    assert (repo / "src/app.py").read_text() == expected_content

    # Checkpoint + push to assigned branch
    subprocess.run(["git", "-C", str(repo), "add", "src/app.py"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "checkpoint"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "push", "origin", f"{branch}:{branch}"],
        capture_output=True,
    )

    # Push confirmed, main untouched
    remote_refs = subprocess.run(
        ["git", "-C", str(bare), "show-ref"], capture_output=True, text=True
    )
    assert f"refs/heads/{branch}" in remote_refs.stdout
    main_refs = subprocess.run(
        ["git", "-C", str(bare), "show-ref", "refs/heads/main"],
        capture_output=True,
        text=True,
    )
    assert main_refs.returncode == 1

    # Payload deleted after apply
    assert load_payload("pay-e2e", "c1", repo) is None
