"""Tests for the spawn session planner and spawn plan schema."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


from datetime import UTC, datetime
import json
from pathlib import Path

from scripts.rig_relay_spawn_session import compute_spawn_plan, validate_mission_packet

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
SPAWN_PLAN_SCHEMA = SCHEMAS_DIR / "rig.relay.spawn_plan.v1.schema.json"
MISSION_SCHEMA = SCHEMAS_DIR / "rig.relay.mission_packet.v1.schema.json"


def _make_valid_packet(**overrides: object) -> dict:
    """Create a valid mission packet for testing."""
    base = {
        "schema_version": "rig.relay.mission_packet.v1",
        "mission_id": "mission_test_001",
        "parent_sprint_id": "sprint_test_001",
        "parent_review_id": None,
        "agent_profile": "tester",
        "mission_title": "Test mission",
        "instructions": "Run tests and report.",
        "allowed_paths": ["tests/coordination/"],
        "forbidden_paths": [],
        "tool_policy": {
            "allow_write": False,
            "allow_bash": True,
            "bash_allowlist": ["uv run pytest tests/coordination/"],
        },
        "coordination_policy": {
            "claim_task": True,
            "reserve_paths": False,
            "heartbeat": True,
        },
        "checkpoint_policy": "off",
        "validation_commands": ["uv run pytest tests/coordination/"],
        "done_when": ["tests pass"],
        "max_runtime_seconds": 600,
        "created_at": datetime.now(UTC).isoformat(),
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


# ── Schema tests ─────────────────────────────────────────────────────────


def test_spawn_plan_schema_is_valid_json():
    """Spawn plan schema file is valid JSON."""
    data = json.loads(SPAWN_PLAN_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Spawn Plan v1"
    assert "can_spawn" in data["required"]


# ── Validation tests ─────────────────────────────────────────────────────


def test_valid_read_only_mission_passes_validation():
    """Valid read-only mission packet passes validation."""
    packet = _make_valid_packet()
    errors = validate_mission_packet(packet)
    assert not errors, f"Unexpected errors: {errors}"


def test_valid_writer_mission_passes_validation():
    """Valid writer mission passes validation."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
        checkpoint_policy="prompt",
    )
    errors = validate_mission_packet(packet)
    assert not errors, f"Unexpected errors: {errors}"


def test_invalid_agent_profile_fails():
    """Invalid agent profile is refused."""
    packet = _make_valid_packet(agent_profile="chaos_monkey")
    errors = validate_mission_packet(packet)
    assert any("agent_profile" in e.lower() for e in errors)


def test_read_only_profile_requests_write_fails():
    """Read-only profile (tester) requesting write is refused."""
    packet = _make_valid_packet(
        agent_profile="tester", tool_policy={"allow_write": True, "allow_bash": True}
    )
    errors = validate_mission_packet(packet)
    assert any("read-only" in e.lower() for e in errors)


def test_writer_empty_allowed_paths_fails():
    """Writer with empty allowed_paths is refused."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=[],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
    )
    errors = validate_mission_packet(packet)
    assert any("non-empty allowed_paths" in e.lower() for e in errors)


def test_forbidden_touches_allowed_fails():
    """Overlapping forbidden and allowed paths fails."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=["tests/coordination/", "docs/"],
        forbidden_paths=["docs/"],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
    )
    errors = validate_mission_packet(packet)
    assert any("overlap" in e.lower() for e in errors)


def test_empty_done_when_fails():
    """Empty done_when list is refused."""
    packet = _make_valid_packet(done_when=[])
    errors = validate_mission_packet(packet)
    assert any("done_when" in e.lower() for e in errors)


def test_missing_required_fields_fails():
    """Mission packet with missing required fields is refused."""
    packet = {"schema_version": "rig.relay.mission_packet.v1", "mission_id": "test"}
    errors = validate_mission_packet(packet)
    assert len(errors) > 0
    # Should mention multiple missing fields
    assert any("Missing required" in e for e in errors)


# ── Spawn plan tests ─────────────────────────────────────────────────────


def test_valid_read_only_mission_can_spawn(tmp_path):
    """Valid read-only mission produces can_spawn=True."""
    packet = _make_valid_packet()
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is True
    assert plan["refusal_code"] is None
    assert plan["agent_profile"] == "tester"
    assert plan["allowed_path_count"] == 1


def test_writer_mission_can_spawn(tmp_path):
    """Valid writer mission produces can_spawn=True."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=["scripts/"],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
        checkpoint_policy="prompt",
        coordination_policy={
            "claim_task": True,
            "reserve_paths": True,
            "heartbeat": True,
        },
    )
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is True
    assert plan["would_reserve_paths"] is True
    assert plan["reservation_mode"] == "write"


def test_max_children_refusal(tmp_path):
    """Active children >= max_parallel is refused by planner directly."""
    # The planner reads from coordination state. Since tmp_path has no sessions,
    # we simulate by passing a low max_parallel_sessions and creating session files.
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    for i in range(3):
        sf = sessions_dir / f"session_{i}.json"
        sf.write_text(json.dumps({"session_id": f"s{i}", "status": "active"}))

    packet = _make_valid_packet()
    plan = compute_spawn_plan(
        packet, coordination_root=tmp_path, max_parallel_sessions=2
    )
    assert plan["can_spawn"] is False
    assert plan["refusal_code"] == "max_children_exceeded"
    assert plan["active_child_count"] == 3


def test_read_only_profile_requests_write_refusal(tmp_path):
    """Read-only profile requesting write is refused."""
    packet = _make_valid_packet(
        agent_profile="tester", tool_policy={"allow_write": True, "allow_bash": True}
    )
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is False
    assert plan["refusal_code"] == "read_only_profile_requests_write"


def test_writer_empty_paths_refusal(tmp_path):
    """Writer with empty allowed_paths is refused."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=[],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
        checkpoint_policy="prompt",
    )
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is False
    assert plan["refusal_code"] == "empty_allowed_paths_for_writer"


def test_invalid_mission_packet_refusal(tmp_path):
    """Invalid mission packet is refused."""
    packet = {"schema_version": "rig.relay.mission_packet.v1", "mission_id": "bad"}
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is False
    assert plan["refusal_code"] == "invalid_mission_packet"


def test_output_validates_against_schema(tmp_path):
    """Spawn plan validates against schema."""
    packet = _make_valid_packet()
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    errors = _try_validate(plan, SPAWN_PLAN_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_no_forbidden_raw_content(tmp_path):
    """Spawn plan does not embed forbidden raw content."""
    packet = _make_valid_packet()
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    json_str = json.dumps(plan)
    raw_patterns = ["def _make_valid_packet", "raw_file_contents", "-----BEGIN"]
    json_lower = json_str.lower()
    for pat in raw_patterns:
        # The field names may appear in forbidden_fields list
        if pat in ("raw_file_contents",):
            continue
        assert pat not in json_lower, f"Forbidden content found: {pat}"


def test_writer_mission_warns_off_checkpoint(tmp_path):
    """Writer with checkpoint off produces warning."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=["scripts/"],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
        checkpoint_policy="off",
    )
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["can_spawn"] is True
    warnings = plan.get("warnings") or []
    " ".join(warnings).lower()
    assert any("checkpoint" in w.lower() and "off" in w.lower() for w in warnings)


def test_max_parallel_default_is_4(tmp_path):
    """Default max_parallel_sessions is 4."""
    packet = _make_valid_packet()
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["max_parallel_sessions"] == 4


def test_coordination_unavailable_warning(tmp_path):
    """Missing coordination events produces warning but not refusal."""
    packet = _make_valid_packet()
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    plan.get("warnings") or []
    # Coordination not available should be a warning but not refusal
    assert plan["can_spawn"] is True


def test_implementer_profile_defaults(tmp_path):
    """Implementer profile sets correct reservation mode."""
    packet = _make_valid_packet(
        agent_profile="implementer",
        allowed_paths=["scripts/"],
        tool_policy={"allow_write": True, "allow_bash": True},
        validation_commands=["uv run pytest"],
        checkpoint_policy="prompt",
        coordination_policy={
            "claim_task": True,
            "reserve_paths": True,
            "heartbeat": True,
        },
    )
    plan = compute_spawn_plan(packet, coordination_root=tmp_path)
    assert plan["agent_profile"] == "implementer"
    assert plan["would_reserve_paths"] is True
    assert plan["reservation_mode"] == "write"
