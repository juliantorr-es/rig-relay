"""Tests for continuation lock and atomic status transitions."""

from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

from rig_relay.coordination.patch_proposal import PatchProposal
from rig_relay.coordination.patch_workflow import (
    PatchWorkflowStore,
    ProposalTransitionError,
    create_pending_proposal,
    proposal_continuation_context,
    transition_proposal_status,
)


def _temp_store(tmp_path: Path) -> PatchWorkflowStore:
    coord = tmp_path / "coordination"
    return PatchWorkflowStore(coord)


def _make_pending(tmp_path: Path, key: str) -> PatchProposal:
    import uuid

    repo = tmp_path / "repo"
    repo.mkdir()
    return create_pending_proposal(
        coordination_root=tmp_path / "coordination",
        file_path="target.py",
        before_hash="sha256:" + "a" * 64,
        after_hash="sha256:" + "b" * 64,
        proposal_id=f"prop-{uuid.uuid4().hex[:12]}",
        idempotency_key=key,
    )


class TestProposalContinuationContext:
    """Lock acquisition and release."""

    def test_lock_acquire_and_release(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-lock-1")
        with proposal_continuation_context(
            tmp_path / "coordination", proposal.proposal_id
        ):
            pass
        # Lock released after context

    def test_concurrent_lock_exclusion(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-lock-2")
        acquired = threading.Event()
        inside = threading.Event()

        def holder() -> None:
            with proposal_continuation_context(
                tmp_path / "coordination", proposal.proposal_id
            ):
                acquired.set()
                time.sleep(0.5)

        def contender() -> None:
            acquired.wait()
            # Try non-blocking — if lock is held, this should block
            import fcntl
            import os

            lock_path = (
                tmp_path
                / "coordination"
                / ".fleet"
                / "patch-proposals"
                / f"{proposal.proposal_id}.lock"
            )
            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                inside.set()
            except BlockingIOError:
                pass
            finally:
                os.close(fd)

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=contender)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not inside.is_set(), (
            "Non-blocking lock should have failed while holder held it"
        )


class TestTransitionProposalStatus:
    """Atomic status transitions."""

    def test_valid_transition_succeeds(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-trans-1")
        result = transition_proposal_status(
            tmp_path / "coordination", proposal.proposal_id, "pending", "applying"
        )
        assert result.status == "applying"

        result2 = transition_proposal_status(
            tmp_path / "coordination", proposal.proposal_id, "applying", "applied"
        )
        assert result2.status == "applied"

    def test_stale_from_status_refused(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-trans-2")
        transition_proposal_status(
            tmp_path / "coordination", proposal.proposal_id, "pending", "applying"
        )
        with pytest.raises(ProposalTransitionError):
            transition_proposal_status(
                tmp_path / "coordination",
                proposal.proposal_id,
                "pending",
                "applied",  # stale
            )

    def test_lock_token_forwarded(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-trans-3")
        with proposal_continuation_context(
            tmp_path / "coordination", proposal.proposal_id
        ) as lock_fd:
            result = transition_proposal_status(
                tmp_path / "coordination",
                proposal.proposal_id,
                "pending",
                "applying",
                _lock_fd=lock_fd,
            )
            assert result.status == "applying"


class TestIntegratedLockPipeline:
    """Lock → transition → checkpoint all under one lock."""

    def test_full_pipeline_under_lock(self, tmp_path: Path) -> None:
        proposal = _make_pending(tmp_path, "key-pipeline")
        with proposal_continuation_context(
            tmp_path / "coordination", proposal.proposal_id
        ) as lock_fd:
            r1 = transition_proposal_status(
                tmp_path / "coordination",
                proposal.proposal_id,
                "pending",
                "applying",
                _lock_fd=lock_fd,
            )
            assert r1.status == "applying"
            r2 = transition_proposal_status(
                tmp_path / "coordination",
                proposal.proposal_id,
                "applying",
                "applied",
                _lock_fd=lock_fd,
            )
            assert r2.status == "applied"
