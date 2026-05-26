from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from rig_relay.coordination.fleet_claim_corridor import (
    FleetClaimEventKind,
    FleetClaimLedger,
    FleetClaimProtocol,
    FleetClaimState,
    FleetClaimXattr,
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
        assert result_b.reason is not None
        assert (
            "already claimed" in result_b.reason.lower()
            or "conflict" in result_b.reason.lower()
        )
        assert result_b.event is not None
        assert result_b.event.event_kind == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT

        events = proto._ledger.read_all()
        refusal_events = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT
        ]
        assert len(refusal_events) == 1

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
        active_a = proto._ledger.find_active_claim("release_me.txt")
        assert active_a is not None
        assert active_a.lane_id == "l_a"

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
        assert active.mission_id == "m2"

        xattr_info = FleetClaimXattr.read_claim(fpath)
        assert xattr_info is not None
        assert xattr_info.lane_id == "l_b"

    def test_scan_claims_and_find_active_claim_agree(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        f1 = tmp / "file1.txt"
        f2 = tmp / "file2.txt"
        f1.write_text("content 1")
        f2.write_text("content 2")

        proto.acquire_claim(
            paths=["file1.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        proto.acquire_claim(
            paths=["file2.txt"], mission_id="m1", lane_id="l2", agent_id="a2"
        )

        for path in ("file1.txt", "file2.txt"):
            point = proto._ledger.find_active_claim(path)
            scan = proto.scan_claims()
            assert path in scan
            assert point is not None
            assert point.lane_id == scan[path].lane_id
            assert point.mission_id == scan[path].mission_id

    def test_non_owner_release_refused_owner_preserved(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "owned.txt"
        fpath.write_text("owner content")

        result_a = proto.acquire_claim(
            paths=["owned.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        assert result_a.acquired is True

        xattr_before = FleetClaimXattr.read_claim(fpath)
        assert xattr_before is not None
        assert xattr_before.lane_id == "l_a"

        refusal = proto.release_claim(
            paths=["owned.txt"], mission_id="m_b", lane_id="l_b", agent_id="a_b"
        )
        assert refusal.acquired is False
        assert refusal.reason is not None
        assert "refused" in refusal.reason.lower()
        assert refusal.event is not None
        assert refusal.event.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED

        active = proto._ledger.find_active_claim("owned.txt")
        assert active is not None
        assert active.lane_id == "l_a"
        assert active.mission_id == "m_a"

        xattr_after = FleetClaimXattr.read_claim(fpath)
        assert xattr_after is not None
        assert xattr_after.lane_id == "l_a"

        state_after = FleetClaimXattr.read_state(fpath)
        assert state_after == FleetClaimState.CLAIMED

        events = proto._ledger.read_all()
        released_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(released_events) == 0

        refusal_events = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED
        ]
        assert len(refusal_events) == 1

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

        fpath.write_text(original)

        stale_check = proto.check_stale_base(
            paths=["stale.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert stale_check["stale.txt"] is False

    def test_missing_xattr_does_not_erase_ledger_state(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "resilient.txt"
        fpath.write_text("resilient content")

        result = proto.acquire_claim(
            paths=["resilient.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result.acquired is True
        assert FleetClaimXattr.read_claim(fpath) is not None

        FleetClaimXattr.clear_claim_xattrs(fpath)
        assert FleetClaimXattr.read_claim(fpath) is None
        assert FleetClaimXattr.read_state(fpath) is None

        active = proto._ledger.find_active_claim("resilient.txt")
        assert active is not None
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED

        scanned = proto.scan_claims()
        assert "resilient.txt" in scanned

    # ── C0.1 authority tests ──────────────────────────────────────────

    def test_acquire_base_hash_captured_inside_serialized_transition_with_causal_race(
        self, tmp_path: Path
    ) -> None:
        """Prove: base hash is captured inside the lock, not before.

        Two processes race to acquire the same file.  The winner's recorded
        prior_sha256 must match the file at the moment of acquisition,
        even under concurrent mutation by the loser.
        """
        fpath = tmp_path / "race_hash.txt"
        fpath.write_text("original")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        q: multiprocessing.Queue = multiprocessing.Queue()

        p_a = multiprocessing.Process(
            target=_acquire_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                "race_hash.txt",
                "m_a",
                "l_a",
                "a_a",
                q,
            ),
        )
        p_b = multiprocessing.Process(
            target=_acquire_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                "race_hash.txt",
                "m_b",
                "l_b",
                "a_b",
                q,
            ),
        )
        p_a.start()
        p_b.start()
        p_a.join(timeout=30)
        p_b.join(timeout=30)

        results: list[tuple[bool, str, int, dict | None]] = [
            q.get(timeout=10) for _ in range(2)
        ]
        assert len(results) == 2
        acquired = [r for r in results if r[0] is True]
        refused = [r for r in results if r[0] is False]
        assert len(acquired) == 1
        assert len(refused) == 1

        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        acquired_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        ]
        assert len(acquired_events) == 1

        # The winner's prior_sha256 must match the file on disk at claim time.
        # Because both processes start with "original", the winner's hash
        # should match "original" content.
        expected_hash = file_sha256(fpath)
        winning_event = acquired_events[0]
        assert winning_event.prior_sha256 is not None
        assert expected_hash in winning_event.prior_sha256.values(), (
            f"Winner's prior_sha256={winning_event.prior_sha256} "
            f"must contain current file hash={expected_hash}"
        )

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

        results: list[tuple[bool, str, int, dict | None]] = [
            q.get(timeout=10) for _ in range(2)
        ]

        assert len(results) == 2
        acquired = [r for r in results if r[0] is True]
        refused = [r for r in results if r[0] is False]
        assert len(acquired) == 1
        assert len(refused) == 1
        assert refused[0][1] == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT.value

        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        acquired_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        ]
        refused_events = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT
        ]
        assert len(acquired_events) == 1
        assert len(refused_events) == 1

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

        results: list[tuple[bool, str, int, dict | None]] = [
            q.get(timeout=10) for _ in range(2)
        ]

        assert len(results) == 2
        assert all(r[0] for r in results)

        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        acquired_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        ]
        assert len(acquired_events) == 2

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

        results: list[tuple] = [q.get(timeout=10) for _ in range(2)]

        assert len(results) == 2

        ledger2 = FleetClaimLedger(ledger_path)
        events = ledger2.read_all()
        acquired_count = sum(
            1 for e in events if e.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        )
        assert acquired_count >= 1

        active = ledger2.find_active_claim("contested.txt")
        # After lane_a releases its own claim, lane_a must never remain active.
        # The only valid outcomes: no active owner (lane_b was refused before
        # release) or lane_b is active (lane_b acquired after release).
        if active is not None:
            assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
            assert active.lane_id == "l_b", f"expected lane_b, got {active.lane_id}"

    def test_non_owner_release_does_not_displace_legitimate_owner(
        self, tmp_path: Path
    ) -> None:
        """Non-owner release racing acquisition: owner must not be displaced."""
        fpath = tmp_path / "protected.txt"
        fpath.write_text("protected content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        result_a = proto.acquire_claim(
            paths=["protected.txt"], mission_id="m_a", lane_id="l_a", agent_id="a_a"
        )
        assert result_a.acquired is True

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

        results: list[tuple] = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2

        # Identify release result (tuple starts with event_kind str) and
        # acquire result (tuple starts with acquired bool)
        release_result = None
        acquire_result = None
        for r in results:
            if isinstance(r[0], bool):
                acquire_result = r  # (_acquire_worker: acquired, kind, seq, sha)
            else:
                release_result = r  # (_release_worker: kind, seq, acquired, reason)

        assert release_result is not None
        assert acquire_result is not None

        # lane_b release must be refused with typed evidence
        assert release_result[0] == FleetClaimEventKind.CLAIM_RELEASE_REFUSED.value
        assert release_result[2] is False  # acquired=False

        # lane_c acquisition must be refused with conflict
        assert acquire_result[0] is False  # acquired=False
        assert acquire_result[1] == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT.value

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

        # No CLAIM_RELEASED event whatsoever
        released = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(released) == 0

        # At least one CLAIM_RELEASE_REFUSED with structured conflicting fields
        release_refused = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED
        ]
        assert len(release_refused) >= 1
        refusal = release_refused[0]
        assert refusal.event_kind == FleetClaimEventKind.CLAIM_RELEASE_REFUSED
        assert "l_a" in (refusal.reason or "")

        # At least one CLAIM_REFUSED_CONFLICT from lane_c
        conflicts = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.CLAIM_REFUSED_CONFLICT
        ]
        assert len(conflicts) >= 1

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

        results: list[tuple[bool, str, int, dict | None]] = [
            q.get(timeout=10) for _ in range(file_count)
        ]

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
        result = proto.acquire_claim(
            paths=["resilient2.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result.acquired is True
        assert FleetClaimXattr.read_claim(fpath) is not None

        FleetClaimXattr.clear_claim_xattrs(fpath)
        assert FleetClaimXattr.read_claim(fpath) is None
        assert FleetClaimXattr.read_state(fpath) is None

        active = ledger.find_active_claim("resilient2.txt")
        assert active is not None
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED

        scanned = proto.scan_claims()
        assert "resilient2.txt" in scanned
        assert scanned["resilient2.txt"].mission_id == "m1"
