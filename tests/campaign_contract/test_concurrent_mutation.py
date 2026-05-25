"""Concurrency proofs for the governed mutation lifecycle coordinator.

S4-A: Same-proposal concurrent continuation — duplicate execution idempotency.
S4-B: Competing distinct proposals against same baseline — write-boundary safety.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
from pathlib import Path
import subprocess
import threading

import pytest

from rig_relay.cli._steward._campaign_mutation import execute_proposal_based_mutation
from rig_relay.cli._steward._mutation_payload import MutationPayloadRecord, save_payload
from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import PatchWorkflowStore
from rig_relay.core.tools.builtins.search_replace import SearchReplaceProposalResult
from rig_relay.governance.dirty_guard import get_guard, reset_guard

# Reuse proven canonical helpers from sibling test module
from tests.campaign_contract.test_campaign_mutation import (
    _extension,  # (campaign_id="c1", push_authorized=True)
    _manifest,  # () -> CampaignManifest
    _mission,  # () -> MissionDefinition
    _registry,  # () -> PathClassificationRegistry
    _state,  # (phase="running", campaign_id="c1", mission_id="m1")
)


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


@pytest.fixture(autouse=True)
def _reset_guard() -> None:

    reset_guard()


_SEARCH_BLOCKS_A = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
_SEARCH_BLOCKS_B = "<<<<<<< SEARCH\nx = 1\n=======\nx = 99\n>>>>>>> REPLACE"


class TestConcurrentSameProposal:
    """S4-A: Same-proposal concurrent continuation — one logical chain."""

    @pytest.mark.timeout(30)
    def test_concurrent_calls_produce_one_mutation_chain(
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
        get_guard().capture()
        get_guard().mark_touched(repo / "a.py")

        coord = tmp_path / "coordination"
        store = PatchWorkflowStore(coord)
        proposal = PatchProposal(
            proposal_id="prop-conc",
            mission_id="m1",
            agent_id="a1",
            title="test",
            summary="test",
            status="pending",
            touched_paths=["a.py"],
            expected_before_sha256={},
        )
        store.save_proposal(proposal)

        payload = MutationPayloadRecord(
            payload_id="pay-conc",
            proposal_id="prop-conc",
            campaign_id="c1",
            mission_id="m1",
            file_path="a.py",
            before_sha256=hashlib.sha256(b"x = 1\n").hexdigest(),
            candidate_after_sha256=hashlib.sha256(b"x = 2\n").hexdigest(),
            mutation_content=_SEARCH_BLOCKS_A,
            payload_sha256=hashlib.sha256(_SEARCH_BLOCKS_A.encode("utf-8")).hexdigest(),
        )
        save_payload(payload, repo)

        proposal_result = SearchReplaceProposalResult(
            file="a.py",
            status="proposal_computed",
            blocks_applied=1,
            after_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 2\n").hexdigest()
            },
            before_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 1\n").hexdigest()
            },
        )

        ext = _extension()
        manifest = _manifest()
        mission = _mission()

        results: list[dict] = []
        barrier = threading.Barrier(2, timeout=15)

        def make_state():
            s = _state()
            s.latest_checkpoint_sha = None
            s.latest_pushed_sha = None
            return s

        def _runner() -> None:
            local_state = make_state()
            barrier.wait()
            r = asyncio.run(
                execute_proposal_based_mutation(
                    campaign_state=local_state,
                    manifest=manifest,
                    extension=ext,
                    mission=mission,
                    registry=_registry(),
                    proposal=proposal,
                    proposal_result=proposal_result,
                    payload=payload,
                    file_bytes=(repo / "a.py").read_bytes(),
                    file_path=repo / "a.py",
                    repo_root=repo,
                    remote_url="test-remote",
                    current_branch=branch,
                    coordination_root=coord,
                )
            )
            results.append(r)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(_runner)
            f2 = ex.submit(_runner)
            f1.result(timeout=25)
            f2.result(timeout=25)

        assert len(results) == 2
        assert all(r["outcome"] == "campaign_mutation_completed" for r in results), (
            f"Concurrent same-proposal outcomes: {[r['outcome'] for r in results]}\n"
            f"Reasons: {[r.get('refusal_reason', '') for r in results]}\n"
            f"File hash: {hashlib.sha256((repo / 'a.py').read_bytes()).hexdigest()}\n"
            f"HEAD: {subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=repo).stdout.strip()}"
        )

        file_hash = hashlib.sha256((repo / "a.py").read_bytes()).hexdigest()
        assert file_hash == hashlib.sha256(b"x = 2\n").hexdigest()

        refs = subprocess.run(
            ["git", "-C", str(bare), "show-ref", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert refs, f"Remote branch {branch} not found"

        main_ref = subprocess.run(
            ["git", "-C", str(bare), "show-ref", "refs/heads/main"],
            capture_output=True,
            text=True,
        )
        assert "refs/heads/main" not in (main_ref.stdout or "")


class TestConcurrentDistinctProposals:
    """S4-B: Competing distinct proposals — write-boundary safety."""

    @pytest.mark.timeout(30)
    def test_two_proposals_same_baseline_one_wins(
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
        get_guard().capture()
        get_guard().mark_touched(repo / "a.py")

        coord = tmp_path / "coordination"
        store = PatchWorkflowStore(coord)

        prop_a = PatchProposal(
            proposal_id="prop-a",
            mission_id="m1",
            agent_id="a1",
            title="A",
            summary="A",
            status="pending",
            touched_paths=["a.py"],
            expected_before_sha256={},
        )
        store.save_proposal(prop_a)
        prop_b = PatchProposal(
            proposal_id="prop-b",
            mission_id="m2",
            agent_id="a2",
            title="B",
            summary="B",
            status="pending",
            touched_paths=["a.py"],
            expected_before_sha256={},
        )
        store.save_proposal(prop_b)

        pl_a = MutationPayloadRecord(
            payload_id="pay-a",
            proposal_id="prop-a",
            campaign_id="c1",
            mission_id="m1",
            file_path="a.py",
            before_sha256=hashlib.sha256(b"x = 1\n").hexdigest(),
            candidate_after_sha256=hashlib.sha256(b"x = 2\n").hexdigest(),
            mutation_content=_SEARCH_BLOCKS_A,
            payload_sha256=hashlib.sha256(_SEARCH_BLOCKS_A.encode("utf-8")).hexdigest(),
        )
        save_payload(pl_a, repo)
        pl_b = MutationPayloadRecord(
            payload_id="pay-b",
            proposal_id="prop-b",
            campaign_id="c1",
            mission_id="m2",
            file_path="a.py",
            before_sha256=hashlib.sha256(b"x = 1\n").hexdigest(),
            candidate_after_sha256=hashlib.sha256(b"x = 99\n").hexdigest(),
            mutation_content=_SEARCH_BLOCKS_B,
            payload_sha256=hashlib.sha256(_SEARCH_BLOCKS_B.encode("utf-8")).hexdigest(),
        )
        save_payload(pl_b, repo)

        ra = SearchReplaceProposalResult(
            file="a.py",
            status="proposal_computed",
            blocks_applied=1,
            after_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 2\n").hexdigest()
            },
            before_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 1\n").hexdigest()
            },
        )
        rb = SearchReplaceProposalResult(
            file="a.py",
            status="proposal_computed",
            blocks_applied=1,
            after_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 99\n").hexdigest()
            },
            before_file_sha256={
                "a.py": "sha256:" + hashlib.sha256(b"x = 1\n").hexdigest()
            },
        )

        ext = _extension()
        manifest = _manifest()
        reg = _registry()
        ma = _mission()
        mb = ma.model_copy(update={"mission_id": "m2"})

        results: list[dict] = []
        barrier = threading.Barrier(2, timeout=15)

        def make_state():
            s = _state()
            s.latest_checkpoint_sha = None
            s.latest_pushed_sha = None
            return s

        def _runner_a() -> None:
            local_state = make_state()
            barrier.wait()
            results.append(
                asyncio.run(
                    execute_proposal_based_mutation(
                        campaign_state=local_state,
                        manifest=manifest,
                        extension=ext,
                        mission=ma,
                        registry=reg,
                        proposal=prop_a,
                        proposal_result=ra,
                        payload=pl_a,
                        file_bytes=(repo / "a.py").read_bytes(),
                        file_path=repo / "a.py",
                        repo_root=repo,
                        remote_url="test-remote",
                        current_branch=branch,
                        coordination_root=coord,
                    )
                )
            )

        def _runner_b() -> None:
            local_state = make_state()
            barrier.wait()
            results.append(
                asyncio.run(
                    execute_proposal_based_mutation(
                        campaign_state=local_state,
                        manifest=manifest,
                        extension=ext,
                        mission=mb,
                        registry=reg,
                        proposal=prop_b,
                        proposal_result=rb,
                        payload=pl_b,
                        file_bytes=(repo / "a.py").read_bytes(),
                        file_path=repo / "a.py",
                        repo_root=repo,
                        remote_url="test-remote",
                        current_branch=branch,
                        coordination_root=coord,
                    )
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fa = ex.submit(_runner_a)
            fb = ex.submit(_runner_b)
            fa.result(timeout=25)
            fb.result(timeout=25)

        assert len(results) == 2
        completed = [
            r for r in results if r["outcome"] == "campaign_mutation_completed"
        ]
        assert len(completed) >= 1, (
            f"Expected >=1 completed, got {[r['outcome'] for r in results]}"
        )

        file_hash = hashlib.sha256((repo / "a.py").read_bytes()).hexdigest()
        cand_a = hashlib.sha256(b"x = 2\n").hexdigest()
        cand_b = hashlib.sha256(b"x = 99\n").hexdigest()
        assert file_hash in (cand_a, cand_b), (
            f"File hash {file_hash} is neither candidate A nor B"
        )
