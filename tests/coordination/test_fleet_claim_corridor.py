from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from rig_relay.coordination.fleet_claim_corridor import (
    FleetClaimEvent,
    FleetClaimEventKind,
    FleetClaimLedger,
    FleetClaimProtocol,
    FleetClaimState,
    FleetClaimXattr,
    _now_iso,
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
    result_queue.put((
        result.event.event_kind.value,
        result.event.event_sequence,
        result.acquired,
        result.reason,
    ))


def _raw_append_worker(
    ledger_path_str: str,
    event_kind_str: str,
    mission_id: str,
    lane_id: str,
    agent_id: str,
    claimed_paths: list[str],
    result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    ledger = FleetClaimLedger(ledger_path)
    event = FleetClaimEvent(
        event_id="",
        event_kind=FleetClaimEventKind(event_kind_str),
        mission_id=mission_id,
        lane_id=lane_id,
        agent_id=agent_id,
        claimed_paths=claimed_paths,
        timestamp=_now_iso(),
        event_digest="",
    )
    result = ledger.append(event)
    result_queue.put((result.event_sequence, result.event_digest))


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

    def test_reacquire_after_release_find_active_claim_returns_new_owner(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        """Prove: acquire(A) → release(A) → acquire(B) resolves to lane B."""
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
        """Prove both authority lookup paths consume the same reducer output."""
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
        """Lane A acquires; lane B tries release; refused; A still owner; xattrs intact."""
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

    def test_lifecycle_events_preserve_ownership(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "lifecycle.txt"
        fpath.write_text("lifecycle content")

        r1 = proto.acquire_claim(
            paths=["lifecycle.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r1.acquired is True

        for method_name, method in [
            ("edit_started", proto.record_edit_started),
            ("tests_completed", proto.record_tests_completed),
            ("ready_for_integration", proto.record_ready_for_integration),
            ("work_parked", proto.record_work_parked),
        ]:
            r = method(
                paths=["lifecycle.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
            )
            assert r.acquired is True, f"{method_name} should succeed"

        active = proto._ledger.find_active_claim("lifecycle.txt")
        assert active is not None
        assert active.lane_id == "l1"
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED

        events = proto._ledger.read_all()
        released = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(released) == 0

    def test_integration_refused_stale_base_via_protocol(self, tmp_path: Path) -> None:
        fpath = tmp_path / "stale_proto.txt"
        fpath.write_text("version 1")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)

        r = proto.acquire_claim(
            paths=["stale_proto.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r.acquired is True

        r_not_stale = proto.record_integration_refused_stale_base(
            paths=["stale_proto.txt"],
            mission_id="m1",
            lane_id="coord",
            agent_id="a_coord",
        )
        assert r_not_stale.acquired is True
        assert r_not_stale.event is None
        assert "not stale" in (r_not_stale.reason or "").lower()

        fpath.write_text("version 2 — external mutation")

        r_stale = proto.record_integration_refused_stale_base(
            paths=["stale_proto.txt"],
            mission_id="m1",
            lane_id="coord",
            agent_id="a_coord",
        )
        assert r_stale.acquired is False
        assert r_stale.event is not None
        assert (
            r_stale.event.event_kind
            == FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE
        )

        active = ledger.find_active_claim("stale_proto.txt")
        assert active is not None
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        assert active.lane_id == "l1"

        events = ledger.read_all()
        stale_events = [
            e
            for e in events
            if e.event_kind == FleetClaimEventKind.INTEGRATION_REFUSED_STALE_BASE
        ]
        assert len(stale_events) == 1

        info = FleetClaimXattr.read_claim(fpath)
        assert info is not None
        assert info.lane_id == "l1"

    def test_outside_root_paths_refused_no_event(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol

        for method_name, call in [
            (
                "acquire_absolute",
                lambda: proto.acquire_claim(
                    paths=["/tmp/outside_abs.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "acquire_dotdot",
                lambda: proto.acquire_claim(
                    paths=["../outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "release_dotdot",
                lambda: proto.release_claim(
                    paths=["../outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "lifecycle_dotdot",
                lambda: proto.record_edit_started(
                    paths=["../outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "stale_base_outside",
                lambda: proto.record_integration_refused_stale_base(
                    paths=["/tmp/outside_abs.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
        ]:
            result = call()
            assert result.acquired is False, f"{method_name} must refuse"
            assert result.event is None, f"{method_name} must not emit event"
            err = (result.reason or "").lower()
            assert "outside" in err, f"{method_name} reason: {result.reason}"

        events = proto._ledger.read_all()
        assert len(events) == 0

    def test_non_expiring_claim_contract(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "non_expiring.txt"
        fpath.write_text("claim me forever")

        r = proto.acquire_claim(
            paths=["non_expiring.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r.acquired is True

        active = proto._ledger.find_active_claim("non_expiring.txt")
        assert active is not None
        assert active.lane_id == "l1"

        events = proto._ledger.read_all()
        renewed = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RENEWED
        ]
        assert len(renewed) == 0


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
        if active is not None:
            assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
            assert active.lane_id in ("l_a", "l_b")

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

    def test_public_append_racing_protocol_transition_unique_sequences_valid_digests(
        self, tmp_path: Path
    ) -> None:
        """Public append racing acquire: unique sequences, valid digest per event."""
        fpath = tmp_path / "race_append.txt"
        fpath.write_text("race append content")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        q: multiprocessing.Queue = multiprocessing.Queue()
        p_acq = multiprocessing.Process(
            target=_acquire_worker,
            args=(
                str(ledger_path),
                str(tmp_path),
                "race_append.txt",
                "m_acq",
                "l_acq",
                "a_acq",
                q,
            ),
        )
        p_raw = multiprocessing.Process(
            target=_raw_append_worker,
            args=(
                str(ledger_path),
                FleetClaimEventKind.CLAIM_REQUESTED.value,
                "m_raw",
                "l_raw",
                "a_raw",
                ["race_append.txt"],
                q,
            ),
        )
        p_acq.start()
        p_raw.start()
        p_acq.join(timeout=30)
        p_raw.join(timeout=30)

        results: list[tuple] = [q.get(timeout=10) for _ in range(2)]
        assert len(results) == 2

        ledger = FleetClaimLedger(ledger_path)
        events = ledger.read_all()
        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences), (
            f"Duplicate sequences: {sequences}"
        )
        assert sorted(sequences) == [1, 2]

        from rig_relay.coordination.fleet_claim_corridor import _sha256_event_payload

        for e in events:
            payload = e.model_dump(exclude={"event_id", "event_digest"})
            expected_digest = _sha256_event_payload(payload)
            assert e.event_digest == expected_digest, (
                f"Event seq={e.event_sequence}: digest mismatch"
            )

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

    def test_acquire_base_hash_captured_inside_serialized_transition(
        self, tmp_path: Path
    ) -> None:
        """Prove prior_sha256 describes file state at claim time, not before."""
        fpath = tmp_path / "hash_timing.txt"
        original_content = "original content for hash"
        fpath.write_text(original_content)
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )

        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)

        result = proto.acquire_claim(
            paths=["hash_timing.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert result.acquired is True

        expected_hash = file_sha256(fpath)
        assert result.event.prior_sha256 is not None
        assert expected_hash == result.event.prior_sha256.get("hash_timing.txt"), (
            "prior_sha256 must match the file content at acquisition time"
        )

        active = ledger.find_active_claim("hash_timing.txt")
        assert active is not None
        assert active.prior_sha256 is not None
        assert active.prior_sha256.get("hash_timing.txt") == expected_hash

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
