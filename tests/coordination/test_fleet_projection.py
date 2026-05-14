"""Tests for FleetProjection — content-light fleet coordination read model."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.coordination.fleet_projection import (
    FleetAgentSummary,
    FleetBlockerSummary,
    FleetLeaseSummary,
    FleetPatchProposalSummary,
    FleetProjection,
    FleetQueueNextItem,
    FleetQueueSummary,
    FleetReplayDiagnostics,
    build_fleet_projection,
    build_lease_summary,
    build_patch_proposal_summary,
    build_queue_summary,
    build_queue_summary_from_snapshot,
)
from rig_relay.coordination.fleet_queue import (
    FleetQueue,
    FleetQueueItem,
    FleetQueueItemKind,
    FleetQueueReplayReport,
    FleetQueueSnapshot,
)
from rig_relay.coordination.lease_manager import PathLeaseManager

_FORBIDDEN_RAW = frozenset({
    "prompt",
    "stdout",
    "stderr",
    "content",
    "diff",
    "patch",
    "secret",
    "argv",
    "snippet",
    "file_content",
    "raw_prompt",
    "raw_output",
})

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


class TestFleetProjectionModel:
    """FleetProjection model tests."""

    def test_minimal_projection(self) -> None:
        proj = build_fleet_projection()
        assert proj.schema_version == "rig.fleet.projection.v1"
        assert proj.fleet_name == "default"
        assert isinstance(proj.agents, FleetAgentSummary)
        assert isinstance(proj.queue, FleetQueueSummary)
        assert isinstance(proj.leases, FleetLeaseSummary)
        assert isinstance(proj.blockers, FleetBlockerSummary)
        assert isinstance(proj.patches, FleetPatchProposalSummary)
        assert proj.agents.total_agents == 0
        assert proj.queue.total == 0
        assert proj.leases.total_active == 0
        assert proj.blockers.total_blockers == 0
        assert proj.patches.total == 0
        assert proj.recent_event_count == 0

    def test_filled_projection(self) -> None:
        proj = build_fleet_projection(
            projection_id="fp-test-001",
            created_at="2026-01-15T10:00:00",
            agents=FleetAgentSummary(
                total_agents=2, active_sessions=1, recent_heartbeats=5, stale_sessions=0
            ),
            queue=FleetQueueSummary(
                queued=3, running=1, completed=10, total=15, highest_priority=5
            ),
            leases=FleetLeaseSummary(
                total_active=4, exclusive_write=3, shared_read=1, path_count=12
            ),
            blockers=FleetBlockerSummary(
                total_blockers=2,
                blocker_kinds={"dirty_files": 1, "policy_guard": 1},
                oldest_blocked_at="2026-01-15T09:00:00",
            ),
            patches=FleetPatchProposalSummary(
                pending=2, applied=1, total=3, oldest_pending_at="2026-01-14T10:00:00"
            ),
            recent_event_count=42,
        )
        assert proj.projection_id == "fp-test-001"
        assert proj.created_at == "2026-01-15T10:00:00"
        assert proj.agents.total_agents == 2
        assert proj.queue.queued == 3
        assert proj.leases.total_active == 4
        assert proj.leases.exclusive_write == 3
        assert proj.blockers.total_blockers == 2
        assert proj.patches.pending == 2
        assert proj.recent_event_count == 42

    def test_projection_id_auto_generated(self) -> None:
        proj = build_fleet_projection()
        assert proj.projection_id.startswith("fp-")
        assert len(proj.projection_id) == 19  # "fp-" + 16 hex chars

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            FleetProjection.model_validate({
                "schema_version": "rig.fleet.projection.v1",
                "projection_id": "fp-001",
                "created_at": "2026-01-01T00:00:00",
                "fleet_name": "test",
                "agents": {
                    "total_agents": 0,
                    "active_sessions": 0,
                    "recent_heartbeats": 0,
                    "stale_sessions": 0,
                },
                "queue": {
                    "queued": 0,
                    "running": 0,
                    "blocked": 0,
                    "completed": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "total": 0,
                    "highest_priority": 0,
                },
                "leases": {
                    "total_active": 0,
                    "exclusive_write": 0,
                    "shared_read": 0,
                    "stale": 0,
                    "expired": 0,
                    "path_count": 0,
                },
                "blockers": {
                    "total_blockers": 0,
                    "blocker_kinds": {},
                    "oldest_blocked_at": None,
                },
                "patches": {
                    "pending": 0,
                    "applied": 0,
                    "rejected": 0,
                    "revised": 0,
                    "total": 0,
                    "oldest_pending_at": None,
                    "latest_proposal_id": None,
                },
                "raw_output": "should_not_exist",
            })

    def test_content_light_enforced(self) -> None:
        """Ensure no raw content fields in serialized output."""
        proj = build_fleet_projection(
            agents=FleetAgentSummary(
                total_agents=1, active_sessions=1, recent_heartbeats=3, stale_sessions=0
            ),
            queue=FleetQueueSummary(queued=1, total=1, highest_priority=1),
        )
        serialized = proj.model_dump_json()
        data = json.loads(serialized)
        _assert_no_forbidden_raw(data)


class TestFleetLeaseSummary:
    """FleetLeaseSummary model tests."""

    def test_defaults(self) -> None:
        s = FleetLeaseSummary()
        assert s.total_active == 0
        assert s.exclusive_write == 0
        assert s.shared_read == 0
        assert s.stale == 0
        assert s.expired == 0
        assert s.path_count == 0

    def test_filled(self) -> None:
        s = FleetLeaseSummary(
            total_active=2, exclusive_write=1, shared_read=1, path_count=5
        )
        assert s.total_active == 2
        assert s.exclusive_write == 1
        assert s.shared_read == 1

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            FleetLeaseSummary.model_validate({
                "total_active": 0,
                "exclusive_write": 0,
                "shared_read": 0,
                "stale": 0,
                "expired": 0,
                "path_count": 0,
                "raw_output": "bad",
            })


class TestFleetQueueSummary:
    """FleetQueueSummary model tests."""

    def test_defaults(self) -> None:
        q = FleetQueueSummary()
        assert q.total == 0
        assert q.highest_priority == 0

    def test_filled(self) -> None:
        q = FleetQueueSummary(
            queued=2, running=1, completed=5, total=8, highest_priority=3
        )
        assert q.queued == 2
        assert q.running == 1
        assert q.completed == 5

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            FleetQueueSummary.model_validate({
                "queued": 0,
                "running": 0,
                "blocked": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "total": 0,
                "highest_priority": 0,
                "raw_content": "bad",
            })


class TestFleetBlockerSummary:
    """FleetBlockerSummary model tests."""

    def test_defaults(self) -> None:
        b = FleetBlockerSummary()
        assert b.total_blockers == 0
        assert b.blocker_kinds == {}
        assert b.oldest_blocked_at is None

    def test_filled(self) -> None:
        b = FleetBlockerSummary(
            total_blockers=2,
            blocker_kinds={"dirty_files": 1, "lease_conflict": 1},
            oldest_blocked_at="2026-01-01T00:00:00",
        )
        assert b.total_blockers == 2
        assert b.blocker_kinds["dirty_files"] == 1


class TestFleetAgentSummary:
    """FleetAgentSummary model tests."""

    def test_defaults(self) -> None:
        a = FleetAgentSummary()
        assert a.total_agents == 0
        assert a.active_sessions == 0
        assert a.recent_heartbeats == 0
        assert a.stale_sessions == 0

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            FleetAgentSummary.model_validate({
                "total_agents": 0,
                "active_sessions": 0,
                "recent_heartbeats": 0,
                "stale_sessions": 0,
                "secret": "bad",
            })


class TestFleetPatchProposalSummary:
    """FleetPatchProposalSummary model tests."""

    def test_defaults(self) -> None:
        p = FleetPatchProposalSummary()
        assert p.total == 0
        assert p.oldest_pending_at is None
        assert p.latest_proposal_id is None

    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            FleetPatchProposalSummary.model_validate({
                "pending": 0,
                "applied": 0,
                "rejected": 0,
                "revised": 0,
                "total": 0,
                "oldest_pending_at": None,
                "latest_proposal_id": None,
                "raw": "bad",
            })


class TestFleetProjectionIntegration:
    def test_build_from_coordination_root_wires_queue_lease_and_patch(
        self, tmp_path: Path
    ) -> None:
        coord_root = tmp_path / "coordination"
        queue = FleetQueue(coord_root / "events.jsonl")
        queue.enqueue_item(FleetQueueItemKind.MESSAGE, payload={"summary": "hello"})

        PathLeaseManager(coord_root).claim_paths(
            session_id="s-1",
            task_id="t-1",
            mode="exclusive_write",
            paths=["src/app.py"],
            ttl_seconds=120,
        )

        proposals_dir = coord_root / ".fleet" / "patch-proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        proposals_dir.joinpath("proposal-1.json").write_text(
            json.dumps({
                "proposal_id": "pp-1",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            }),
            encoding="utf-8",
        )

        projection = build_fleet_projection(coordination_root=coord_root)
        assert projection.queue.total == 1
        assert projection.leases.total_active == 1
        assert projection.patches.pending == 1


class TestFleetProjectionSchema:
    """Validate FleetProjection against JSON Schema."""

    def _schema(self) -> dict:
        path = _SCHEMAS_DIR / "rig.fleet.projection.v1.schema.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _minimal_data(self) -> dict:
        return {
            "schema_version": "rig.fleet.projection.v1",
            "projection_id": "fp-test-001",
            "created_at": "2026-01-01T00:00:00",
            "fleet_name": "test",
            "agents": {
                "total_agents": 0,
                "active_sessions": 0,
                "recent_heartbeats": 0,
                "stale_sessions": 0,
            },
            "queue": {
                "queued": 0,
                "running": 0,
                "blocked": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "total": 0,
                "highest_priority": 0,
            },
            "leases": {
                "total_active": 0,
                "exclusive_write": 0,
                "shared_read": 0,
                "stale": 0,
                "expired": 0,
                "path_count": 0,
            },
            "blockers": {
                "total_blockers": 0,
                "blocker_kinds": {},
                "oldest_blocked_at": None,
            },
            "patches": {
                "pending": 0,
                "applied": 0,
                "rejected": 0,
                "revised": 0,
                "total": 0,
                "oldest_pending_at": None,
                "latest_proposal_id": None,
            },
        }

    def test_minimal_matches_schema(self) -> None:
        schema = self._schema()
        data = self._minimal_data()
        jsonschema.validate(data, schema)

    def test_filled_matches_schema(self) -> None:
        schema = self._schema()
        data = self._minimal_data()
        data["agents"] = {
            "total_agents": 2,
            "active_sessions": 1,
            "recent_heartbeats": 5,
            "stale_sessions": 0,
        }
        data["queue"] = {
            "queued": 3,
            "running": 1,
            "blocked": 0,
            "completed": 10,
            "failed": 0,
            "cancelled": 1,
            "total": 15,
            "highest_priority": 5,
        }
        data["leases"] = {
            "total_active": 4,
            "exclusive_write": 3,
            "shared_read": 1,
            "stale": 0,
            "expired": 0,
            "path_count": 12,
        }
        data["blockers"] = {
            "total_blockers": 2,
            "blocker_kinds": {"dirty_files": 1, "lease_conflict": 1},
            "oldest_blocked_at": "2026-01-01T09:00:00",
        }
        data["patches"] = {
            "pending": 2,
            "applied": 1,
            "rejected": 0,
            "revised": 1,
            "total": 4,
            "oldest_pending_at": "2026-01-01T08:00:00",
            "latest_proposal_id": "pp-001",
        }
        data["recent_event_count"] = 42
        jsonschema.validate(data, schema)

    def test_rejects_extra_property(self) -> None:
        schema = self._schema()
        data = self._minimal_data()
        data["raw_output"] = "should_not_exist"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_rejects_missing_required(self) -> None:
        schema = self._schema()
        data = self._minimal_data()
        del data["agents"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_model_dump_validates_without_exclude_none(self) -> None:
        """FleetProjection.model_dump(mode='json') validates against schema
        without using exclude_none=True.
        """
        schema = self._schema()
        proj = FleetProjection(
            projection_id="fp-dump-test", created_at="2026-01-01T00:00:00"
        )
        dumped = proj.model_dump(mode="json")
        # Should not raise ValidationError
        jsonschema.validate(instance=dumped, schema=schema)


class TestBuilderEmptySafe:
    """build_fleet_projection empty-safe behavior tests."""

    def test_no_args_returns_empty_defaults(self) -> None:
        proj = build_fleet_projection()
        assert proj.agents.total_agents == 0
        assert proj.queue.queued == 0
        assert proj.leases.total_active == 0
        assert proj.blockers.total_blockers == 0
        assert proj.patches.pending == 0
        assert proj.recent_event_count == 0

    def test_none_args_produce_defaults(self) -> None:
        proj = build_fleet_projection(
            queue=None, leases=None, blockers=None, patches=None, agents=None
        )
        assert proj.agents.total_agents == 0
        assert proj.queue.queued == 0

    def test_partial_args(self) -> None:
        proj = build_fleet_projection(
            queue=FleetQueueSummary(queued=1, total=1, highest_priority=1),
            leases=FleetLeaseSummary(total_active=2, path_count=3),
        )
        assert proj.queue.queued == 1
        assert proj.leases.total_active == 2
        # Not explicitly provided — should be defaults
        assert proj.blockers.total_blockers == 0
        assert proj.agents.total_agents == 0
        assert proj.patches.total == 0


# ── Helpers ─────────────────────────────────────────────────────────────


def _assert_no_forbidden_raw(obj, path: str = "") -> None:
    """Recursively ensure no forbidden raw field names appear in serialized data."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _FORBIDDEN_RAW:
                pytest.fail(f"Forbidden raw field '{key}' at {path}")
            _assert_no_forbidden_raw(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden_raw(item, f"{path}[{i}]")


# ── FleetQueueNextItem model tests ───────────────────────────────────────


class TestFleetQueueNextItem:
    def test_defaults(self) -> None:
        ni = FleetQueueNextItem()
        assert ni.queue_item_id is None
        assert ni.kind is None
        assert ni.priority == 0

    def test_filled(self) -> None:
        ni = FleetQueueNextItem(
            queue_item_id="q-001",
            kind="validate",
            priority=5,
            created_at="2026-01-01T00:00:00",
        )
        assert ni.queue_item_id == "q-001"
        assert ni.kind == "validate"
        assert ni.priority == 5


class TestFleetReplayDiagnostics:
    def test_defaults(self) -> None:
        r = FleetReplayDiagnostics()
        assert r.total_lines == 0
        assert r.valid_events == 0

    def test_filled(self) -> None:
        r = FleetReplayDiagnostics(
            total_lines=10,
            valid_events=8,
            malformed_lines=1,
            invalid_events=1,
            skipped_unknown_kind=0,
            total_skipped=2,
        )
        assert r.total_lines == 10
        assert r.valid_events == 8
        assert r.malformed_lines == 1


class TestFleetQueueSummaryNewFields:
    def test_next_item_default(self) -> None:
        q = FleetQueueSummary()
        assert q.next_item is None

    def test_next_item_set(self) -> None:
        q = FleetQueueSummary(
            queued=1,
            total=1,
            highest_priority=3,
            next_item=FleetQueueNextItem(
                queue_item_id="q-1", kind="message", priority=3
            ),
        )
        assert q.next_item is not None
        assert q.next_item.queue_item_id == "q-1"

    def test_replay_default(self) -> None:
        q = FleetQueueSummary()
        assert q.replay is None

    def test_replay_set(self) -> None:
        r = FleetReplayDiagnostics(total_lines=5, valid_events=5, total_skipped=0)
        q = FleetQueueSummary(queued=1, total=1, highest_priority=0, replay=r)
        assert q.replay is not None
        assert q.replay.valid_events == 5


# ── build_queue_summary_from_snapshot tests ──────────────────────────────


class TestBuildQueueSummaryFromSnapshot:
    def test_empty_snapshot(self) -> None:
        snap = FleetQueueSnapshot()
        qs = build_queue_summary_from_snapshot(snap)
        assert qs.total == 0
        assert qs.next_item is None
        assert qs.replay is None

    def test_with_queued_items(self) -> None:
        items = [
            FleetQueueItem(queue_item_id="a", kind="message", priority=1),
            FleetQueueItem(queue_item_id="b", kind="validate", priority=5),
        ]
        snap = FleetQueueSnapshot(
            items=items, total_count=2, status_counts={"queued": 2}
        )
        qs = build_queue_summary_from_snapshot(snap)
        assert qs.total == 2
        assert qs.queued == 2
        assert qs.next_item is not None
        assert qs.next_item.queue_item_id == "b"  # highest priority
        assert qs.next_item.kind == "validate"
        assert qs.highest_priority == 5

    def test_with_replay_report(self) -> None:
        rr = FleetQueueReplayReport(
            total_lines=10, valid_events=8, malformed_lines=2, total_skipped=2
        )
        snap = FleetQueueSnapshot(
            items=[], total_count=0, status_counts={}, replay_report=rr
        )
        qs = build_queue_summary_from_snapshot(snap)
        assert qs.replay is not None
        assert qs.replay.total_lines == 10
        assert qs.replay.malformed_lines == 2
        assert qs.replay.total_skipped == 2


# ── build_queue_summary tests ────────────────────────────────────────────


class TestBuildQueueSummary:
    def test_none_queue(self) -> None:
        qs = build_queue_summary(None)
        assert qs.total == 0

    def test_from_empty_queue(self, tmp_path) -> None:
        q = FleetQueue(tmp_path / "queue" / "events.jsonl")
        qs = build_queue_summary(q)
        assert qs.total == 0
        assert qs.replay is not None
        assert qs.replay.total_lines == 0

    def test_from_queue_with_events(self, tmp_path) -> None:
        q = FleetQueue(tmp_path / "queue" / "events.jsonl")
        q.enqueue_item("message")
        q.enqueue_item("validate", priority=5)
        qs = build_queue_summary(q)
        assert qs.total == 2
        assert qs.queued == 2
        assert qs.next_item is not None
        assert qs.next_item.kind == "validate"
        assert qs.highest_priority == 5
        assert qs.replay is not None


# ── build_lease_summary tests ────────────────────────────────────────────


class TestBuildLeaseSummary:
    def test_none_root(self) -> None:
        ls = build_lease_summary(None)
        assert ls.total_active == 0

    def test_nonexistent_root(self) -> None:
        ls = build_lease_summary(Path("/nonexistent/path"))
        assert ls.total_active == 0


# ── build_patch_proposal_summary tests ────────────────────────────────────


class TestBuildPatchProposalSummary:
    def test_none_root(self) -> None:
        ps = build_patch_proposal_summary(None)
        assert ps.total == 0

    def test_nonexistent_root(self) -> None:
        ps = build_patch_proposal_summary(Path("/nonexistent/path"))
        assert ps.total == 0

    def test_missing_proposals_dir(self, tmp_path) -> None:
        ps = build_patch_proposal_summary(tmp_path)
        assert ps.total == 0
