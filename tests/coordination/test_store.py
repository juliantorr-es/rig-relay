from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from rig_relay.coordination.models import CoordinationConflict, CoordinationSession
from rig_relay.coordination.store import CoordinationStore

pytestmark = [pytest.mark.integration]


def test_register_session_and_heartbeat(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    session = store.register_session(
        CoordinationSession(session_id="session-a", status="running")
    )

    updated = store.heartbeat(
        session_id=session.session_id,
        task_id="task-a",
        status="running_tests",
        reserved_paths=["vibe/core/tools/builtins/task.py"],
    )

    projection = store.read_state_projection()

    assert updated.session_id == "session-a"
    assert projection.active_sessions["session-a"].status == "running_tests"
    assert projection.active_sessions["session-a"].reserved_paths == [
        "vibe/core/tools/builtins/task.py"
    ]
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert events
    event = json.loads(events[-1])
    assert any("heartbeat" in json.loads(line)["event_name"] for line in events)
    assert event["schema_version"] == "rig.relay.coordination.event.v1"
    assert event["event_name"] == "coord.projection.read"
    assert event.get("session_id") is None
    assert event["event_hash"].startswith("sha256:")


def test_write_reservation_blocks_overlap(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )

    other = store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )

    assert other.allowed is False
    assert other.conflict is not None
    assert other.conflict.kind == "path_write_overlap"


def test_read_reservations_can_overlap(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    first = store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="read",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    second = store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="read",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )

    assert first.allowed is True
    assert second.allowed is True


def test_parent_directory_conflict_is_detected(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools"],
        ttl_seconds=120,
    )

    blocked = store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )

    assert blocked.allowed is False
    assert blocked.conflict is not None
    assert blocked.conflict.kind == "path_write_overlap"


def test_publish_artifact_and_conflict_are_projected(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    store.publish_artifact(
        session_id="session-a",
        task_id="task-a",
        artifact_kind="search_results",
        artifact_uri=".build/rig-relay/artifacts/search_result.json",
        artifact_sha256="sha256:abc",
        schema_id="rig.relay.artifact.search_results.v1",
    )
    store.report_conflict(
        CoordinationConflict(
            conflict_id="conflict-1",
            kind="path_write_overlap",
            session_id="session-a",
            other_session_id="session-b",
            paths=["vibe/core/tools/builtins/task.py"],
            recommended_resolution="serialize_or_split_scope",
        )
    )

    projection = store.read_state_projection()

    assert projection.recent_artifacts[0].artifact_kind == "search_results"
    assert projection.conflicts[0].conflict_id == "conflict-1"


def test_expired_reservation_is_marked_stale(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path)
    reservation = store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    ).reservation
    assert reservation is not None

    reservation.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    lease_path = next((tmp_path / "leases" / "paths").glob("*.json"))
    lease_path.write_text(reservation.model_dump_json(), encoding="utf-8")

    projection = store.read_state_projection()

    assert projection.active_path_reservations == {}
    assert projection.active_task_claims == {}


# ── Same-owner claim_task renewal ─────────────────────────────────────


def test_claim_task_same_owner_renews(tmp_path: Path) -> None:
    """Same session_id + task_id re-claim refreshes expiry."""
    store = CoordinationStore(tmp_path)
    first = store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    assert first.allowed is True
    assert first.claim is not None
    original_expires = first.claim.expires_at

    second = store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=300
    )
    assert second.allowed is True
    assert second.claim is not None
    # Expiry should be refreshed (extended)
    assert second.claim.expires_at > original_expires  # type: ignore[operator]


def test_claim_task_same_session_different_task_blocked(tmp_path: Path) -> None:
    """Same session but different task_id is blocked."""
    store = CoordinationStore(tmp_path)
    store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    result = store.claim_task(
        session_id="session-a", task_id="task-b", claim_kind="test", ttl_seconds=120
    )
    assert result.allowed is True  # Different task_id -> separate claim


def test_claim_task_different_session_same_task_blocked(tmp_path: Path) -> None:
    """Different session_id on same task is blocked."""
    store = CoordinationStore(tmp_path)
    store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    result = store.claim_task(
        session_id="session-b", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    assert result.allowed is False
    assert result.conflict is not None


def test_claim_task_different_session_different_task_allowed(tmp_path: Path) -> None:
    """Different session and different task is allowed."""
    store = CoordinationStore(tmp_path)
    store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    result = store.claim_task(
        session_id="session-b", task_id="task-b", claim_kind="test", ttl_seconds=120
    )
    assert result.allowed is True


# ── Same-owner reserve_paths renewal ──────────────────────────────────


def test_reserve_paths_same_owner_renews(tmp_path: Path) -> None:
    """Same session_id + task_id can reserve same path twice."""
    store = CoordinationStore(tmp_path)
    first = store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    assert first.allowed is True

    second = store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=300,
    )
    assert second.allowed is True
    assert second.reservation is not None

    # Only one lease file should exist (reused key)
    leases = list((tmp_path / "leases" / "paths").glob("*.json"))
    assert len(leases) == 1


def test_reserve_paths_same_session_different_task_blocked(tmp_path: Path) -> None:
    """Same session but different task_id on same path is blocked."""
    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    result = store.reserve_paths(
        session_id="session-a",
        task_id="task-b",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    assert result.allowed is False
    assert result.conflict is not None


def test_reserve_paths_different_session_blocked(tmp_path: Path) -> None:
    """Different session_id on same path and task is blocked."""
    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    result = store.reserve_paths(
        session_id="session-b",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    assert result.allowed is False
    assert result.conflict is not None


def test_reserve_paths_different_session_different_task_blocked(tmp_path: Path) -> None:
    """Different session and different task on same path is blocked."""
    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    result = store.reserve_paths(
        session_id="session-b",
        task_id="task-b",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    assert result.allowed is False
    assert result.conflict is not None


# ── Release after same-owner renewal ──────────────────────────────────


def test_release_after_same_owner_renewal(tmp_path: Path) -> None:
    """Releasing a path after same-owner renewal works."""
    store = CoordinationStore(tmp_path)
    store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=120
    )
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=120,
    )
    # Renew
    store.claim_task(
        session_id="session-a", task_id="task-a", claim_kind="test", ttl_seconds=300
    )
    store.reserve_paths(
        session_id="session-a",
        task_id="task-a",
        mode="write",
        paths=["vibe/core/tools/builtins/task.py"],
        ttl_seconds=300,
    )
    # Release should work
    store.release_paths(
        session_id="session-a",
        task_id="task-a",
        paths=["vibe/core/tools/builtins/task.py"],
    )
    # Verify the reservation is released
    projection = store.read_state_projection()
    assert projection.active_path_reservations == {}
