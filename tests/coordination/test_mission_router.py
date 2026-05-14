"""Tests for the Rig Mission Router Phase 0.

Proves batch normalization, heuristic classification, dependency/conflict planning,
queue item compilation, and content-light boundary enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.coordination.mission_router import (
    MissionBatch,
    MissionRoute,
    MissionRouter,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
MISSION_BATCH_SCHEMA = SCHEMAS_DIR / "rig.fleet.mission_batch.v1.schema.json"
MISSION_PLAN_SCHEMA = SCHEMAS_DIR / "rig.fleet.mission_plan.v1.schema.json"
MISSION_ROUTE_SCHEMA = SCHEMAS_DIR / "rig.fleet.mission_route.v1.schema.json"


@pytest.fixture
def router() -> MissionRouter:
    return MissionRouter()


def _try_validate(instance: Any, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


# ── Classification Tests ───────────────────────────────────────────────────


def test_routes_docs_mission_to_delegated(router: MissionRouter):
    batch = MissionBatch(
        user_request_summary="Update docs",
        mission_texts=[
            "Mission: Update README\nModify docs/README.md to add a section about fleet."
        ],
        requested_by="user1",
    )
    plan = router.route_batch(batch)
    assert len(plan.nodes) == 1
    assert plan.nodes[0].route == MissionRoute.DELEGATED_AGENT


def test_routes_broad_mission_to_fleet(router: MissionRouter):
    text = (
        "Mission: Overhaul everything\n"
        "Touch docs/README.md, tests/test_core.py, rig_relay/runtime/exec.py, vibe/cli/app.py. "
        "Update all schemas and models."
    )
    batch = MissionBatch(
        user_request_summary="Big overhaul", mission_texts=[text], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert plan.nodes[0].route == MissionRoute.FLEET


def test_routes_patch_proposal_mission(router: MissionRouter):
    text = (
        "Mission: Fix runtime\nModify rig_relay/runtime/tool_invocation_execution.py."
    )
    batch = MissionBatch(
        user_request_summary="Fix runtime", mission_texts=[text], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert plan.nodes[0].route == MissionRoute.PATCH_PROPOSAL


def test_routes_destructive_to_human_review(router: MissionRouter):
    text = "Mission: Clean repo\nRun git clean -fdx and git reset --hard HEAD."
    batch = MissionBatch(
        user_request_summary="Destructive", mission_texts=[text], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert plan.nodes[0].route == MissionRoute.HUMAN_REVIEW


def test_routes_approval_to_patch_proposal(router: MissionRouter):
    text = "Mission: Approve PR\nGo ahead and merge the patch proposal 123."
    batch = MissionBatch(
        user_request_summary="Merge task", mission_texts=[text], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert plan.nodes[0].route == MissionRoute.PATCH_PROPOSAL


# ── Dependency & Conflict Tests ──────────────────────────────────────────


def test_overlapping_paths_create_conflicts_and_deps(router: MissionRouter):
    m1 = "Mission: Edit utils\nChange rig_relay/utils.py."
    m2 = "Mission: Fix utils\nAnother change to rig_relay/utils.py."
    batch = MissionBatch(
        user_request_summary="Overlap", mission_texts=[m1, m2], requested_by="user1"
    )
    plan = router.route_batch(batch)

    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].kind == "path_overlap"
    assert "rig_relay/utils.py" in plan.conflicts[0].paths

    assert len(plan.dependencies) == 1
    # Dependency should be node_1 depends on node_0 (due to stable sorting)
    assert plan.dependencies[0].node_id == plan.nodes[1].node_id
    assert plan.dependencies[0].depends_on == plan.nodes[0].node_id


def test_independent_missions_in_same_group(router: MissionRouter):
    m1 = "Mission: Docs\nEdit docs/a.md"
    m2 = "Mission: Tests\nEdit tests/b.py"
    batch = MissionBatch(
        user_request_summary="Independent", mission_texts=[m1, m2], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert len(plan.runnable_groups) == 1
    assert len(plan.runnable_groups[0]) == 2


def test_dependent_missions_are_ordered(router: MissionRouter):
    m1 = "Mission: Core\nEdit rig_relay/utils.py"
    m2 = "Mission: More Core\nEdit rig_relay/utils.py"
    batch = MissionBatch(
        user_request_summary="Dependent", mission_texts=[m1, m2], requested_by="user1"
    )
    plan = router.route_batch(batch)
    assert len(plan.runnable_groups) == 2
    assert plan.runnable_groups[0] == [plan.nodes[0].node_id]
    assert plan.runnable_groups[1] == [plan.nodes[1].node_id]


# ── Compilation Tests ─────────────────────────────────────────────────────


def test_compiles_to_queue_item_templates(router: MissionRouter):
    batch = MissionBatch(
        user_request_summary="Docs only",
        mission_texts=["Mission: Update README\nModify docs/README.md"],
        requested_by="user1",
    )
    plan = router.route_batch(batch)
    templates = router.compile_to_queue_items(plan)

    assert len(templates) == 1
    assert templates[0]["kind"] == "runtime_exec"
    assert templates[0]["mission_id"] == batch.batch_id
    assert templates[0]["payload"]["node_id"] == plan.nodes[0].node_id
    assert templates[0]["payload"]["route"] == "delegated_agent"


# ── Content-Light & Schema Tests ──────────────────────────────────────────


def test_plan_output_is_content_light(router: MissionRouter):
    raw_text = "Mission: Secret\nThis mission contains a secret: API_KEY=12345."
    batch = MissionBatch(
        user_request_summary="Sensitive", mission_texts=[raw_text], requested_by="user1"
    )
    plan = router.route_batch(batch)
    dump = plan.model_dump_json()

    # Raw prompt should NOT be in the dump
    assert "API_KEY=12345" not in dump
    # Summary/Sanitized summary ARE allowed (truncated)
    assert "Mission: Secret" in dump


def test_schemas_validate_model_dumps(router: MissionRouter):
    batch = MissionBatch(
        user_request_summary="Schema test",
        mission_texts=["Mission: A", "Mission: B"],
        requested_by="user1",
    )
    batch_dict = batch.model_dump(mode="json")
    errors = _try_validate(batch_dict, MISSION_BATCH_SCHEMA)
    assert not errors, f"Batch schema errors: {errors}"

    plan = router.route_batch(batch)
    plan_dict = plan.model_dump(mode="json")
    errors = _try_validate(plan_dict, MISSION_PLAN_SCHEMA)
    assert not errors, f"Plan schema errors: {errors}"

    route_dict = "local_runtime"
    errors = _try_validate(route_dict, MISSION_ROUTE_SCHEMA)
    assert not errors, f"Route schema errors: {errors}"


def test_schemas_reject_extra_fields():
    # Batch extra field
    batch_dict = {
        "schema_version": "rig.fleet.mission_batch.v1",
        "batch_id": "b1",
        "created_at": "2026-05-14T12:00:00Z",
        "user_request_summary": "test",
        "mission_texts": ["a"],
        "requested_by": "u1",
        "extra_field": "forbidden",
    }
    errors = _try_validate(batch_dict, MISSION_BATCH_SCHEMA)
    assert len(errors) > 0
    assert "extra_field" in errors[0]


def test_deterministic_classification(router: MissionRouter):
    text = "Mission: Test\nEdit tests/test_a.py"
    batch1 = MissionBatch(
        user_request_summary="T1", mission_texts=[text], requested_by="u1"
    )
    batch2 = MissionBatch(
        user_request_summary="T1", mission_texts=[text], requested_by="u1"
    )

    plan1 = router.route_batch(batch1)
    plan2 = router.route_batch(batch2)

    assert plan1.nodes[0].route == plan2.nodes[0].route
    assert plan1.nodes[0].route == MissionRoute.DELEGATED_AGENT
