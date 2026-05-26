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


def _lifecycle_worker(
    ledger_path_str: str,
    repo_root_str: str,
    paths: list[str],
    mission_id: str,
    lane_id: str,
    agent_id: str,
    method: str,
    result_queue: multiprocessing.Queue,
) -> None:
    ledger_path = Path(ledger_path_str)
    repo_root = Path(repo_root_str)
    ledger = FleetClaimLedger(ledger_path)
    proto = FleetClaimProtocol(ledger, repo_root)
    result = {  # type: ignore[assignment]
        "edit_started": proto.record_edit_started(
            paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
        ),
        "tests_completed": proto.record_tests_completed(
            paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
        ),
        "ready_for_integration": proto.record_ready_for_integration(
            paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
        ),
        "work_parked": proto.record_work_parked(
            paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
        ),
    }.get(
        method,
        proto.acquire_claim(
            paths=paths, mission_id=mission_id, lane_id=lane_id, agent_id=agent_id
        ),
    )
    ev = result.event
    result_queue.put((
        result.acquired,
        ev.event_kind.value if ev is not None else "no_event",
        ev.event_sequence if ev is not None else 0,
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

    def test_acquire_base_hash_inside_lock_causal_race(self, tmp_path: Path) -> None:
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
        results = [q.get(timeout=10) for _ in range(2)]
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
        expected_hash = file_sha256(fpath)
        winning_event = acquired_events[0]
        assert winning_event.prior_sha256 is not None
        assert expected_hash in winning_event.prior_sha256.values()

    def test_lifecycle_events_preserve_ownership(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "lifecycle.txt"
        fpath.write_text("lifecycle content")
        proto.acquire_claim(
            paths=["lifecycle.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        for method in [
            proto.record_edit_started,
            proto.record_tests_completed,
            proto.record_ready_for_integration,
            proto.record_work_parked,
        ]:
            r = method(
                paths=["lifecycle.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
            )
            assert r.acquired is True
        active = proto._ledger.find_active_claim("lifecycle.txt")
        assert active is not None
        assert active.lane_id == "l1"
        assert active.event_kind == FleetClaimEventKind.CLAIM_ACQUIRED
        events = proto._ledger.read_all()
        released = [
            e for e in events if e.event_kind == FleetClaimEventKind.CLAIM_RELEASED
        ]
        assert len(released) == 0

    def test_work_parked_preserves_claim_xattr(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "parked.txt"
        fpath.write_text("park me")
        proto.acquire_claim(
            paths=["parked.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        r = proto.record_work_parked(
            paths=["parked.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r.acquired is True
        claim_info = FleetClaimXattr.read_claim(fpath)
        assert claim_info is not None
        assert claim_info.lane_id == "l1"
        state = FleetClaimXattr.read_state(fpath)
        assert state == FleetClaimState.PARKED
        active = proto._ledger.find_active_claim("parked.txt")
        assert active is not None
        assert active.lane_id == "l1"

    def test_concurrent_lifecycle_events_via_subprocess(self, tmp_path: Path) -> None:
        fpath = tmp_path / "concurrent_lc.txt"
        fpath.write_text("concurrent lifecycle")
        ledger_path = (
            tmp_path / ".rig" / "relay" / "fleet" / "coordination_events.v1.jsonl"
        )
        ledger = FleetClaimLedger(ledger_path)
        proto = FleetClaimProtocol(ledger, tmp_path)
        r = proto.acquire_claim(
            paths=["concurrent_lc.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r.acquired is True
        q: multiprocessing.Queue = multiprocessing.Queue()
        methods = [
            "edit_started",
            "tests_completed",
            "ready_for_integration",
            "work_parked",
        ]
        processes = []
        for method in methods:
            p = multiprocessing.Process(
                target=_lifecycle_worker,
                args=(
                    str(ledger_path),
                    str(tmp_path),
                    ["concurrent_lc.txt"],
                    "m1",
                    "l1",
                    "a1",
                    method,
                    q,
                ),
            )
            processes.append(p)
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=30)
        results = [q.get(timeout=10) for _ in range(len(methods))]
        assert len(results) == len(methods)
        assert all(r[0] for r in results)
        events = ledger.read_all()
        lifecycle_events = [
            e
            for e in events
            if e.event_kind
            in {
                FleetClaimEventKind.EDIT_STARTED,
                FleetClaimEventKind.TESTS_COMPLETED,
                FleetClaimEventKind.READY_FOR_INTEGRATION,
                FleetClaimEventKind.WORK_PARKED,
            }
        ]
        assert len(lifecycle_events) == len(methods)
        sequences = [e.event_sequence for e in events]
        assert len(set(sequences)) == len(sequences)
        assert sorted(sequences) == list(range(1, len(events) + 1))
        active = ledger.find_active_claim("concurrent_lc.txt")
        assert active is not None
        assert active.lane_id == "l1"

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
            paths=["stale_proto.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
        assert r_not_stale.acquired is True
        assert r_not_stale.event is None
        r_foreign = proto.record_integration_refused_stale_base(
            paths=["stale_proto.txt"],
            mission_id="m1",
            lane_id="coord",
            agent_id="a_coord",
        )
        assert r_foreign.acquired is False
        assert r_foreign.event is None
        fpath.write_text("version 2 — external mutation")
        r_stale = proto.record_integration_refused_stale_base(
            paths=["stale_proto.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
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
        for label, call in [
            (
                "abs_acquire",
                lambda: proto.acquire_claim(
                    paths=["/tmp/outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "dotdot_acquire",
                lambda: proto.acquire_claim(
                    paths=["../outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
            (
                "dotdot_release",
                lambda: proto.release_claim(
                    paths=["../outside.txt"],
                    mission_id="m1",
                    lane_id="l1",
                    agent_id="a1",
                ),
            ),
        ]:
            result = call()
            assert result.acquired is False, label
            assert result.event is None, label
            assert "outside" in (result.reason or "").lower(), label
        events = proto._ledger.read_all()
        assert len(events) == 0

    def test_non_expiring_claim_contract(
        self, protocol: tuple[FleetClaimProtocol, Path]
    ) -> None:
        proto, tmp = protocol
        fpath = tmp / "non_expiring.txt"
        fpath.write_text("claim me forever")
        proto.acquire_claim(
            paths=["non_expiring.txt"], mission_id="m1", lane_id="l1", agent_id="a1"
        )
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
