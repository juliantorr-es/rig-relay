"""Tests for the steward coordination bridge.

Validates that the steward emits canonical coordination events through
the existing CoordinationStore, without compiling evidence, traces,
roadmap planning, context projections, or Ralph recommendations into
the wrong authority layer.
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import pytest

from rig_relay.cli._steward._coordination import (
    COORDINATION_ROOT,
    StewardCoordinationBridge,
    _cycle_id,
    _worker_id,
    _workspace_id,
)
from rig_relay.coordination.store import check_ledger_integrity

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.substrate,
    pytest.mark.contract,
    pytest.mark.sabotage,
]


def _read_events(store_root: Path) -> list[dict]:
    events_path = store_root / "events.jsonl"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestBridgeSessionRegistration:
    def test_register_cycle_emits_session_registered_and_cycle_started(
        self, tmp_path: Path
    ) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-test-1"

        session = bridge.register_cycle(
            sess_id, branch="main", head="abc123", lane_id="default"
        )

        assert session.session_id == sess_id
        assert session.agent_profile == "steward"

        events = _read_events(tmp_path / COORDINATION_ROOT)
        event_names = [e["event_name"] for e in events]

        assert "coord.session.registered" in event_names
        assert "steward.cycle.started" in event_names

        found = [e for e in events if e["event_name"] == "steward.cycle.started"]
        assert len(found) == 1
        payload = found[0]["payload"]
        assert payload["branch"] == "main"
        assert payload["head"] == "abc123"

    def test_heartbeat_updates_session_status(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-hb"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.heartbeat(sess_id, "task-a", "executing", current_step="open_loop")

        projection = bridge.store.read_state_projection()
        assert sess_id in projection.active_sessions
        assert projection.active_sessions[sess_id].status == "executing"

    def test_cycle_finished_emits_final_state(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-finished"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_cycle_finished(sess_id, "no_action", 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        event_names = [e["event_name"] for e in events]
        assert "steward.cycle.finished" in event_names

        found = [e for e in events if e["event_name"] == "steward.cycle.finished"]
        assert found[0]["payload"]["final_state"] == "no_action"


class TestClaimLeaseBehavior:
    def test_claim_task_allowed_unless_conflict(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-claim"

        bridge.register_cycle(sess_id, branch="main", head="abc")

        allowed = bridge.claim_task(
            sess_id, "task-a", ["file1.py", "file2.py"], ttl_seconds=600
        )
        assert allowed is True

        allowed_again = bridge.claim_task(
            sess_id, "task-a", ["file1.py"], ttl_seconds=600
        )
        assert allowed_again is True

        events = _read_events(tmp_path / COORDINATION_ROOT)
        claim_events = [e for e in events if e["event_name"] == "coord.task.claimed"]
        assert len(claim_events) >= 1

    def test_reserve_paths_emits_coordination_event(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-reserve"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        allowed = bridge.reserve_paths(
            sess_id, "task-a", ["rig_relay/cli/steward.py"], ttl_seconds=600
        )
        assert allowed is True

        events = _read_events(tmp_path / COORDINATION_ROOT)
        reserved = [e for e in events if e["event_name"] == "coord.path.reserved"]
        assert len(reserved) == 1

    def test_release_paths_cleans_up(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-release"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.reserve_paths(
            sess_id, "task-a", ["rig_relay/cli/steward.py"], ttl_seconds=600
        )
        bridge.release_paths(sess_id, "task-a", ["rig_relay/cli/steward.py"])

        events = _read_events(tmp_path / COORDINATION_ROOT)
        released = [e for e in events if e["event_name"] == "coord.path.released"]
        assert len(released) == 1


class TestBlockedRefusalBehavior:
    def test_record_blocked_emits_conflict_events(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-blocked"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_blocked(sess_id, "task-a", ["dirty_overlap", "failed_gate"])

        events = _read_events(tmp_path / COORDINATION_ROOT)
        conflict_events = [
            e for e in events if e["event_name"] == "coord.conflict.reported"
        ]
        assert len(conflict_events) == 2

        kinds = [e["payload"]["conflict_kind"] for e in conflict_events]
        assert "dirty_overlap" in kinds
        assert "failed_gate" in kinds

    def test_blocked_task_does_not_dispatch(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-no-dispatch"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_blocked(sess_id, "task-b", ["malformed_queue_item"])

        events = _read_events(tmp_path / COORDINATION_ROOT)
        dispatched = [e for e in events if e["event_name"] == "steward.task.dispatched"]
        assert len(dispatched) == 0


class TestArtifactReferencePublication:
    def test_publish_artifact_emits_reference_not_content(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-art"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.publish_artifact_ref(
            sess_id,
            "task-a",
            "steward_capsule",
            ".build/rig-relay/derived/capsule.json",
            "sha256:deadbeef",
            "rig.relay.capsule.v1",
        )

        events = _read_events(tmp_path / COORDINATION_ROOT)
        pub_events = [
            e for e in events if e["event_name"] == "coord.artifact.published"
        ]
        assert len(pub_events) == 1

        payload = pub_events[0]["payload"]
        assert payload["artifact_sha256"] == "sha256:deadbeef"
        assert payload["artifact_uri"] == ".build/rig-relay/derived/capsule.json"
        assert payload["artifact_kind"] == "steward_capsule"
        assert "capsule_payload" not in payload
        assert "capsule_content" not in payload
        assert "raw_prompt" not in payload


class TestCorrelationPropagation:
    def test_events_carry_session_and_task_ids(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-corr"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_task_considered(
            sess_id, "task-c", "Test task", "queued", 5, eligible=True
        )
        bridge.record_dispatch(
            sess_id,
            "task-c",
            "opencode-task-c",
            "sha256:cmdhash",
            dry_run=False,
            stream_mode=True,
        )
        bridge.record_completion(sess_id, "task-c", "opencode-task-c", 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        for event in events:
            if event["event_name"] in (
                "steward.task.considered",
                "steward.task.dispatched",
                "steward.task.completed",
            ):
                assert event.get("task_id") == "task-c", (
                    f"Event {event['event_name']} missing task_id"
                )
                assert event.get("session_id") == sess_id, (
                    f"Event {event['event_name']} missing session_id"
                )

    def test_dispatch_carries_worker_id(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-worker"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_dispatch(
            sess_id,
            "task-d",
            "opencode-task-d",
            "sha256:cmd",
            dry_run=False,
            stream_mode=True,
        )

        events = _read_events(tmp_path / COORDINATION_ROOT)
        dispatch = [e for e in events if e["event_name"] == "steward.task.dispatched"][
            0
        ]
        assert dispatch["payload"]["worker_id"] == "opencode-task-d"
        assert dispatch["payload"]["engine"] == "opencode"


class TestContentLightEnforcement:
    def test_events_do_not_contain_raw_prompt(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-content"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_task_considered(
            sess_id, "task-e", "A task title", "queued", 1, eligible=True
        )
        bridge.record_dispatch(
            sess_id, "task-e", "worker", "sha256:cmd", dry_run=False, stream_mode=True
        )
        bridge.record_completion(sess_id, "task-e", "worker", 0)
        bridge.record_cycle_finished(sess_id, "no_action", 0)
        bridge.record_git_scan(sess_id, "main", "abc", 0, 0, 0, [])
        bridge.record_queue_read(sess_id, 1, 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        for event in events:
            payload_str = json.dumps(event)
            assert "raw_prompt" not in payload_str.lower(), "raw prompt found in event"
            assert "reasoning" not in payload_str.lower(), "reasoning found in event"
            assert "stdout" not in payload_str.lower(), "raw stdout found in event"

        ignored_fields = {
            "session_id",
            "task_id",
            "event_id",
            "event_hash",
            "event_name",
            "created_at",
            "sequence",
            "schema_version",
            "projection_sha256",
            "worker_id",
            "command_sha256",
            "artifact_sha256",
            "task_title_sha256",
            "diagnosis_id",
            "repair_id",
            "dirty_file_hashes",
            "lane_id",
            "blocker_class",
            "blocker_classes",
            "event_kind",
            "engine",
            "exit_code",
            "final_state",
            "status",
            "resolution_kind",
            "conflict_kind",
            "conflict_id",
            "recommended_resolution",
            "path_hashes",
            "scope_path_hashes",
            "authored_at",
            "claim_kind",
            "reservation_mode",
            "reservation_status",
            "ttl_seconds",
            "expires_at",
            "branch",
            "head",
            "mode",
            "kind",
            "path_count",
            "scope_path_count",
            "path_hash",
            "artifact_kind",
            "artifact_uri",
            "other_session_id",
            "queue_item_count",
            "lane_count",
            "eligibility",
            "eligible",
            "dry_run",
            "stream_mode",
            "priority",
            "queue_status",
            "outcome",
            "duration_ms",
            "agent_profile_name",
            "repairable",
            "repair_attempts_so_far",
            "total_attempts",
            "dirty_modified_count",
            "dirty_staged_count",
            "dirty_untracked_count",
            "dirty_file_count",
            "warnings",
            "renewal",
            "last_artifact_sha256",
            "current_step",
            "state_sha256",
        }
        for event in events:
            payload = event.get("payload", {})
            for key in payload:
                assert key in ignored_fields, (
                    f"Unexpected field '{key}' in coordination event "
                    f"'{event['event_name']}'"
                )


class TestRepairDispatch:
    def test_repair_proposed_emits_event(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-repair"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_repair_proposed(
            sess_id,
            "context_capsule_invalid",
            "diag-001",
            repairable=True,
            repair_attempts=0,
        )

        events = _read_events(tmp_path / COORDINATION_ROOT)
        repair_events = [
            e for e in events if e["event_name"] == "steward.repair.proposed"
        ]
        assert len(repair_events) == 1
        p = repair_events[0]["payload"]
        assert p["blocker_class"] == "context_capsule_invalid"
        assert p["repairable"] is True

    def test_repair_dispatched_emits_event(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-repair-dispatch"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_repair_dispatched(
            sess_id, "repair-1", "task-repair", "worker-repair"
        )

        events = _read_events(tmp_path / COORDINATION_ROOT)
        dispatched = [
            e for e in events if e["event_name"] == "steward.repair.dispatched"
        ]
        assert len(dispatched) == 1
        assert dispatched[0]["task_id"] == "task-repair"


class TestWorkerAuthorityBoundary:
    def test_bridge_does_not_expose_task_release_to_workers(self) -> None:
        methods = [
            m
            for m in dir(StewardCoordinationBridge)
            if not m.startswith("_")
            and callable(getattr(StewardCoordinationBridge, m, None))
        ]
        assert "release_task" not in methods, "Workers must not release tasks directly"

    def test_workspace_id_helper_is_deterministic(self, tmp_path: Path) -> None:
        sid1 = _workspace_id(tmp_path)
        sid2 = _workspace_id(tmp_path)
        assert sid1 == sid2
        assert sid1.startswith("rig-")

    def test_worker_id_helper_is_namespaced(self) -> None:
        wid = _worker_id("task-xyz")
        assert wid.startswith("opencode-")
        assert "task-xyz" in wid


class TestRoadmapAuthorityClassification:
    def test_bridge_does_not_create_lanes_authority(self, tmp_path: Path) -> None:
        """The coordination bridge must not establish .rig/roadmap/lanes.jsonl
        as a second authoritative lifecycle ledger.
        """
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-lanes"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.claim_task(sess_id, "task-f", ["file1.py"], ttl_seconds=600)
        bridge.reserve_paths(sess_id, "task-f", ["file1.py"], ttl_seconds=600)

        lanes_path = tmp_path / ".rig" / "roadmap" / "lanes.jsonl"
        assert not lanes_path.exists(), (
            "Coordination bridge must not create a competing lanes authority"
        )

        events = _read_events(tmp_path / COORDINATION_ROOT)
        claim_events = [e for e in events if e["event_name"] == "coord.task.claimed"]
        assert len(claim_events) >= 1, (
            "Task claims should go to coordination store, not lanes.jsonl"
        )


class TestConcurrentStoreSafety:
    def test_concurrent_record_events_do_not_corrupt_ledger(
        self, tmp_path: Path
    ) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-concurrent"

        bridge.register_cycle(sess_id, branch="main", head="abc")

        def _write_git_scan(idx: int) -> None:
            bridge.record_git_scan(sess_id, "main", "abc", idx, 0, 0, [])

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_write_git_scan, range(20)))

        findings = check_ledger_integrity(tmp_path / COORDINATION_ROOT / "events.jsonl")
        malformed = [f for f in findings if f["type"] == "malformed_json"]
        duplicates = [f for f in findings if "duplicate" in f["type"]]
        assert len(malformed) == 0, f"Malformed events: {malformed}"
        assert len(duplicates) == 0, f"Duplicate sequences: {duplicates}"


class TestContextDigesterIntegration:
    def test_context_digester_sees_steward_sessions(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "steward-cd"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.heartbeat(sess_id, "task-g", "executing", current_step="open_loop")

        from rig_relay.context.digester import ContextDigester

        digester = ContextDigester()
        result = digester.digest(
            str(tmp_path / COORDINATION_ROOT), str(tmp_path), gate_path=None
        )

        assert result.active_lane_count >= 1
        session_ids = [lane["session_id"] for lane in result.active_lanes]
        assert sess_id in session_ids


class TestClaimRefusalBlocksDispatch:
    def test_claim_refused_emits_refusal_event(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_a = "claim-test-a"
        sess_b = "claim-test-b"

        bridge.register_cycle(sess_a, branch="main", head="abc")
        bridge.register_cycle(sess_b, branch="main", head="abc")

        first = bridge.claim_task(sess_a, "task-x", ["file.py"], ttl_seconds=600)
        assert first is True

        second = bridge.claim_task(sess_b, "task-x", ["file.py"], ttl_seconds=600)
        assert second is False

        events = _read_events(tmp_path / COORDINATION_ROOT)
        refusal_events = [
            e for e in events if e["event_name"] == "steward.task.claim_refused"
        ]
        assert len(refusal_events) >= 1

    def test_reservation_refused_emits_refusal_event(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_a = "reserve-test-a"
        sess_b = "reserve-test-b"

        bridge.register_cycle(sess_a, branch="main", head="abc")
        bridge.claim_task(sess_a, "task-y", ["shared_file.py"], ttl_seconds=600)
        bridge.reserve_paths(sess_a, "task-y", ["shared_file.py"], ttl_seconds=600)

        bridge.register_cycle(sess_b, branch="main", head="abc")
        bridge.claim_task(sess_b, "task-z", ["shared_file.py"], ttl_seconds=600)
        result = bridge.reserve_paths(
            sess_b, "task-z", ["shared_file.py"], ttl_seconds=600
        )
        assert result is False

        events = _read_events(tmp_path / COORDINATION_ROOT)
        refusal_events = [
            e for e in events if e["event_name"] == "steward.task.reservation_refused"
        ]
        assert len(refusal_events) >= 1


class TestDryRunNoPollution:
    def test_dry_run_cycle_leaves_coordination_events_but_no_durable_claims(
        self, tmp_path: Path
    ) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "dry-test-1"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_dispatch(
            sess_id,
            "task-dry",
            "worker-dry",
            "sha256:cmd",
            dry_run=True,
            stream_mode=True,
        )
        bridge.record_cycle_finished(sess_id, "advance_to_next_lane", 0)

        projection = bridge.store.read_state_projection()
        assert "task-dry" not in projection.active_task_claims


class TestTraceIdPropagation:
    def test_trace_id_appears_in_steward_events(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        bridge.set_trace_id("trace-abc-123")
        sess_id = "trace-test"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_git_scan(sess_id, "main", "abc", 0, 0, 0, [])
        bridge.record_queue_read(sess_id, 1, 0)
        bridge.record_cycle_finished(sess_id, "no_action", 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        for event in events:
            name = event["event_name"]
            if name in ("coord.session.registered", "coord.session.heartbeat"):
                continue
            payload = event.get("payload", {})
            assert payload.get("trace_id") == "trace-abc-123", (
                f"Event {name} missing trace_id"
            )

    def test_events_without_trace_id_set_do_not_inject_empty(
        self, tmp_path: Path
    ) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "no-trace-test"

        bridge.register_cycle(sess_id, branch="main", head="abc")
        bridge.record_cycle_finished(sess_id, "no_action", 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        good_events = [e for e in events if e["event_name"] == "steward.cycle.started"]
        assert len(good_events) == 1
        assert "trace_id" not in good_events[0].get("payload", {})


class TestEventNameValidation:
    def test_rejects_unrecognized_event_name(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "bad-event-test"
        bridge.register_cycle(sess_id, branch="main", head="abc")

        with pytest.raises(ValueError, match="Rejected steward event name"):
            bridge._record("steward.random.thing", sess_id, {})

    def test_all_registered_event_names_pass_validation(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_id = "all-names-test"
        bridge.register_cycle(sess_id, branch="main", head="abc")

        bridge.record_git_scan(sess_id, "main", "abc", 0, 0, 0, [])
        bridge.record_queue_read(sess_id, 1, 0)
        bridge.record_task_considered(sess_id, "t", "title", "queued", 1, True)
        bridge.record_dispatch(
            sess_id, "t", "w", "sha256:cmd", dry_run=True, stream_mode=True
        )
        bridge.record_completion(sess_id, "t", "w", 0)
        bridge.record_cycle_finished(sess_id, "done", 0)

        events = _read_events(tmp_path / COORDINATION_ROOT)
        steward_events = [e for e in events if e["event_name"].startswith("steward.")]
        assert len(steward_events) >= 6

    def test_claim_refused_event_name_is_validated(self, tmp_path: Path) -> None:
        bridge = StewardCoordinationBridge(tmp_path)
        sess_a = "validate-refused"
        sess_b = "validate-refused-b"

        bridge.register_cycle(sess_a, branch="main", head="abc")
        bridge.register_cycle(sess_b, branch="main", head="abc")

        first = bridge.claim_task(sess_a, "task-v", ["f.py"], ttl_seconds=600)
        assert first is True
        second = bridge.claim_task(sess_b, "task-v", ["f.py"], ttl_seconds=600)
        assert second is False

        events = _read_events(tmp_path / COORDINATION_ROOT)
        refused = [e for e in events if e["event_name"] == "steward.task.claim_refused"]
        assert len(refused) == 1
        assert refused[0]["task_id"] == "task-v"


class TestCycleIdUniqueness:
    def test_cycle_ids_are_unique_per_invocation(self) -> None:
        c1 = _cycle_id()
        c2 = _cycle_id()
        c3 = _cycle_id()
        ids = {c1, c2, c3}
        assert len(ids) == 3
        assert all(len(c) == 16 for c in ids)
