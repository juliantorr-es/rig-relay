"""Tests for the current-state pulse generator and schema."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from rig_relay.coordination.current_state import (
    generate_current_state as relay_generate_current_state,
)
from scripts.rig_relay_current_state import generate_current_state

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
CURRENT_STATE_SCHEMA = SCHEMAS_DIR / "rig.relay.current_state.v1.schema.json"


def _try_validate(instance: dict, schema_path: Path) -> list[str]:
    """Validate instance against schema, return errors."""
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def _write_session(sessions_dir: Path, session_id: str, **overrides: object) -> None:
    """Write a session state JSON file."""
    data: dict = {
        "session_id": session_id,
        "task_id": f"task_{session_id}",
        "agent_profile": "tester",
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "reserved_paths": [],
        "warnings": [],
    }
    data.update(overrides)
    (sessions_dir / f"{session_id}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _write_lease(
    leases_dir: Path,
    filename: str = "lease",
    *,
    session_id: str = "s1",
    mode: str = "read",
    paths: list[str] | None = None,
    **overrides: object,
) -> None:
    """Write a path lease JSON file."""
    data: dict = {
        "session_id": session_id,
        "task_id": f"task_{session_id}",
        "mode": mode,
        "paths": paths or [],
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(seconds=300)).isoformat(),
    }
    data.update(overrides)
    (leases_dir / f"lease_{filename}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _write_event(
    events_path: Path, event_name: str, **payload_overrides: object
) -> None:
    """Append a coordination event JSONL line."""
    payload: dict = {
        "session_id": "test_session",
        "task_id": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    payload.update(payload_overrides)
    event = {
        "event_name": event_name,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _write_derived(derived_dir: Path, name: str, rows: list[dict]) -> None:
    """Write a derived dataset JSONL file."""
    if not rows:
        # Write an empty file (to avoid counting as absent)
        (derived_dir / name).write_text("", encoding="utf-8")
        return
    with (derived_dir / name).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Schema tests ─────────────────────────────────────────────────────────


def test_current_state_schema_is_valid_json():
    """Current state schema file is valid JSON."""
    data = json.loads(CURRENT_STATE_SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert data["title"] == "Current State v1"
    assert "scope" in data["required"]


# ── Generator tests ──────────────────────────────────────────────────────


def test_current_state_schema_validates_generated(tmp_path):
    """Generated current state validates against schema."""
    state = generate_current_state(
        coordination_root=tmp_path / "coord", derived_dir=tmp_path / "derived"
    )
    errors = _try_validate(state, CURRENT_STATE_SCHEMA)
    assert not errors, f"Schema validation errors: {errors}"
    assert state["schema_version"] == "rig.relay.current_state.v1"
    assert state["summary"]["active_children"] == 0
    assert state["content_policy"] == "content_light"


def test_current_state_missing_derived_files(tmp_path):
    """Empty derived dir produces warnings, not crash."""
    der = tmp_path / "derived"
    der.mkdir(parents=True)
    state = generate_current_state(
        coordination_root=tmp_path / "coord", derived_dir=der
    )
    errors = _try_validate(state, CURRENT_STATE_SCHEMA)
    assert not errors
    warnings = state.get("warnings") or []
    assert any("Derived coordination dataset is empty" in w for w in warnings)


def test_current_state_with_fixtures(tmp_path):
    """Synthetic sessions/leases/events produce expected summary counts."""
    coord = tmp_path / "coord"
    der = tmp_path / "derived"
    sessions_dir = coord / "sessions"
    leases_dir = coord / "leases" / "paths"
    sessions_dir.mkdir(parents=True)
    leases_dir.mkdir(parents=True)
    der.mkdir(parents=True)

    # 3 active sessions: 2 implementers, 1 tester
    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="implementer",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s2",
        agent_profile="implementer",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s3",
        agent_profile="tester",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # Lease for s1 (write mode)
    _write_lease(leases_dir, "s1", mode="write", paths=["src/vibe/core/"])

    # Derived datasets with some rows
    _write_derived(
        der,
        "cross_session_coordination_dataset.jsonl",
        [{"event": "e1"}, {"event": "e2"}],
    )
    _write_derived(der, "artifact_reuse_dataset.jsonl", [{"artifact": "a1"}])

    state = generate_current_state(
        coordination_root=coord, derived_dir=der, max_children=4
    )
    errors = _try_validate(state, CURRENT_STATE_SCHEMA)
    assert not errors

    assert state["summary"]["active_children"] == 3
    assert state["summary"]["active_writers"] == 2
    assert state["summary"]["active_readers"] == 1
    assert state["summary"]["available_child_slots"] == 1
    assert len(state["children"]) == 3

    # Derived completeness
    dc = state.get("dataset_completeness", {})
    assert dc.get("coordination_rows") == 2
    assert dc.get("artifact_reuse_rows") == 1


def test_current_state_max_children(tmp_path):
    """Active children >= max_children produces wait recommendation."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    for i in range(5):
        _write_session(
            sessions_dir,
            f"s{i}",
            agent_profile="tester",
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived", max_children=4
    )
    assert state["summary"]["active_children"] == 5
    assert state["summary"]["available_child_slots"] == 0
    recs = state.get("recommendations") or []
    assert any("at or above max" in r.lower() for r in recs)


def test_current_state_writer_detection(tmp_path):
    """Implementer sessions are counted as writers."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="implementer",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s2",
        agent_profile="documenter",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s3",
        agent_profile="tester",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    assert state["summary"]["active_writers"] == 2
    assert state["summary"]["active_readers"] == 1
    recs = state.get("recommendations") or []
    assert any("writer" in r.lower() for r in recs)


def test_current_state_stale_lease_recommendation(tmp_path):
    """Stale lease event produces inspect recommendation."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="tester",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # Write events file with stale lease event
    events_path = coord / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    _write_event(
        events_path, "coord.lease.marked_stale", session_id="s1", task_id="task_s1"
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    assert state["summary"]["stale_leases"] >= 1
    recs = state.get("recommendations") or []
    assert any("stale lease" in r.lower() for r in recs)
    assert len(state.get("stale_items", [])) >= 1


def test_current_state_conflict_recommendation(tmp_path):
    """Conflict events produce inspect recommendation."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="tester",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    events_path = coord / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    _write_event(
        events_path,
        "coord.conflict.reported",
        conflict_id="conf_001",
        conflict_kind="path_overlap",
        other_session_id="s2",
        session_id="s1",
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    assert state["summary"]["conflicts"] >= 1
    recs = state.get("recommendations") or []
    assert any("conflict" in r.lower() for r in recs)
    assert len(state.get("recent_conflicts", [])) >= 1


def test_current_state_checkpoint_recommendation(tmp_path):
    """Writer with no checkpoints produces checkpoint policy reminder."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="implementer",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    assert state["summary"]["active_writers"] == 1
    assert state["summary"]["checkpoint_commits"] == 0
    recs = state.get("recommendations") or []
    assert any("checkpoint" in r.lower() for r in recs)


def test_current_state_forbidden_content(tmp_path):
    """Current state output contains no forbidden raw content."""
    state = generate_current_state(
        coordination_root=tmp_path / "coord", derived_dir=tmp_path / "derived"
    )
    json_str = json.dumps(state)
    # Check that fields exist (they appear as field names)
    assert "raw_file_contents" in json_str  # in forbidden_fields list
    assert "secrets" in json_str  # in forbidden_fields list

    # But raw content patterns should not be in values
    source_patterns = ["def generate_current_state", "def _read_jsonl", "-----BEGIN"]
    json_lower = json_str.lower()
    for pat in source_patterns:
        assert pat not in json_lower, f"Forbidden source content found: {pat}"


def test_current_state_implementer_completed_launch_tester(tmp_path):
    """Completed implementer leads to launch_tester recommendation."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    # An implementer that completed
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="implementer",
        status="completed",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    # Another active session
    _write_session(
        sessions_dir,
        "s2",
        agent_profile="tester",
        status="active",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    # implementer_completed only fires when writers==0 && active_children > 0
    # Since s1 is completed, it's not in active_sessions, so writers=0
    # s2 is active reader
    recs = state.get("recommendations") or []
    assert any("launch" in r.lower() for r in recs)


def test_current_state_heartbeat_age_risk(tmp_path):
    """Heartbeat age determines risk: critical > 180s."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    sessions_dir.mkdir(parents=True)

    old = datetime.now(UTC) - timedelta(seconds=200)
    recent = datetime.now(UTC) - timedelta(seconds=30)

    _write_session(
        sessions_dir,
        "s_old",
        agent_profile="implementer",
        created_at=old.isoformat(),
        updated_at=old.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s_recent",
        agent_profile="tester",
        created_at=recent.isoformat(),
        updated_at=recent.isoformat(),
    )

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )

    children = {c["session_id"]: c for c in state["children"]}
    assert children["s_old"]["risk"] == "critical"
    assert children["s_old"]["recommended_parent_action"] == "mark_stale"
    assert children["s_recent"]["risk"] == "normal"
    assert children["s_recent"]["recommended_parent_action"] == "wait"


def test_current_state_reservation_count(tmp_path):
    """Per-child reservation count from lease files."""
    coord = tmp_path / "coord"
    sessions_dir = coord / "sessions"
    leases_dir = coord / "leases" / "paths"
    sessions_dir.mkdir(parents=True)
    leases_dir.mkdir(parents=True)

    now = datetime.now(UTC)
    _write_session(
        sessions_dir,
        "s1",
        agent_profile="implementer",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    _write_session(
        sessions_dir,
        "s2",
        agent_profile="tester",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    # s1 has 2 active reservations, s2 has 0
    _write_lease(leases_dir, "s1_a", session_id="s1", mode="write", paths=["src/a/"])
    _write_lease(leases_dir, "s1_b", session_id="s1", mode="write", paths=["src/b/"])

    state = generate_current_state(
        coordination_root=coord, derived_dir=tmp_path / "derived"
    )
    children = {c["session_id"]: c for c in state["children"]}
    assert children["s1"]["reservation_count"] == 2
    assert children["s2"]["reservation_count"] == 0


# ── stable_path_key tests ────────────────────────────────────────────────


def test_stable_path_key_deterministic():
    """stable_path_key returns same key for same path within same repo."""
    from rig_relay.coordination._models import stable_path_key

    p1 = stable_path_key("tests/coordination/test_current_state.py")
    p2 = stable_path_key("tests/coordination/test_current_state.py")
    assert p1 == p2
    assert p1.startswith("coord:")


def test_stable_path_key_different_from_salted():
    """stable_path_key produces coord: prefix, salted_path_hash produces sha256: prefix."""
    from rig_relay.coordination._models import (
        reset_path_salt_for_testing,
        salted_path_hash,
        stable_path_key,
    )

    reset_path_salt_for_testing()

    key = stable_path_key("tests/coordination/test_current_state.py")
    salted = salted_path_hash("tests/coordination/test_current_state.py")
    assert key.startswith("coord:")
    assert salted.startswith("sha256:")
    assert key != salted


# ── Storage Status Tests ────────────────────────────────────────────────


def test_current_state_has_storage_status(tmp_path):
    """generate_current_state includes storage_status from compute_storage_summary."""
    state = generate_current_state(
        coordination_root=tmp_path, derived_dir=tmp_path / "derived"
    )
    assert "storage_status" in state
    storage = state["storage_status"]
    assert isinstance(storage, dict)
    assert "budget_status" in storage
    assert "total_size_bytes" in storage
    assert "total_size_mb" in storage
    # Missing build root should return warning dict, not crash
    assert storage["budget_status"] in (
        "unknown",
        "ok",
        "warn",
        "over_budget",
        "fleet_blocked",
    )


# ── Relay-native import tests ────────────────────────────────────────────


def test_relay_generate_current_state_returns_same_structure(tmp_path):
    """Both script and Relay-native import produce identical results."""
    p1 = generate_current_state(
        coordination_root=tmp_path, derived_dir=tmp_path / "derived"
    )
    p2 = relay_generate_current_state(
        coordination_root=tmp_path, derived_dir=tmp_path / "derived"
    )
    # Compare non-temporal fields (generated_at differs between calls)
    for key in ("schema_version", "scope", "content_policy", "forbidden_fields"):
        assert p1[key] == p2[key], f"Mismatch in key: {key}"
    assert p2["schema_version"] == "rig.relay.current_state.v1"
