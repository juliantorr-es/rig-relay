"""Tests for the delegate/fleet orchestration schemas and queue planner."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from scripts.rig_relay_queue_plan import compute_ready_plan

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

WORK_ITEM_SCHEMA = SCHEMAS_DIR / "rig.relay.work_item.v1.schema.json"
WORK_QUEUE_SCHEMA = SCHEMAS_DIR / "rig.relay.work_queue.v1.schema.json"
READY_PLAN_SCHEMA = SCHEMAS_DIR / "rig.relay.ready_work_plan.v1.schema.json"
CONVERGENCE_SCHEMA = SCHEMAS_DIR / "rig.relay.parent_convergence_report.v1.schema.json"


def _try_validate(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _make_work_item(**overrides: object) -> dict:
    """Create a valid work item for testing."""
    base = {
        "schema_version": "rig.relay.work_item.v1",
        "work_item_id": "wi_test_001",
        "sprint_id": "sprint_test_001",
        "title": "Test work item",
        "description": "A test work item for unit testing.",
        "status": "pending",
        "priority": 50,
        "agent_profile": "tester",
        "execution_mode": "delegate",
        "allowed_paths": ["tests/coordination/"],
        "forbidden_paths": [],
        "tool_policy": {"allow_write": False, "allow_bash": True},
        "coordination_policy": {
            "claim_task": True,
            "reserve_paths": False,
            "heartbeat": True,
        },
        "checkpoint_policy": "off",
        "validation_commands": ["uv run pytest tests/coordination/"],
        "done_when": ["tests pass"],
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


def _make_queue(**overrides: object) -> dict:
    """Create a valid work queue for testing."""
    base = {
        "schema_version": "rig.relay.work_queue.v1",
        "sprint_id": "sprint_test_001",
        "queue_id": "queue_test_001",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "max_parallel_children": 4,
        "work_items": [],
        "active_work_item_ids": [],
        "completed_work_item_ids": [],
    }
    base.update(overrides)
    return base


def _make_convergence_report(**overrides: object) -> dict:
    """Create a valid parent convergence report for testing."""
    base = {
        "schema_version": "rig.relay.parent_convergence_report.v1",
        "sprint_id": "sprint_test_001",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": "continue",
        "child_results": [
            {
                "session_id": "session_test_001",
                "work_item_id": "wi_test_001",
                "agent_profile": "tester",
                "status": "completed",
            }
        ],
        "completed_work_items": [
            {"work_item_id": "wi_test_001", "title": "Test item", "status": "completed"}
        ],
        "blocked_work_items": [],
        "recommended_next_action": "Continue dispatching work",
        "warnings": [],
    }
    base.update(overrides)
    return base


# ── Schema validity tests ────────────────────────────────────────────────


def test_work_item_schema_is_valid_json():
    """Work item schema file is valid JSON."""
    data = json.loads(WORK_ITEM_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Work Item v1"
    assert "work_item_id" in data["required"]


def test_work_queue_schema_is_valid_json():
    """Work queue schema file is valid JSON."""
    data = json.loads(WORK_QUEUE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Work Queue v1"
    assert "queue_id" in data["required"]


def test_ready_plan_schema_is_valid_json():
    """Ready work plan schema file is valid JSON."""
    data = json.loads(READY_PLAN_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Ready Work Plan v1"
    assert "ready_items" in data["required"]


def test_convergence_report_schema_is_valid_json():
    """Parent convergence report schema file is valid JSON."""
    data = json.loads(CONVERGENCE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Parent Convergence Report v1"
    assert "child_results" in data["required"]


# ── Schema validation tests ──────────────────────────────────────────────


def test_work_item_schema_validates_sample():
    """Sample work item validates against schema."""
    sample = _make_work_item()
    errors = _try_validate(sample, WORK_ITEM_SCHEMA)
    assert not errors, f"Validation errors: {errors}"


def test_work_queue_schema_validates_sample():
    """Sample work queue validates against schema."""
    sample = _make_queue(work_items=[_make_work_item()])
    errors = _try_validate(sample, WORK_QUEUE_SCHEMA)
    assert not errors, f"Validation errors: {errors}"


def test_ready_plan_schema_validates_sample():
    """Sample ready work plan validates against schema."""
    sample = {
        "schema_version": "rig.relay.ready_work_plan.v1",
        "sprint_id": "sprint_test_001",
        "generated_at": datetime.now(UTC).isoformat(),
        "max_items": 4,
        "ready_items": [],
        "blocked_items": [],
        "waiting_items": [],
        "active_count": 0,
        "available_slots": 4,
        "recommendations": ["no_ready_work"],
        "warnings": [],
    }
    errors = _try_validate(sample, READY_PLAN_SCHEMA)
    assert not errors, f"Validation errors: {errors}"


def test_convergence_report_schema_validates_sample():
    """Sample parent convergence report validates against schema."""
    sample = _make_convergence_report()
    errors = _try_validate(sample, CONVERGENCE_SCHEMA)
    assert not errors, f"Validation errors: {errors}"


def test_work_item_14_statuses():
    """Work item schema has exactly 14 statuses."""
    schema = json.loads(WORK_ITEM_SCHEMA.read_text(encoding="utf-8"))
    statuses = schema["properties"]["status"]["enum"]
    expected = {
        "pending",
        "ready",
        "claimed",
        "dispatched",
        "running",
        "blocked",
        "waiting_dependency",
        "waiting_lease",
        "waiting_validation_stage",
        "completed",
        "failed",
        "refused",
        "cancelled",
        "superseded",
    }
    assert set(statuses) == expected


# ── Queue planner tests ──────────────────────────────────────────────────


def test_queue_planner_returns_ready_item_when_dependencies_complete(tmp_path):
    """Item with completed dependencies appears in ready_items."""
    wi = _make_work_item(work_item_id="wi_002", status="pending")
    queue = _make_queue(work_items=[wi], completed_work_item_ids=[])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 1
    assert plan["ready_items"][0]["work_item_id"] == "wi_002"


def test_queue_planner_blocks_item_when_dependency_pending(tmp_path):
    """Item with pending dependency is in waiting_items."""
    wi = _make_work_item(
        work_item_id="wi_002",
        status="pending",
        dependencies=[{"work_item_id": "wi_001", "type": "must_complete"}],
    )
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 0
    assert len(plan["waiting_items"]) == 1
    assert "dependencies" in plan["waiting_items"][0]["waiting_reason"].lower()


def test_queue_planner_respects_max_items(tmp_path):
    """Only max_items ready items are returned."""
    items = [
        _make_work_item(work_item_id=f"wi_{i:03d}", status="pending", priority=10)
        for i in range(6)
    ]
    queue = _make_queue(work_items=items)
    plan = compute_ready_plan(queue, coordination_root=tmp_path, max_items=3)
    assert len(plan["ready_items"]) == 3
    assert plan["max_items"] == 3


def test_queue_planner_sorts_by_priority(tmp_path):
    """Items are sorted by priority (lower first)."""
    items = [
        _make_work_item(work_item_id="wi_001", status="pending", priority=50),
        _make_work_item(work_item_id="wi_002", status="pending", priority=10),
        _make_work_item(work_item_id="wi_003", status="pending", priority=30),
    ]
    queue = _make_queue(work_items=items)
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert ready_ids == ["wi_002", "wi_003", "wi_001"]


def test_queue_planner_skips_terminal_items(tmp_path):
    """Terminal items (completed, failed, etc.) are not in ready/waiting."""
    items = [
        _make_work_item(work_item_id="wi_001", status="completed"),
        _make_work_item(work_item_id="wi_002", status="failed"),
        _make_work_item(work_item_id="wi_003", status="refused"),
        _make_work_item(work_item_id="wi_004", status="cancelled"),
        _make_work_item(work_item_id="wi_005", status="superseded"),
        _make_work_item(work_item_id="wi_006", status="pending"),
    ]
    queue = _make_queue(work_items=items)
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 1
    assert plan["ready_items"][0]["work_item_id"] == "wi_006"


def test_queue_planner_skips_active_items(tmp_path):
    """Active items (claimed, dispatched, running) are not returned."""
    items = [
        _make_work_item(work_item_id="wi_001", status="claimed"),
        _make_work_item(work_item_id="wi_002", status="dispatched"),
        _make_work_item(work_item_id="wi_003", status="running"),
        _make_work_item(work_item_id="wi_004", status="pending"),
    ]
    queue = _make_queue(work_items=items)
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 1
    assert plan["ready_items"][0]["work_item_id"] == "wi_004"


def test_queue_planner_emits_blocked_items(tmp_path):
    """Items with status 'blocked' appear in blocked_items."""
    wi = _make_work_item(
        work_item_id="wi_001", status="blocked", blocked_by=["human review required"]
    )
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["blocked_items"]) == 1
    assert "human review" in plan["blocked_items"][0]["blocked_reason"]


def test_queue_planner_emits_waiting_dependency(tmp_path):
    """Item with status waiting_dependency appears in waiting_items."""
    wi = _make_work_item(
        work_item_id="wi_002",
        status="waiting_dependency",
        dependencies=[{"work_item_id": "wi_001", "type": "must_complete"}],
    )
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["waiting_items"]) == 1
    assert "dependencies" in plan["waiting_items"][0]["waiting_reason"].lower()


def test_queue_planner_emits_waiting_lease(tmp_path):
    """Item with status waiting_lease appears in waiting_items."""
    wi = _make_work_item(work_item_id="wi_001", status="waiting_lease")
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["waiting_items"]) == 1
    assert "lease" in plan["waiting_items"][0]["waiting_reason"].lower()


def test_queue_planner_validates_against_schema(tmp_path):
    """Ready plan validates against schema."""
    wi = _make_work_item(status="pending")
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    errors = _try_validate(plan, READY_PLAN_SCHEMA)
    assert not errors, f"Validation errors: {errors}"


def test_queue_planner_content_light(tmp_path):
    """Ready plan contains no forbidden raw content."""
    wi = _make_work_item(status="pending")
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    json_str = json.dumps(plan)
    # Forbidden field names may appear in the forbidden_fields list
    # but source code patterns must not appear in values
    source_patterns = [
        "def _read_json",
        "def compute_ready_plan",
        "-----BEGIN",
        "def test_",
    ]
    json_lower = json_str.lower()
    for pat in source_patterns:
        assert pat not in json_lower, f"Forbidden source content found: {pat}"


def test_queue_planner_active_count_from_sessions(tmp_path):
    """Active count is computed from coordination sessions."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)
    for i in range(2):
        sf = sessions_dir / f"session_{i}.json"
        sf.write_text(
            json.dumps({
                "session_id": f"s{i}",
                "status": "active",
                "agent_profile": "tester",
            })
        )

    queue = _make_queue(work_items=[_make_work_item()])
    plan = compute_ready_plan(queue, coordination_root=coord)
    assert plan["active_count"] == 2


def test_queue_planner_no_ready_work_recommendation(tmp_path):
    """Empty queue produces no_ready_work recommendation."""
    queue = _make_queue()
    plan = compute_ready_plan(queue, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 0
    recs = plan.get("recommendations") or []
    assert any("no_ready_work" in r for r in recs)


def test_queue_planner_write_lease_conflict(tmp_path):
    """Item with write path overlapping active lease is waiting."""
    coord = tmp_path / "coord"
    leases_dir = coord / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    lf = leases_dir / "lease_test.json"
    lf.write_text(
        json.dumps({
            "session_id": "s1",
            "mode": "write",
            "status": "active",
            "paths": ["src/vibe/core/"],
        })
    )

    wi = _make_work_item(
        work_item_id="wi_001",
        agent_profile="implementer",
        allowed_paths=["src/vibe/core/"],
        tool_policy={"allow_write": True, "allow_bash": True},
        status="pending",
    )
    queue = _make_queue(work_items=[wi])
    plan = compute_ready_plan(queue, coordination_root=coord)
    assert len(plan["ready_items"]) == 0
    assert len(plan["waiting_items"]) == 1
    assert "lease" in plan["waiting_items"][0]["waiting_reason"].lower()
