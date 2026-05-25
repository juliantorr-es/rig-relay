"""Process-separated concurrency proofs for the governed mutation lifecycle.

Uses multiprocessing.get_context("spawn") to prove that independent
worker processes, each reconstructing state from durable artifacts,
serialize correctly through the fcntl.flock continuation lock.

S4-A-process: Same-proposal cross-worker continuation.
S4-B-process: Competing distinct proposals cross-worker proof.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
import subprocess

import pytest


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(
        ["git", "-C", str(tmp_path), "init"], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True
    )
    return tmp_path


def _init_bare(tmp_path: Path) -> Path:
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(
        ["git", "-C", str(bare), "init", "--bare"], capture_output=True, check=True
    )
    return bare


_SEARCH_BLOCKS = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"


def _worker_same_proposal(
    repo_str: str, coord_str: str, barrier_file: str, queue: multiprocessing.Queue
) -> None:
    """Worker: load durable state, execute same proposal, return result."""
    import hashlib
    import json
    import os
    from pathlib import Path as _Path
    import time

    # File-based barrier: touch ready file, wait for all ready
    ready_file = _Path(barrier_file) / f"ready_{os.getpid()}"
    ready_file.touch()
    # Wait for both ready files
    while len(list(_Path(barrier_file).glob("ready_*"))) < 2:
        time.sleep(0.05)

    from rig_relay.cli._steward._campaign_models import CampaignState
    from rig_relay.cli._steward._campaign_runtime import (
        execute_campaign_execution,
        save_campaign_state,
    )
    from rig_relay.cli._steward._mutation_payload import (
        MutationPayloadRecord,
        save_payload,
    )
    from rig_relay.coordination.patch_proposal import PatchProposal
    from rig_relay.coordination.patch_workflow import PatchWorkflowStore
    from rig_relay.governance.dirty_guard import get_guard, reset_guard

    repo = Path(repo_str)
    coord = Path(coord_str)
    reset_guard()
    get_guard().capture()
    get_guard().mark_touched(repo / "a.py")

    # Persist proposal (idempotent across workers — same ID)
    store = PatchWorkflowStore(coord)
    proposal = PatchProposal(
        proposal_id="prop-cross",
        mission_id="m1",
        agent_id="a1",
        title="test",
        summary="test",
        status="pending",
        touched_paths=["a.py"],
        expected_before_sha256={},
    )
    try:
        store.save_proposal(proposal)
    except Exception:
        pass  # Already exists from other worker

    blocks = _SEARCH_BLOCKS
    payload = MutationPayloadRecord(
        payload_id="pay-cross",
        proposal_id="prop-cross",
        campaign_id="c-cross",
        mission_id="m1",
        file_path="a.py",
        before_sha256=hashlib.sha256(b"x = 1\n").hexdigest(),
        candidate_after_sha256=hashlib.sha256(b"x = 2\n").hexdigest(),
        mutation_content=blocks,
        payload_sha256=hashlib.sha256(blocks.encode()).hexdigest(),
    )
    try:
        save_payload(payload, repo)
    except Exception:
        pass

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
                        "execution_id": "exec-cross",
                        "execution_kind": "proposal_based_mutation",
                        "proposal_id": "prop-cross",
                        "payload_id": "pay-cross",
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

    state_dict = {
        "campaign_id": "c-cross",
        "operating_mode": "confidential_autonomous_campaign_with_private_checkpoint_push",
        "phase": "running",
        "lane_identity": "l1",
        "baseline_sha": "abc",
        "active_branch": "confidential/steward-campaign/c1",
        "assigned_remote_branch": "confidential/steward-campaign/c1",
        "current_mission_id": "m1",
        "manifest_digest": "dig",
        "latest_checkpoint_sha": None,
        "latest_pushed_sha": None,
        "completed_missions": [],
        "paused_missions": [],
        "checkpoint_count": 0,
        "push_count": 0,
    }
    state = CampaignState.model_validate(state_dict)
    save_campaign_state(state, "c-cross", repo)

    result = execute_campaign_execution(
        campaign_id="c-cross", mission_id="m1", repo_root=repo, coordination_root=coord
    )
    queue.put(result)


class TestProcessSeparatedSameProposal:
    """S4-A-process: Same-proposal cross-worker continuation."""

    @pytest.mark.timeout(60)
    def test_two_workers_one_mutation_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _init_repo(tmp_path)
        bare = _init_bare(tmp_path)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
            capture_output=True,
        )
        branch = "confidential/steward-campaign/c1"
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True
        )
        (repo / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True
        )
        monkeypatch.chdir(repo)

        coord = tmp_path / "coordination"
        barrier_dir = tmp_path / "barrier"
        barrier_dir.mkdir()
        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()

        p1 = ctx.Process(
            target=_worker_same_proposal,
            args=(str(repo), str(coord), str(barrier_dir), queue),
        )
        p2 = ctx.Process(
            target=_worker_same_proposal,
            args=(str(repo), str(coord), str(barrier_dir), queue),
        )
        p1.start()
        p2.start()
        p1.join(timeout=50)
        p2.join(timeout=50)

        results: list[dict] = []
        while not queue.empty():
            results.append(queue.get())

        assert len(results) == 2
        statuses = [r.get("status") or r.get("outcome", "") for r in results]
        completed = [
            s
            for s in statuses
            if s in ("completed", "campaign_mutation_completed", "already_completed")
        ]
        assert len(completed) >= 1, f"Expected >=1 completed, got {statuses}"

        # File mutated
        import hashlib

        file_hash = hashlib.sha256((repo / "a.py").read_bytes()).hexdigest()
        assert file_hash == hashlib.sha256(b"x = 2\n").hexdigest()

        # Remote branch exists
        refs = subprocess.run(
            ["git", "-C", str(bare), "show-ref", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert refs, f"Remote branch {branch} not found"

        # Main untouched
        main_ref = subprocess.run(
            ["git", "-C", str(bare), "show-ref", "refs/heads/main"],
            capture_output=True,
            text=True,
        )
        assert "refs/heads/main" not in (main_ref.stdout or "")
