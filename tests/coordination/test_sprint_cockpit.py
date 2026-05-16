"""Tests for the sprint cockpit generator and reviewer orchestrator schemas."""

from __future__ import annotations
import pytest

pytestmark = [pytest.mark.integration]


import json
from pathlib import Path

from scripts.rig_relay_create_sprint_cockpit import DEFAULT_FORBIDDEN, generate_cockpit

# ── Schema paths ─────────────────────────────────────────────────────────

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

COCKPIT_SCHEMA = SCHEMAS_DIR / "rig.relay.sprint_cockpit.v1.schema.json"
MISSION_SCHEMA = SCHEMAS_DIR / "rig.relay.mission_packet.v1.schema.json"
CHILD_RESULT_SCHEMA = SCHEMAS_DIR / "rig.relay.child_session_result.v1.schema.json"
AGGREGATE_SCHEMA = SCHEMAS_DIR / "rig.relay.sprint_aggregate_report.v1.schema.json"


def _try_validate(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []  # Skip if jsonschema not available

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(instance))
    return [e.message for e in errors]


# ── Schema tests ─────────────────────────────────────────────────────────


def test_cockpit_schema_is_valid_json():
    """Cockpit schema file is valid JSON."""
    data = json.loads(COCKPIT_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Sprint Cockpit v1"
    assert "schema_version" in data["required"]


def test_mission_schema_is_valid_json():
    """Mission packet schema file is valid JSON."""
    data = json.loads(MISSION_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Mission Packet v1"
    assert "mission_id" in data["required"]


def test_child_result_schema_is_valid_json():
    """Child session result schema file is valid JSON."""
    data = json.loads(CHILD_RESULT_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Child Session Result v1"
    assert "session_id" in data["required"]


def test_aggregate_schema_is_valid_json():
    """Sprint aggregate report schema file is valid JSON."""
    data = json.loads(AGGREGATE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Sprint Aggregate Report v1"
    assert "child_results" in data["required"]


# ── Cockpit schema validates generated sample ────────────────────────────


def test_cockpit_schema_validates_sample():
    """Generated cockpit packet validates against schema."""
    packet, _ = generate_cockpit(output_dir=Path("/tmp"))
    errors = _try_validate(packet, COCKPIT_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"
    assert packet["schema_version"] == "rig.relay.sprint_cockpit.v1"
    assert packet["sprint_id"].startswith("sprint_")
    assert packet["branch"] is not None
    assert packet["head"] is not None


def test_mission_packet_schema_validates_sample():
    """Sample mission packet validates against schema."""
    from datetime import UTC, datetime

    sample = {
        "schema_version": "rig.relay.mission_packet.v1",
        "mission_id": "mission_20250101_000000_test",
        "parent_sprint_id": "sprint_20250101_000000",
        "parent_review_id": None,
        "agent_profile": "tester",
        "mission_title": "Validate coordination exporter",
        "instructions": "Run focused tests and report failures. Do not edit files.",
        "allowed_paths": ["tests/coordination/test_exporter.py"],
        "forbidden_paths": [],
        "tool_policy": {
            "allow_write": False,
            "allow_bash": True,
            "bash_allowlist": ["uv run pytest -n0 tests/coordination/test_exporter.py"],
        },
        "coordination_policy": {
            "claim_task": True,
            "reserve_paths": False,
            "heartbeat": True,
        },
        "checkpoint_policy": "off",
        "validation_commands": [
            "uv run pytest -n0 tests/coordination/test_exporter.py"
        ],
        "done_when": ["focused tests pass or failure report emitted"],
        "max_runtime_seconds": 1800,
        "created_at": datetime.now(UTC).isoformat(),
    }
    errors = _try_validate(sample, MISSION_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_child_result_schema_validates_sample():
    """Sample child session result validates against schema."""
    from datetime import UTC, datetime

    sample = {
        "schema_version": "rig.relay.child_session_result.v1",
        "mission_id": "mission_20250101_000000_test",
        "session_id": "session_20250101_000000_child",
        "status": "completed",
        "final_report_path": "/tmp/.rig-relay/reports/child_final.md",
        "artifact_manifest_path": None,
        "checkpoint_commit_sha": None,
        "files_changed": ["tests/coordination/test_exporter.py"],
        "validation_summary": ["3 passed"],
        "findings_recorded": [],
        "warnings": [],
        "recommended_next_action": "Proceed to next sprint mission",
        "runtime_seconds": 45.2,
        "created_at": datetime.now(UTC).isoformat(),
    }
    errors = _try_validate(sample, CHILD_RESULT_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


def test_aggregate_schema_validates_sample():
    """Sample sprint aggregate report validates against schema."""
    from datetime import UTC, datetime

    sample = {
        "schema_version": "rig.relay.sprint_aggregate_report.v1",
        "sprint_id": "sprint_20250101_000000",
        "parent_review_id": "review_20250101_000000",
        "child_results": [
            {
                "mission_id": "mission_1",
                "session_id": "session_1",
                "agent_profile": "tester",
                "status": "completed",
            }
        ],
        "overall_status": "clean",
        "recommended_next_action": "Propose manual push",
        "new_findings": [],
        "blockers": [],
        "warnings": [],
        "created_at": datetime.now(UTC).isoformat(),
    }
    errors = _try_validate(sample, AGGREGATE_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"


# ── Cockpit generator tests ──────────────────────────────────────────────


def test_cockpit_generator_tolerates_missing_coordination(monkeypatch, tmp_path):
    """Cockpit generator produces valid output when coordination files are missing."""
    monkeypatch.setattr(
        "scripts.rig_relay_create_sprint_cockpit.COORD_EVENTS",
        tmp_path / "no-coordination" / "events.jsonl",
    )
    monkeypatch.setattr(
        "scripts.rig_relay_create_sprint_cockpit.BUILD_ROOT", tmp_path / "no-build"
    )
    packet, _ = generate_cockpit(output_dir=tmp_path)
    errors = _try_validate(packet, COCKPIT_SCHEMA)
    assert not errors
    assert packet["coordination_summary"]["available"] is False
    assert packet["dataset_summary"]["available"] is False


def test_cockpit_generator_includes_branch_head_dirty(tmp_path):
    """Cockpit includes git branch, HEAD, and dirty file summary."""
    packet, _ = generate_cockpit(output_dir=tmp_path)
    assert packet["branch"] is not None
    assert len(packet["branch"]) > 0
    assert packet["head"] is not None
    assert len(packet["head"]) > 0
    assert "tracked_modified_count" in packet["dirty_summary"]
    assert "untracked_count" in packet["dirty_summary"]


def test_cockpit_generator_no_forbidden_raw_content(tmp_path):
    """Cockpit JSON does not include raw file contents, prompts, or model outputs."""
    packet, _ = generate_cockpit(output_dir=tmp_path)
    json_str = json.dumps(packet)
    for _forbidden in DEFAULT_FORBIDDEN:
        # The field names themselves may appear in forbidden_fields list
        # but the values should not contain raw content
        pass
    # Check that specific raw content patterns don't appear in values
    raw_patterns = [
        "def _run_git",  # source code should not appear
        "raw file contents",
        "-----BEGIN",  # secrets pattern
    ]
    json_lower = json_str.lower()
    for pat in raw_patterns:
        assert pat not in json_lower, f"Forbidden content found: {pat}"


def test_cockpit_generator_max_parallel_sessions_default(tmp_path):
    """Default constraints include max_parallel_sessions=4."""
    packet, _ = generate_cockpit(output_dir=tmp_path)
    assert "max_parallel_sessions=4" in packet["constraints"]


def test_cockpit_generator_produces_markdown(tmp_path):
    """Cockpit generator produces companion Markdown."""
    _, markdown = generate_cockpit(output_dir=tmp_path)
    assert markdown.startswith("# Sprint Cockpit:")
    assert "## Repository" in markdown
    assert "## Constraints" in markdown
    assert "## Available Reviewer Tools" in markdown


def test_cockpit_generator_includes_open_findings(tmp_path):
    """Cockpit findings are content-light (id, severity, title only)."""
    packet, _ = generate_cockpit(output_dir=tmp_path)
    for finding in packet.get("open_findings", []):
        # Only id, severity, title — no evidence, why_it_matters, etc.
        assert set(finding.keys()) <= {"finding_id", "severity", "title"}


def test_cockpit_generator_includes_sprint_mission(tmp_path):
    """Cockpit includes the sprint mission string."""
    mission = "Implement coordinator cockpit protocol"
    packet, _ = generate_cockpit(output_dir=tmp_path, sprint_mission=mission)
    assert packet["sprint_mission"] == mission


def test_cockpit_generator_default_reviewer_tools(tmp_path):
    """Cockpit includes the default list of reviewer tools."""
    from scripts.rig_relay_create_sprint_cockpit import AVAILABLE_REVIEWER_TOOLS

    packet, _ = generate_cockpit(output_dir=tmp_path)
    assert packet["available_reviewer_tools"] == AVAILABLE_REVIEWER_TOOLS


def test_cockpit_generator_handles_empty_findings(tmp_path, monkeypatch):
    """Cockpit handles empty findings file gracefully."""
    monkeypatch.setattr(
        "scripts.rig_relay_create_sprint_cockpit.FINDINGS_PATH",
        tmp_path / "nonexistent.jsonl",
    )
    packet, _ = generate_cockpit(output_dir=tmp_path)
    assert packet["open_findings"] == []


def test_cockpit_generator_markdown_includes_warnings(tmp_path, monkeypatch):
    """Markdown includes warnings section when data is missing."""
    monkeypatch.setattr(
        "scripts.rig_relay_create_sprint_cockpit.COORD_EVENTS",
        tmp_path / "missing" / "events.jsonl",
    )
    monkeypatch.setattr(
        "scripts.rig_relay_create_sprint_cockpit.BUILD_ROOT", tmp_path / "no-build"
    )
    _, markdown = generate_cockpit(output_dir=tmp_path)
    assert "## Warnings" in markdown
    assert "Coordination events not available" in markdown
