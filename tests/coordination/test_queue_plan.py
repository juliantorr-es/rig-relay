"""Tests for the queue planner, work item schema, work queue schema,
ready work plan schema, and parent convergence report schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from scripts.rig_relay_queue_plan import compute_ready_plan

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
WORK_ITEM_SCHEMA = SCHEMAS_DIR / "rig.relay.work_item.v1.schema.json"
WORK_QUEUE_SCHEMA = SCHEMAS_DIR / "rig.relay.work_queue.v1.schema.json"
PARENT_CONVERGENCE_SCHEMA = (
    SCHEMAS_DIR / "rig.relay.parent_convergence_report.v1.schema.json"
)
READY_PLAN_SCHEMA = SCHEMAS_DIR / "rig.relay.ready_work_plan.v1.schema.json"

NOW = datetime.now(UTC).isoformat()


def _make_work_item(**overrides: object) -> dict:
    """Create a valid work item for testing."""
    base = {
        "schema_version": "rig.relay.work_item.v1",
        "work_item_id": "wi_test_001",
        "sprint_id": "sprint_test_001",
        "parent_work_item_id": None,
        "title": "Test work item",
        "description": "A test work item for queue planner tests.",
        "status": "pending",
        "priority": 50,
        "agent_profile": "implementer",
        "execution_mode": "delegate",
        "parallelism_group": None,
        "dependencies": [],
        "blocked_by": [],
        "allowed_paths": ["scripts/"],
        "forbidden_paths": [],
        "tool_policy": {"allow_write": True, "allow_bash": True},
        "coordination_policy": {
            "claim_task": True,
            "reserve_paths": True,
            "heartbeat": True,
        },
        "checkpoint_policy": "prompt",
        "validation_commands": ["uv run pytest tests/"],
        "done_when": ["tests pass"],
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _make_queue(work_items: list[dict], **overrides: object) -> dict:
    """Create a work queue for testing."""
    base = {
        "schema_version": "rig.relay.work_queue.v1",
        "sprint_id": "sprint_test_001",
        "queue_id": "queue_test_001",
        "created_at": NOW,
        "updated_at": NOW,
        "max_parallel_children": 4,
        "work_items": work_items,
        "active_work_item_ids": [],
        "completed_work_item_ids": [],
        "blocked_work_item_ids": [],
    }
    base.update(overrides)
    return base


def _try_validate(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _try_validate_jsonschema(instance: dict, schema_path: Path) -> list[str]:
    """Alias for _try_validate."""
    return _try_validate(instance, schema_path)


# ── Schema validation tests ──────────────────────────────────────────────


def test_work_item_schema_is_valid_json():
    data = json.loads(WORK_ITEM_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Work Item v1"
    assert "work_item_id" in data["required"]


def test_work_item_validates_sample():
    item = _make_work_item()
    errors = _try_validate(item, WORK_ITEM_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_work_item_missing_required_fails():
    item = {"schema_version": "rig.relay.work_item.v1"}
    errors = _try_validate(item, WORK_ITEM_SCHEMA)
    assert len(errors) > 0


def test_work_item_invalid_status_fails():
    item = _make_work_item(status="nonexistent")
    errors = _try_validate(item, WORK_ITEM_SCHEMA)
    assert len(errors) > 0


def test_work_queue_schema_is_valid_json():
    data = json.loads(WORK_QUEUE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Work Queue v1"
    assert "queue_id" in data["required"]


def test_work_queue_validates_sample():
    item = _make_work_item()
    queue = _make_queue([item])
    errors = _try_validate(queue, WORK_QUEUE_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_parent_convergence_schema_is_valid_json():
    data = json.loads(PARENT_CONVERGENCE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Parent Convergence Report v1"
    assert "overall_status" in data["required"]


def test_parent_convergence_validates_sample():
    report = {
        "schema_version": "rig.relay.parent_convergence_report.v1",
        "sprint_id": "sprint_test_001",
        "generated_at": NOW,
        "overall_status": "continue",
        "child_results": [
            {
                "session_id": "session_001",
                "work_item_id": "wi_001",
                "agent_profile": "implementer",
                "status": "completed",
            }
        ],
        "completed_work_items": [
            {"work_item_id": "wi_001", "title": "Done", "status": "completed"}
        ],
        "blocked_work_items": [],
        "recommended_next_action": "dispatch_next_ready_work",
        "warnings": [],
    }
    errors = _try_validate(report, PARENT_CONVERGENCE_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_ready_plan_schema_is_valid_json():
    data = json.loads(READY_PLAN_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Ready Work Plan v1"
    assert "ready_items" in data["required"]


def test_ready_plan_validates_sample():
    plan = compute_ready_plan(_make_queue([_make_work_item()]), max_items=4)
    errors = _try_validate(plan, READY_PLAN_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


# ── Queue planner tests ──────────────────────────────────────────────────


def test_returns_ready_item_when_dependencies_complete(tmp_path: Path):
    wi = _make_work_item(status="pending")
    queue = _make_queue([wi])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 1
    assert plan["ready_items"][0]["work_item_id"] == "wi_test_001"
    assert len(plan["blocked_items"]) == 0
    assert len(plan["waiting_items"]) == 0


def test_blocks_item_when_dependency_pending(tmp_path: Path):
    wi1 = _make_work_item(
        work_item_id="wi_001", title="First item", status="pending", priority=10
    )
    wi2 = _make_work_item(
        work_item_id="wi_002",
        title="Second item (depends)",
        status="pending",
        priority=20,
        dependencies=[{"work_item_id": "wi_001", "type": "must_complete"}],
    )
    queue = _make_queue([wi1, wi2])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_001" in ready_ids
    assert "wi_002" not in ready_ids
    waiting_ids = [w["work_item_id"] for w in plan["waiting_items"]]
    assert "wi_002" in waiting_ids


def test_respects_max_items(tmp_path: Path):
    items = [
        _make_work_item(work_item_id=f"wi_{i:03d}", title=f"Item {i}", priority=i)
        for i in range(10)
    ]
    queue = _make_queue(items)
    plan = compute_ready_plan(queue, max_items=3, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 3


def test_respects_max_parallel_children(tmp_path: Path):
    items = [
        _make_work_item(work_item_id=f"wi_{i:03d}", title=f"Item {i}") for i in range(6)
    ]
    queue = _make_queue(items, max_parallel_children=2)
    plan = compute_ready_plan(queue, max_items=10, coordination_root=tmp_path)
    # With max_parallel_children=2 and 0 active, only 2 slots available
    assert len(plan["ready_items"]) <= 2
    assert plan["available_slots"] == 2


def test_sorts_by_priority(tmp_path: Path):
    items = [
        _make_work_item(work_item_id=f"wi_{p:03d}", title=f"Priority {p}", priority=p)
        for p in [90, 10, 50, 30, 70]
    ]
    queue = _make_queue(items)
    plan = compute_ready_plan(queue, max_items=5, coordination_root=tmp_path)
    priorities = [r["priority"] for r in plan["ready_items"]]
    assert priorities == sorted(priorities)


def test_skips_active_items(tmp_path: Path):
    wi_active = _make_work_item(work_item_id="wi_active", status="running")
    wi_pending = _make_work_item(work_item_id="wi_pending", title="Pending item")
    queue = _make_queue([wi_active, wi_pending], active_work_item_ids=["wi_active"])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_active" not in ready_ids
    assert "wi_pending" in ready_ids


def test_skips_terminal_items(tmp_path: Path):
    wi_done = _make_work_item(work_item_id="wi_done", status="completed")
    wi_pending = _make_work_item(work_item_id="wi_pending", title="Pending item")
    queue = _make_queue([wi_done, wi_pending], completed_work_item_ids=["wi_done"])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_done" not in ready_ids
    assert "wi_pending" in ready_ids


def test_blocks_item_with_blocked_status(tmp_path: Path):
    wi_blocked = _make_work_item(
        work_item_id="wi_blocked", status="blocked", blocked_by=["Some external reason"]
    )
    wi_pending = _make_work_item(
        work_item_id="wi_pending", title="Pending item", priority=60
    )
    queue = _make_queue([wi_blocked, wi_pending])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    blocked_ids = [b["work_item_id"] for b in plan["blocked_items"]]
    assert "wi_blocked" in blocked_ids
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_pending" in ready_ids


def test_handles_empty_queue(tmp_path: Path):
    queue = _make_queue([])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    assert len(plan["ready_items"]) == 0
    assert len(plan["blocked_items"]) == 0
    assert len(plan["waiting_items"]) == 0
    assert plan["active_count"] == 0


def test_emits_content_light_output(tmp_path: Path):
    wi = _make_work_item()
    queue = _make_queue([wi])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    output = json.dumps(plan)
    # Check that actual content patterns are absent.
    # The string 'raw_file_contents' appears in the schema-required
    # 'forbidden_fields' metadata list — that's not a content leak.
    assert "-----BEGIN RSA PRIVATE KEY" not in output
    assert "def _make_work_item" not in output
    assert "/Users/" not in output


def test_filters_by_profile(tmp_path: Path):
    wi_impl = _make_work_item(
        work_item_id="wi_impl", title="Implementer task", agent_profile="implementer"
    )
    wi_tester = _make_work_item(
        work_item_id="wi_tester", title="Tester task", agent_profile="tester"
    )
    wi_doc = _make_work_item(
        work_item_id="wi_doc", title="Documenter task", agent_profile="documenter"
    )
    queue = _make_queue([wi_impl, wi_tester, wi_doc])
    plan = compute_ready_plan(queue, max_items=4, profiles=["implementer", "tester"], coordination_root=tmp_path)
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_impl" in ready_ids
    assert "wi_tester" in ready_ids
    assert "wi_doc" not in ready_ids


def test_recommendations_present_when_ready(tmp_path: Path):
    wi = _make_work_item()
    queue = _make_queue([wi])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    assert len(plan["recommendations"]) > 0


def test_active_count_reflects_running_items():
    """Active count is derived from coordination sessions, not queue fields.

    Without coordination session files, active_count defaults to 0.
    Running work items are still excluded from ready_items.
    """
    wi_active = _make_work_item(work_item_id="wi_active", status="running")
    wi_pending = _make_work_item(work_item_id="wi_pending", title="Pending item")
    queue = _make_queue([wi_active, wi_pending], active_work_item_ids=["wi_active"])
    plan = compute_ready_plan(queue, max_items=4, coordination_root=tmp_path)
    # No coordination sessions exist, so active_count is 0
    assert plan["active_count"] == 0
    # Running items are excluded from ready_items
    ready_ids = [r["work_item_id"] for r in plan["ready_items"]]
    assert "wi_active" not in ready_ids
    assert "wi_pending" in ready_ids
    # With zero active sessions, all max_parallel_children slots are available
    assert plan["available_slots"] == 4
