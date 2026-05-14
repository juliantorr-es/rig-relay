"""Tests for FleetProjection — content-light fleet coordination read model."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.coordination.fleet_projection import (
    FleetAgentSummary,
    FleetBlockerSummary,
    FleetLeaseSummary,
    FleetPatchProposalSummary,
    FleetProjection,
    FleetQueueSummary,
    build_fleet_projection,
)

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
                total_active=4,
                exclusive_write=3,
                shared_read=1,
                path_count=12,
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
        with pytest.raises(Exception):
            FleetProjection.model_validate({
                "schema_version": "rig.fleet.projection.v1",
                "projection_id": "fp-001",
                "created_at": "2026-01-01T00:00:00",
                "fleet_name": "test",
                "agents": {"total_agents": 0, "active_sessions": 0, "recent_heartbeats": 0, "stale_sessions": 0},
                "queue": {"queued": 0, "running": 0, "blocked": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0, "highest_priority": 0},
                "leases": {"total_active": 0, "exclusive_write": 0, "shared_read": 0, "stale": 0, "expired": 0, "path_count": 0},
                "blockers": {"total_blockers": 0, "blocker_kinds": {}, "oldest_blocked_at": None},
                "patches": {"pending": 0, "applied": 0, "rejected": 0, "revised": 0, "total": 0, "oldest_pending_at": None, "latest_proposal_id": None},
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
        with pytest.raises(Exception):
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
        q = FleetQueueSummary(queued=2, running=1, completed=5, total=8, highest_priority=3)
        assert q.queued == 2
        assert q.running == 1
        assert q.completed == 5

    def test_rejects_unknown(self) -> None:
        with pytest.raises(Exception):
            FleetQueueSummary.model_validate({
                "queued": 0, "running": 0, "blocked": 0, "completed": 0,
                "failed": 0, "cancelled": 0, "total": 0, "highest_priority": 0,
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
        with pytest.raises(Exception):
            FleetAgentSummary.model_validate({
                "total_agents": 0, "active_sessions": 0,
                "recent_heartbeats": 0, "stale_sessions": 0,
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
        with pytest.raises(Exception):
            FleetPatchProposalSummary.model_validate({
                "pending": 0, "applied": 0, "rejected": 0, "revised": 0,
                "total": 0, "oldest_pending_at": None, "latest_proposal_id": None,
                "raw": "bad",
            })


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
                "queued": 0, "running": 0, "blocked": 0, "completed": 0,
                "failed": 0, "cancelled": 0, "total": 0, "highest_priority": 0,
            },
            "leases": {
                "total_active": 0, "exclusive_write": 0, "shared_read": 0,
                "stale": 0, "expired": 0, "path_count": 0,
            },
            "blockers": {
                "total_blockers": 0,
                "blocker_kinds": {},
                "oldest_blocked_at": None,
            },
            "patches": {
                "pending": 0, "applied": 0, "rejected": 0, "revised": 0,
                "total": 0, "oldest_pending_at": None, "latest_proposal_id": None,
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
            "queued": 3, "running": 1, "blocked": 0, "completed": 10,
            "failed": 0, "cancelled": 1, "total": 15, "highest_priority": 5,
        }
        data["leases"] = {
            "total_active": 4, "exclusive_write": 3, "shared_read": 1,
            "stale": 0, "expired": 0, "path_count": 12,
        }
        data["blockers"] = {
            "total_blockers": 2,
            "blocker_kinds": {"dirty_files": 1, "lease_conflict": 1},
            "oldest_blocked_at": "2026-01-01T09:00:00",
        }
        data["patches"] = {
            "pending": 2, "applied": 1, "rejected": 0, "revised": 1,
            "total": 4, "oldest_pending_at": "2026-01-01T08:00:00",
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
