from __future__ import annotations

import json
from pathlib import Path

from rig_relay.context.digester import ContextDigester, ContextDigestionResult
from rig_relay.coordination.models import CoordinationConflict, CoordinationSession
from rig_relay.coordination.store import CoordinationStore


def _write_events(store_root: Path, events: list[dict]) -> None:
    events_path = store_root / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, sort_keys=True) + "\n")


def test_digest_reads_real_events_jsonl(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(
        CoordinationSession(session_id="session-1", task_id="task-a", status="running")
    )
    store.reserve_paths(
        session_id="session-1",
        task_id="task-a",
        mode="write",
        paths=["src/main.py"],
        ttl_seconds=3600,
    )

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert result.schema_version == "rig.relay.context_digestion.v1"
    assert result.generated_at
    assert result.active_lane_count >= 1
    assert any(lane["session_id"] == "session-1" for lane in result.active_lanes)
    assert "src/main.py" in result.owned_paths
    assert "src/main.py" in result.do_not_touch_paths
    assert result.digest_sha256.startswith("sha256:")
    assert result.redaction_status == "content_light"
    assert result.source_event_range[1] >= result.source_event_range[0]


def test_digest_excludes_private_content(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(
        CoordinationSession(session_id="session-1", status="running")
    )
    store.publish_artifact(
        session_id="session-1",
        artifact_kind="evidence",
        artifact_uri="/safe/path/report.json",
        artifact_sha256="sha256:abc123",
    )

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    payload = json.dumps(
        {
            "schema_version": result.schema_version,
            "active_lanes": result.active_lanes,
            "owned_paths": result.owned_paths,
            "do_not_touch_paths": result.do_not_touch_paths,
            "recent_conflicts": result.recent_conflicts,
            "evidence_paths": result.evidence_paths,
        },
        sort_keys=True,
    )

    assert "api_key" not in payload.lower()
    assert "secret" not in payload.lower()
    assert "token" not in payload.lower()
    assert "/safe/path/report.json" in result.evidence_paths


def test_digest_computes_digest_sha256(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(
        CoordinationSession(session_id="session-1", task_id="task-a", status="running")
    )

    digester = ContextDigester()
    result1 = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))
    result2 = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert result1.digest_sha256.startswith("sha256:")
    assert len(result1.digest_sha256) > 10
    assert result1.digest_sha256 == result2.digest_sha256


def test_digest_active_lanes_count(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(CoordinationSession(session_id="s1", status="running"))
    store.register_session(CoordinationSession(session_id="s2", status="running"))
    store.register_session(CoordinationSession(session_id="s3", status="completed"))

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    session_ids = {lane["session_id"] for lane in result.active_lanes}
    assert "s1" in session_ids
    assert "s2" in session_ids
    assert "s3" in session_ids


def test_digest_do_not_touch_paths(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(
        CoordinationSession(session_id="session-a", status="running")
    )
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["src/a.py", "src/b.py"],
        ttl_seconds=3600,
    )

    store.register_session(
        CoordinationSession(session_id="session-b", status="running")
    )
    store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="write",
        paths=["tests/c.py"],
        ttl_seconds=3600,
    )

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert "src/a.py" in result.do_not_touch_paths
    assert "src/b.py" in result.do_not_touch_paths
    assert "tests/c.py" in result.do_not_touch_paths


def test_digest_with_release_gate(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(CoordinationSession(session_id="s1", status="running"))

    gate_path = tmp_path / "rc_gate.json"
    gate_path.write_text(
        json.dumps({
            "status": "blocked",
            "blockers": [{"id": "B-001", "description": "flaky test"}, "B-002"],
        }),
        encoding="utf-8",
    )

    digester = ContextDigester()
    result = digester.digest(
        store_root=str(store_root), repo_root=str(tmp_path), gate_path=str(gate_path)
    )

    assert result.release_gate_status == "blocked"
    assert "B-001" in result.open_blocker_ids
    assert "B-002" in result.open_blocker_ids


def test_digest_with_release_gate_missing(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(CoordinationSession(session_id="s1", status="running"))

    digester = ContextDigester()
    result = digester.digest(
        store_root=str(store_root), repo_root=str(tmp_path), gate_path=None
    )

    assert result.release_gate_status == "unknown"
    assert result.open_blocker_ids == []


def test_digest_empty_store(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert result.schema_version == "rig.relay.context_digestion.v1"
    assert result.active_lane_count == 0
    assert result.active_lanes == []
    assert result.owned_paths == []
    assert result.do_not_touch_paths == []
    assert result.source_event_range == (0, 0)
    assert result.digest_sha256.startswith("sha256:")


def test_digest_malformed_event_line_skip(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    events_path = store_root / "events.jsonl"
    events_path.write_text(
        json.dumps({"event_name": "valid", "sequence": 1})
        + "\n"
        + "this is not json\n"
        + json.dumps({"event_name": "valid2", "sequence": 2})
        + "\n",
        encoding="utf-8",
    )

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert result.source_event_range == (1, 2)


def test_digest_recent_conflicts(tmp_path: Path) -> None:
    store_root = tmp_path / "coordination"
    store_root.mkdir()

    store = CoordinationStore(store_root)
    store.register_session(CoordinationSession(session_id="s1", status="running"))
    store.register_session(CoordinationSession(session_id="s2", status="running"))

    store.report_conflict(
        CoordinationConflict(
            conflict_id="conflict-1",
            kind="path_write_overlap",
            session_id="s1",
            other_session_id="s2",
            task_id="task-a",
            paths=["src/main.py"],
            recommended_resolution="serialize_or_split_scope",
        )
    )

    digester = ContextDigester()
    result = digester.digest(store_root=str(store_root), repo_root=str(tmp_path))

    assert len(result.recent_conflicts) == 1
    assert result.recent_conflicts[0]["conflict_id"] == "conflict-1"
    assert result.recent_conflicts[0]["kind"] == "path_write_overlap"


def test_digestion_result_compute_digest_deterministic() -> None:
    result = ContextDigestionResult(
        generated_at="2026-01-01T00:00:00Z",
        source_commit="abc123",
        workspace_id="sha256:def456",
        active_lane_count=1,
        active_lanes=[
            {
                "session_id": "s1",
                "task_id": "t1",
                "status": "running",
                "reserved_paths": [],
                "last_heartbeat": "2026-01-01T00:00:00Z",
            }
        ],
        owned_paths=["src/a.py"],
        do_not_touch_paths=["src/a.py"],
        source_event_range=(1, 5),
    )

    d1 = result.compute_digest()
    d2 = result.compute_digest()
    assert d1 == d2
    assert d1.startswith("sha256:")
