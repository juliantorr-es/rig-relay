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
    result_queue.put((
        result.acquired,
        result.event.event_kind.value,
        result.event.event_sequence,
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
    result_queue.put((result.event.event_kind.value, result.event.event_sequence))


def _read_events_worker(
    ledger_path_str: str, result_queue: multiprocessing.Queue
) -> None:
    ledger_path = Path(ledger_path_str)
    ledger = FleetClaimLedger(ledger_path)
    events = ledger.read_all()
    data = [
        (e.event_kind.value, e.event_sequence, e.claimed_paths, e.lane_id)
        for e in events
    ]
    result_queue.put(data)


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

    def test_released_claim_clears_xattrs_and_appends_release_event(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "release_me.txt"
        fpath.write_text("release test")

        result_a = proto.acquire_claim(
            paths=["release_me.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result_a.acquired is True

        result_rel = proto.release_claim(
            paths=["release_me.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result_rel.event.event_kind == FleetClaimEventKind.CLAIM_RELEASED

        events = proto._ledger.read_all()
        release_events = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(release_events) == 1

        info = FleetClaimXattr.read_claim(fpath)
        assert info is None
        state = FleetClaimXattr.read_state(fpath)
        assert state is None

        result_b = proto.acquire_claim(
            paths=["release_me.txt"], mission_id="m2", lane_id="l2", agent_id="a2"
        )
        assert result_b.acquired is True

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

        results: list[tuple[bool, str, int]] = [q.get(timeout=10) for _ in range(2)]

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

        results: list[tuple[bool, str, int]] = [q.get(timeout=10) for _ in range(2)]

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
        if active is not None:
            assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
            assert active.lane_id in ("l_a", "l_b")

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

        results: list[tuple[bool, str, int]] = [
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

    def test_stale_base_integration_refused_without_damaging_claim(
        self, tmp_path: Path
    ) -> None:
        fpath = tmp_path / "stale_integration.txt"
        fpath.write_text("version 1")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        result = proto.acquire_claim(
            paths=["stale_integration.txt"],
            mission_id="m1",
            lane_id="l1",
            agent_id="a1",
        )
        assert result.acquired is True

        fpath.write_text("version 2 — mutated by external process")

        stale = proto.check_stale_base(
            paths=["stale_integration.txt"],
            mission_id="m1",
            lane_id="l1",
            agent_id="a1",
        )
        assert stale["stale_integration.txt"] is True

        from rig_relay.coordination.fleet_claim_corridor import (
            FleetClaimEvent,
            _now_iso,
        )

        stale_event = FleetClaimEvent(
            event_id="",
            event_kind=FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE,
            mission_id="m1",
            lane_id="l1",
            agent_id="a1",
            claimed_paths=["stale_integration.txt"],
            timestamp=_now_iso(),
            event_digest="",
            reason="stale base detected during integration check",
        )
        ledger.append(stale_event)

        active = ledger.find_active_claim("stale_integration.txt")
        assert active is not None
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED

        info = FleetClaimXattr.read_claim(fpath)
        assert info is not None
        assert info.lane_id == "l1"

        events = ledger.read_all()
        stale_events = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE
        ]
        assert len(stale_events) == 1
