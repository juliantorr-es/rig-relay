from __future__ import annotations

import ast
import inspect
import multiprocessing
from pathlib import Path

import pytest

from rig_relay.coordination.fleet_claim_corridor import (
    FleetClaimEvent,
    FleetClaimEventKind,
    FleetClaimInfo,
    FleetClaimLedger,
    FleetClaimProtocol,
    FleetClaimState,
    FleetClaimXattr,
    _now_iso,
    _sha256_event_payload,
    file_sha256,
)


def _acquire_worker(
    ledger_path_str: str,
    repo_root_str: str,
    path: str,
    mission_id: str,
    lane_id: str,
    agent_id: str,
    result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    result = proto.acquire_claim(
        paths=[path], mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
    )
    ev = result.event
    result_queue.put((
        result.acquired,
        ev.event_kind.value if ev is not None else "no_event",
        ev.event_sequence if ev is not None else 0,
        ev.prior_sha256 if ev is not None else None,
    ))


def _release_worker(
    ledger_path_str: str,
    repo_root_str: str,
    paths: list[str],
    mission_id: str,
    lane_id: str,
    agent_id: str,
    result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    result = proto.release_claim(
        paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
    )
    ev = result.event
    result_queue.put((
        ev.event_kind.value if ev is not None else "no_event",
        ev.event_sequence if ev is not None else 0,
        result.acquired,
        result.reason,
    ))




def _hash_proof_worker(
    ledger_path_str: str, repo_root_str: str, path: str,
    ready_event: multiprocessing.Event, result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    ready_event.set()
    r = proto.acquire_claim(
        paths=[path], mission_id="m1", lane_id="l1", agent_id="a1"
    )
    result_queue.put((r.acquired, r.event.prior_sha256 if r.event else None))


def _digest_chain_public_append_worker(
    ledger_path_str: str, result_queue: multiprocessing.Queue,
) -> None:
    from rig_relay.coordination.fleet_claim_corridor import (
        FleetClaimEvent,
        FleetClaimEventKind,
        _now_iso,
    )
    ledger_path = Path(ledger_path_str)
    ledger = FleetClaimLedger(ledger_path)
    event = FleetClaimEvent(
        event_id="", event_kind=FleetClaimEventKind.CLAIM_REQUESTED,
        mission_id="m_raw", lane_id="l_raw", agent_id="a_raw",
        claimed_paths=["race_digest.txt"], timestamp=_now_iso(), event_digest="",
        prior_event_digest="fabricated_deadbeef000000000000000000000000000000000000000000000000000000",
    )
    result = ledger.append(event)
    result_queue.put((result.event_sequence, result.event_digest, result.prior_event_digest))


def _digest_chain_proto_worker(
    ledger_path_str: str, repo_root_str: str, result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    r = proto.release_claim(
        paths=["race_digest.txt"], mission_id="m_acq", lane_id="l_acq", agent_id="a_acq"
    )
    result_queue.put((r.event.event_sequence, r.event.event_digest, r.event.prior_event_digest))




def _raw_append_worker(ledger_path_str: str, event_kind_str: str, mission_id: str, lane_id: str, agent_id: str, claimed_paths: list, result_queue) -> None:
    ledger_path = Path(ledger_path_str)
    ledger = FleetClaimLedger(ledger_path)
    event = FleetClaimEvent(event_id="", event_kind=FleetClaimEventKind(event_kind_str), mission_id=mission_id, lane_id=lane_id, agent_id=agent_id, claimed_paths=claimed_paths, timestamp=_now_iso(), event_digest="")
    result = ledger.append(event)
    result_queue.put((result.event_sequence, result.event_digest))


def _sha256_lock_holder(ledger_path_str: str, ready_event, release_event) -> None:
    import fcntl
    lock_path = Path(ledger_path_str).parent / "coordination_events.v1.lock"
    fd = open(str(lock_path), "r+b")
    fcntl.flock(fd, fcntl.LOCK_EX)
    ready_event.set()
    release_event.wait(timeout=30)
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()


def _acquire_blocking_worker(ledger_path_str: str, repo_root_str: str, path: str, mission_id: str, lane_id: str, agent_id: str, result_queue) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    result = proto.acquire_claim(paths=[path], mission_id=mission_id, lane_id=lane_id, agent_id=agent_id)
    ev = result.event
    result_queue.put((result.acquired, ev.event_kind.value if ev is not None else None, ev.prior_sha256 if ev is not None else None))


@pytest.fixture
def protocol(tmp_path: Path) -> tuple[FleetClaimProtocol, Path]:
    ledger_path = tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, tmp_path)
    return proto, tmp_path


class TestFleetClaimCorridor:
    def test_claim_acquired_writes_ledger_and_xattrs(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "test.txt"
        fpath.write_text("hello fleet")
        result = proto.acquire_claim(
            paths=["test.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result.acquired is True
        assert result.event is not None
        assert result.event.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        assert "test.txt" in result.event.claimed_paths
        events = proto._ledger.read_all()
        acquired_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        ]
        assert len(acquired_events) == 1
        info = FleetClaimXattr.read_claim(fpath)
        assert info is not None
        assert info.mission_id == "m1"
        assert info.lane_id == "l1"
        state = FleetClaimXattr.read_state(fpath)
        assert state == FleetClaimState.CLAIMED

    def test_second_claim_on_same_path_refused_with_conflict_event(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "shared.txt"
        fpath.write_text("shared content")
        result_a = proto.acquire_claim(
            paths=["shared.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result_a.acquired is True
        result_b = proto.acquire_claim(
            paths=["shared.txt"], mission_id="m2", lane_id="l2", agent_id="a2"
        )
        assert result_b.acquired is False
        assert result_b.event is not None
        assert result_b.event.event_kind == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT
        info = FleetClaimXattr.read_claim(fpath)
        assert info is not None
        assert info.lane_id == "l1"

    def test_reacquire_after_release_find_active_claim_returns_new_owner(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "release_me.txt"
        fpath.write_text("release test")
        result_a = proto.acquire_claim(
            paths=["release_me.txt"], mission_id="m1", lane_id="l_a", agent_id="a_a"
        )
        assert result_a.acquired is True
        result_rel = proto.release_claim(
            paths=["release_me.txt"], mission_id="m1", lane_id="l_a", agent_id="a_a"
        )
        assert result_rel.event is not None
        assert result_rel.event.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        assert proto._ledger.find_active_claim("release_me.txt") is None
        result_b = proto.acquire_claim(
            paths=["release_me.txt"], mission_id="m2", lane_id="l_b", agent_id="a_b"
        )
        assert result_b.acquired is True
        active = proto._ledger.find_active_claim("release_me.txt")
        assert active is not None
        assert active.lane_id == "l_b"

    def test_non_owner_release_refused_owner_preserved(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "owned.txt"
        fpath.write_text("owner content")
        proto.acquire_claim(
            paths=["owned.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        refusal = proto.release_claim(
            paths=["owned.txt"], mission_id="m_b", lane_id="l_b", agent_id="a_b"
        )
        assert refusal.acquired is False
        assert refusal.event is not None
        assert refusal.event.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED
        active = proto._ledger.find_active_claim("owned.txt")
        assert active is not None
        assert active.lane_id == "l_a"
        xattr_after = FleetClaimXattr.read_claim(fpath)
        assert xattr_after is not None
        assert xattr_after.lane_id == "l_a"
        events = proto._ledger.read_all()
        released_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(released_events) == 0

    def test_stale_base_detected_when_file_changes_after_claim(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "stale.txt"
        original = "original content"
        fpath.write_text(original)
        result = proto.acquire_claim(
            paths=["stale.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result.acquired is True
        stale_check = proto.check_stale_base(
            paths=["stale.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert stale_check["stale.txt"] is False
        fpath.write_text("modified content")
        stale_check = proto.check_stale_base(
            paths=["stale.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert stale_check["stale.txt"] is True

    def test_missing_xattr_does_not_erase_ledger_state(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "resilient.txt"
        fpath.write_text("resilient content")
        proto.acquire_claim(
            paths=["resilient.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        FleetClaimXattr.clear_claim_xattrs(fpath)
        assert FleetClaimXattr.read_claim(fpath) is None
        active = proto._ledger.find_active_claim("resilient.txt")
        assert active is not None
        scanned = proto.scan_claims()
        assert "resilient.txt" in scanned

    # ── C0.1 authority tests ──────────────────────────────────────────

    
    def test_stale_xattr_does_not_override_canonical_ledger_after_reacquisition(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        """Prove scan_claims() and find_active_claim() both report lane B
        when stale lane-A xattrs are present after release/reacquire.
        """
        proto, tmp = protocol
        fpath = tmp / "stale_xattr.txt"
        fpath.write_text("content_a")

        from rig_relay.coordination.fleet_claim_corridor import FleetClaimInfo, _now_iso

        proto.acquire_claim(
            paths=["stale_xattr.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        proto.release_claim(
            paths=["stale_xattr.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )

        # Deliberately write stale lane-A xattrs
        stale_info = FleetClaimInfo(
            mission_id="m_a", lane_id="l_a", agent_id="a_a",
            acquired_at=_now_iso(), base_sha256={},
        )
        FleetClaimXattr.write_claim(fpath, stale_info)

        # Lane B acquires — canonical owner
        proto.acquire_claim(
            paths=["stale_xattr.txt"], mission_id="m_b", lane_id="l_b", agent_id="a_b"
        )

        active = proto._ledger.find_active_claim("stale_xattr.txt")
        assert active is not None
        assert active.lane_id == "l_b"

        scanned = proto.scan_claims()
        assert "stale_xattr.txt" in scanned
        assert scanned["stale_xattr.txt"].lane_id == "l_b"
        assert scanned["stale_xattr.txt"].mission_id == "m_b"

class TestFleetClaimCorridorLocking:
    def test_two_processes_same_file_one_acquires_one_refused(
        self, tmp_path: Path
    ) -> None:
        fpath = tmp_path / "shared.txt"
        fpath.write_text("race content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        q: multiprocessing.Queue = multiprocessing.Queue()
        p1 = multiprocessing.Process(
            target=_acquire_worker,
            args=(str(ledger_path), str(tmp_path), "shared.txt", "m1", "l1", "a1", q),
        )
        p2 = multiprocessing.Process(
            target=_acquire_worker,
            args=(str(ledger_path), str(tmp_path), "shared.txt", "m2", "l2", "a2", q),
        )
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2
        acquired = [r for r in results if r[0] is True]
        refused = [r for r in results if r[0] is False]
        assert len(acquired) == 1
        assert len(refused) == 1
        assert refused[0][1] == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT.value
        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences)
        assert sorted(sequences) == [1, 2]

    def test_two_processes_disjoint_files_both_acquire(self, tmp_path: Path) -> None:
        f1 = tmp_path / "file_a.txt"
        f2 = tmp_path / "file_b.txt"
        f1.write_text("content a")
        f2.write_text("content b")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        q: multiprocessing.Queue = multiprocessing.Queue()
        p1 = multiprocessing.Process(
            target=_acquire_worker,
            args=(str(ledger_path), str(tmp_path), "file_a.txt", "m1", "l1", "a1", q),
        )
        p2 = multiprocessing.Process(
            target=_acquire_worker,
            args=(str(ledger_path), str(tmp_path), "file_b.txt", "m2", "l2", "a2", q),
        )
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2
        assert all(r[0] for r in results)
        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences)
        assert sorted(sequences) == [1, 2]

    def test_concurrent_release_and_acquire_produces_at_most_one_owner(
        self, tmp_path: Path
    ) -> None:
        fpath = tmp_path / "contested.txt"
        fpath.write_text("contested content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        result_a = proto.acquire_claim(
            paths=["contested.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        assert result_a.acquired is True
        q: multiprocessing.Queue = multiprocessing.Queue()
        p_release = multiprocessing.Process(
            target=_release_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                ["contested.txt"],
                "m_a",
                "l_a",
                "a_a",
                q,
            ),
        )
        p_acquire = multiprocessing.Process(
            target=_acquire_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                "contested.txt",
                "m_b",
                "l_b",
                "a_b",
                q,
            ),
        )
        p_release.start()
        p_acquire.start()
        p_release.join(timeout=30)
        p_acquire.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2
        ledger2 = FleetClaimLedger(ledger_path)
        active = ledger2.find_active_claim("contested.txt")
        if active is not None:
            assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
            assert active.lane_id in ("l_a", "l_b")

    def test_non_owner_release_does_not_displace_legitimate_owner(
        self, tmp_path: Path
    ) -> None:
        fpath = tmp_path / "protected.txt"
        fpath.write_text("protected content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        proto.acquire_claim(
            paths=["protected.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        q: multiprocessing.Queue = multiprocessing.Queue()
        p_nonowner_rel = multiprocessing.Process(
            target=_release_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                ["protected.txt"],
                "m_b",
                "l_b",
                "a_b",
                q,
            ),
        )
        p_acquire_b = multiprocessing.Process(
            target=_acquire_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                "protected.txt",
                "m_c",
                "l_c",
                "a_c",
                q,
            ),
        )
        p_nonowner_rel.start()
        p_acquire_b.start()
        p_nonowner_rel.join(timeout=30)
        p_acquire_b.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2
        ledger2 = FleetClaimLedger(ledger_path)
        active = ledger2.find_active_claim("protected.txt")
        assert active is not None
        assert active.lane_id == "l_a"
        assert active.mission_id == "m_a"
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        xattr_info = FleetClaimXattr.read_claim(fpath)
        assert xattr_info is not None
        assert xattr_info.lane_id == "l_a"
        events = ledger2.read_all()
        release_refused = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED
        ]
        assert len(release_refused) >= 1

    def test_concurrent_events_have_unique_monotonic_sequences(
        self, tmp_path: Path
    ) -> None:
        file_count = 5
        for i in range(file_count):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"content {i}")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        q: multiprocessing.Queue = multiprocessing.Queue()
        processes = []
        for i in range(file_count):
            p = multiprocessing.Process(
                target=_acquire_worker,
                args=(
                    str(ledger_path),
                    str(tmp_path),
                    f"file_{i}.txt",
                    f"m_{i}",
                    f"l_{i}",
                    f"a_{i}",
                    q,
                ),
            )
            processes.append(p)
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(file_count)]
        assert len(results) == file_count
        assert all(r[0] for r in results)
        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences)
        assert sorted(sequences) == list(range(1, file_count + 1))

    def test_xattr_failure_during_locked_transition_preserves_ledger(
        self, tmp_path: Path
    ) -> None:
        fpath = tmp_path / "resilient2.txt"
        fpath.write_text("resilient content v2")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        proto.acquire_claim(
            paths=["resilient2.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        FleetClaimXattr.clear_claim_xattrs(fpath)
        assert FleetClaimXattr.read_claim(fpath) is None
        active = ledger.find_active_claim("resilient2.txt")
        assert active is not None
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        scanned = proto.scan_claims()
        assert "resilient2.txt" in scanned
        assert scanned["resilient2.txt"].mission_id == "m1"


    def test_public_append_racing_protocol_transition_digest_chain_proof(
        self, tmp_path: Path
    ) -> None:
        """Public append racing acquire: unique sequences, predecessor linkage,
        and recomputed canonical digest for every event.
        """
        fpath = tmp_path / "race_digest.txt"
        fpath.write_text("race digest chain content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)

        from rig_relay.coordination.fleet_claim_corridor import _sha256_event_payload

        # Acquire first event (single-threaded, sequence 1)
        r = proto.acquire_claim(
            paths=["race_digest.txt"], mission_id="m_acq", lane_id="l_acq", agent_id="a_acq"
        )
        assert r.acquired is True

        # Now race public append with protocol transition
        q: multiprocessing.Queue = multiprocessing.Queue()

        p1 = multiprocessing.Process(
            target=_digest_chain_public_append_worker,
            args=(str(ledger_path), q),
        )
        p2 = multiprocessing.Process(
            target=_digest_chain_proto_worker,
            args=(str(ledger_path), str(tmp_path), q),
        )
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)

        results = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2

        events = sorted(ledger.read_all(), key=lambda e: e.event_sequence)
        assert len(events) >= 3

        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences)

        # Verify chain: predecessor linkage and canonical digests
        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]
            assert curr.prior_event_digest == prev.event_digest, (
                f"Chain broken seq={curr.event_sequence}: "
                f"prior={curr.prior_event_digest[:16] if curr.prior_event_digest else 'None'}..., "
                f"expected={prev.event_digest[:16]}..."
            )
            payload = curr.model_dump(exclude={"event_id", "event_digest"})
            expected_digest = _sha256_event_payload(payload)
            assert curr.event_digest == expected_digest, (
                f"Digest mismatch seq={curr.event_sequence}"
            )


    def test_base_hash_captured_during_held_lock_proof(
        self, tmp_path: Path
    ) -> None:
        """Hold the transition lock, mutate the file, release, verify hash."""
        fpath = tmp_path / "hash_proof.txt"
        fpath.write_text("original content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        ledger = FleetClaimLedger(ledger_path)

        q: multiprocessing.Queue = multiprocessing.Queue()
        ready = multiprocessing.Event()

        # Hold the transition lock directly so the subprocess blocks
        ledger._acquire_transition_lock()
        try:
            p = multiprocessing.Process(
                target=_hash_proof_worker,
                args=(str(ledger_path), str(tmp_path), "hash_proof.txt", ready, q),
            )
            p.start()
            ready.wait(timeout=10)

            # Mutate file while subprocess is blocked on lock
            fpath.write_text("mutated content during lock hold")
            mutated_hash = file_sha256(fpath)
        finally:
            ledger._release_transition_lock()

        p.join(timeout=30)
        acquired, prior = q.get(timeout=10)

        assert acquired is True
        assert prior is not None
        assert prior.get("hash_proof.txt") == mutated_hash, (
            f"prior_sha256 must match post-mutation content. "
            f"Expected {mutated_hash[:16]}..., got {prior.get('hash_proof.txt', 'N/A')[:16]}..."
        )


    # ── C0.1 acceptance proofs ────────────────────────────────────────────

    

    
    
    

    


    # ── C0.1 proofs ─────────────────────────────

    def test_stale_xattr_does_not_override_ledger_after_reacquisition(self, tmp_path: Path) -> None:
        fpath = tmp_path / "sp.txt"; fpath.write_text("v1")
        lp = tmp_path / ".rig/relay/fleet/coordination_events.v1.jsonl"
        l = FleetClaimLedger(lp); p = FleetClaimProtocol(l, tmp_path)
        p.acquire_claim(paths=["sp.txt"], mission_id="ma", lane_id="la", agent_id="aa")
        p.release_claim(paths=["sp.txt"], mission_id="ma", lane_id="la", agent_id="aa")
        p.acquire_claim(paths=["sp.txt"], mission_id="mb", lane_id="lb", agent_id="ab")
        si = FleetClaimInfo(mission_id="ma", lane_id="la", agent_id="aa", acquired_at="2020-01-01T00:00:00+00:00", base_sha256={})
        FleetClaimXattr.write_claim(fpath, si)
        sc = p.scan_claims(); assert "sp.txt" in sc; assert sc["sp.txt"].lane_id == "lb"
        p.mirror_to_xattrs()
        xa = FleetClaimXattr.read_claim(fpath); assert xa is not None; assert xa.lane_id == "lb"

    
    def test_prior_sha256_call_is_lexically_inside_transition_lock(self) -> None:
        import textwrap
        source = textwrap.dedent(inspect.getsource(FleetClaimProtocol.acquire_claim))
        tree = ast.parse(source); func_def = tree.body[0]
        try_node = next(n for n in ast.walk(func_def) if isinstance(n, ast.Try))
        lock_found = any("acquire_transition_lock" in ast.unparse(n) for s in func_def.body[:func_def.body.index(try_node)] for n in ast.walk(s) if isinstance(n, ast.Call))
        release_found = any("release_transition_lock" in ast.unparse(n) for s in try_node.finalbody for n in ast.walk(s) if isinstance(n, ast.Call))
        assert lock_found; assert release_found
        ts = min(s.lineno for s in try_node.body if hasattr(s, "lineno"))
        te = max(getattr(s, "end_lineno", s.lineno) for s in try_node.body)
        sc = [n for n in ast.walk(func_def) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "file_sha256"]
        assert len(sc) > 0
        for c in sc: assert ts <= c.lineno <= te
        cl = [n.lineno for n in ast.walk(func_def) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "find_active_claim"]
        sl = [c.lineno for c in sc]
        if cl and sl: assert max(cl) < min(sl)

    
    def test_public_append_contention_burst(self, tmp_path: Path) -> None:
        fc = 3; ac = 3; total = fc + ac
        for i in range(fc): (tmp_path / f"b{i}.txt").write_text(f"c{i}")
        lp = tmp_path / ".rig/relay/fleet/coordination_events.v1.jsonl"
        q = multiprocessing.Queue(); procs = []
        for i in range(fc): procs.append(multiprocessing.Process(target=_acquire_worker, args=(str(lp), str(tmp_path), f"b{i}.txt", f"m{i}", f"l{i}", f"a{i}", q)))
        for i in range(ac): procs.append(multiprocessing.Process(target=_raw_append_worker, args=(str(lp), FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE.value, f"mp{i}", f"lp{i}", f"ap{i}", [f"p{i}.txt"], q)))
        import random; random.shuffle(procs)
        for p in procs: p.start()
        for p in procs: p.join(timeout=60)
        [q.get(timeout=10) for _ in range(total)]
        ledger = FleetClaimLedger(lp); events = ledger.read_all()
        assert len(events) == total
        seqs = [e.event_sequence for e in events]; assert len(set(seqs)) == total; assert sorted(seqs) == list(range(1, total+1))
        for e in events:
            assert e.event_digest == _sha256_event_payload(e.model_dump(exclude={"event_id","event_digest"}))

    

    
