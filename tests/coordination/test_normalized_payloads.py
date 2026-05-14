from __future__ import annotations

import json
from pathlib import Path

from rig_relay.coordination import (
    CoordinationArtifactRef,
    CoordinationConflict,
    CoordinationHeartbeat,
    CoordinationPathReservation,
    CoordinationSession,
    CoordinationTaskClaim,
    build_artifact_published_payload,
    build_checkpoint_committed_payload,
    build_checkpoint_refused_payload,
    build_conflict_reported_payload,
    build_heartbeat_payload,
    build_path_released_payload,
    build_path_reserved_payload,
    build_projection_read_payload,
    build_reservation_refused_payload,
    build_session_registered_payload,
    build_task_claim_payload,
    build_task_released_payload,
    reset_path_salt_for_testing,
)


def _reset():
    reset_path_salt_for_testing()


def test_session_registered_payload_has_normalized_fields() -> None:
    _reset()
    session = CoordinationSession(
        session_id="sess-1",
        task_id="task-1",
        agent_profile="explore",
        status="running",
        reserved_paths=["vibe/core/foo.py", "vibe/core/bar.py"],
    )
    payload = build_session_registered_payload(session)
    assert payload["session_id"] == "sess-1"
    assert payload["task_id"] == "task-1"
    assert payload["agent_profile_name"] == "explore"
    assert payload["event_kind"] == "session_registered"
    assert payload["status"] == "running"
    assert payload["path_count"] == 2
    assert len(payload["path_hashes"]) == 2
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")
    # No raw paths in normalized payload
    assert all(isinstance(h, str) for h in payload["path_hashes"])


def test_heartbeat_payload_includes_path_hashes_and_count() -> None:
    _reset()
    hb = CoordinationHeartbeat(
        session_id="sess-1",
        task_id="task-1",
        status="running_tests",
        current_step="step-3",
        reserved_paths=["vibe/core/tools/builtins/task.py"],
    )
    payload = build_heartbeat_payload(hb)
    assert payload["session_id"] == "sess-1"
    assert payload["task_id"] == "task-1"
    assert payload["event_kind"] == "heartbeat"
    assert payload["status"] == "running_tests"
    assert payload["current_step"] == "step-3"
    assert payload["path_count"] == 1
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")


def test_task_claim_payload_has_scope_hashes() -> None:
    _reset()
    claim = CoordinationTaskClaim(
        session_id="sess-1",
        task_id="task-1",
        claim_kind="implementation",
        ttl_seconds=120,
        scope_allowed_paths=["vibe/core/tools"],
    )
    payload = build_task_claim_payload(claim)
    assert payload["claim_kind"] == "implementation"
    assert payload["ttl_seconds"] == 120
    assert payload["scope_path_count"] == 1
    for h in payload["scope_path_hashes"]:
        assert h.startswith("sha256:")


def test_task_released_payload_is_light() -> None:
    payload = build_task_released_payload("sess-1", "task-1")
    assert payload["session_id"] == "sess-1"
    assert payload["task_id"] == "task-1"
    assert payload["event_kind"] == "task_released"
    assert payload["status"] == "released"
    # No extra fields
    assert set(payload.keys()) == {"session_id", "task_id", "event_kind", "status"}


def test_path_reserved_payload_includes_mode_status_and_hashes() -> None:
    _reset()
    res = CoordinationPathReservation(
        session_id="sess-1",
        task_id="task-1",
        mode="write",
        paths=["vibe/core/tools/foo.py", "vibe/core/tools/bar.py"],
        ttl_seconds=120,
        status="active",
    )
    payload = build_path_reserved_payload(res)
    assert payload["reservation_mode"] == "write"
    assert payload["reservation_status"] == "active"
    assert payload["path_count"] == 2
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")
    assert payload["ttl_seconds"] == 120


def test_path_released_payload_hashes_not_raw_paths() -> None:
    _reset()
    payload = build_path_released_payload("sess-1", "task-1", ["vibe/core/foo.py"])
    assert payload["reservation_status"] == "released"
    assert payload["path_count"] == 1
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")
    # No raw path strings
    assert not any("foo.py" in v for k, v in payload.items() if isinstance(v, str))


def test_reservation_refused_payload_has_conflict_fields() -> None:
    _reset()
    conflict = CoordinationConflict(
        conflict_id="conflict-1",
        kind="path_write_overlap",
        session_id="sess-1",
        other_session_id="sess-2",
        task_id="task-1",
        paths=["vibe/core/shared.py"],
        recommended_resolution="serialize_or_split_scope",
    )
    payload = build_reservation_refused_payload(conflict)
    assert payload["reservation_status"] == "refused"
    assert payload["conflict_kind"] == "path_write_overlap"
    assert payload["conflict_id"] == "conflict-1"
    assert payload["other_session_id"] == "sess-2"
    assert payload["resolution_kind"] == "serialize_or_split_scope"
    assert payload["path_count"] == 1
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")


def test_artifact_published_payload_has_kind_and_hash() -> None:
    _reset()
    art = CoordinationArtifactRef(
        session_id="sess-1",
        task_id="task-1",
        artifact_kind="search_results",
        artifact_uri=".build/rig-relay/artifacts/search.json",
        artifact_sha256="sha256:abc123",
        schema_id="rig.relay.artifact.search_results.v1",
    )
    payload = build_artifact_published_payload(art)
    assert payload["artifact_kind"] == "search_results"
    assert payload["artifact_sha256"] == "sha256:abc123"
    # No raw body/contents
    assert "contents" not in payload
    assert "body" not in payload


def test_conflict_reported_payload_has_kind_and_resolution() -> None:
    _reset()
    conflict = CoordinationConflict(
        conflict_id="conflict-2",
        kind="stale_lease",
        session_id="sess-1",
        other_session_id="sess-3",
        task_id="task-1",
        paths=["vibe/core/stale.py"],
        recommended_resolution="takeover",
    )
    payload = build_conflict_reported_payload(conflict)
    assert payload["conflict_kind"] == "stale_lease"
    assert payload["resolution_kind"] == "takeover"
    assert payload["path_count"] == 1
    for h in payload["path_hashes"]:
        assert h.startswith("sha256:")


def test_projection_read_payload_has_sha256() -> None:
    payload = build_projection_read_payload("sess-1", "sha256:proj123")
    assert payload["session_id"] == "sess-1"
    assert payload["event_kind"] == "projection_read"
    assert payload["projection_sha256"] == "sha256:proj123"


def test_checkpoint_committed_payload_is_content_light() -> None:
    payload = build_checkpoint_committed_payload(
        session_id="sess-1",
        task_id="task-1",
        branch="main",
        pre_commit_head="abc",
        post_commit_head="def",
        commit_sha="def",
        files_committed=["a.py", "b.py"],
        validation_summary=["uv run pytest"],
        artifact_sha256="sha256:art123",
    )
    assert payload["event_kind"] == "checkpoint_committed"
    assert payload["status"] == "committed"
    assert payload["branch"] == "main"
    assert payload["pre_commit_head"] == "abc"
    assert payload["post_commit_head"] == "def"
    assert payload["commit_sha"] == "def"
    assert payload["files_committed_count"] == 2
    assert payload["checkpoint_artifact_sha256"] == "sha256:art123"
    assert payload["validation_summary_hash"].startswith("sha256:")
    # No raw file contents or validation logs
    assert "contents" not in payload
    assert "validation_logs" not in payload


def test_checkpoint_refused_payload_has_refusal_code() -> None:
    payload = build_checkpoint_refused_payload(
        session_id="sess-1",
        task_id="task-1",
        refusal_code="include_paths is empty and allow_partial is false",
        warnings=["no files"],
    )
    assert payload["event_kind"] == "checkpoint_refused"
    assert payload["status"] == "refused"
    assert (
        payload["refusal_code"] == "include_paths is empty and allow_partial is false"
    )
    assert payload["warnings"] == ["no files"]
    # No commit fields
    assert "commit_sha" not in payload
    assert "branch" not in payload


def test_coordination_event_envelope_has_schema_version_event_id_sequence_created_at_event_name_payload_event_hash(
    tmp_path: Path,
) -> None:
    from rig_relay.coordination import (
        CoordinationEvent,
        CoordinationSession,
        CoordinationStore,
    )

    _reset()
    store = CoordinationStore(tmp_path)
    store.register_session(CoordinationSession(session_id="sess-1", status="running"))

    events_path = tmp_path / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1

    event = CoordinationEvent.model_validate_json(lines[0])
    assert event.schema_version == "rig.relay.coordination.event.v1"
    assert event.event_id is not None and len(event.event_id) > 0
    assert event.sequence >= 0
    assert event.created_at is not None
    assert event.event_name == "coord.session.registered"
    assert event.payload is not None
    assert event.event_hash is not None
    assert event.event_hash.startswith("sha256:")


def test_path_reserved_store_event_includes_reservation_mode_and_path_hashes(
    tmp_path: Path,
) -> None:
    _reset()
    from rig_relay.coordination import CoordinationEvent, CoordinationStore

    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="sess-1",
        task_id="task-1",
        mode="write",
        paths=["vibe/core/tools/foo.py", "vibe/core/tools/bar.py"],
        ttl_seconds=120,
    )

    events_path = tmp_path / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    # Find the coord.path.reserved event
    reserved_events = [l for l in lines if "coord.path.reserved" in l]
    assert len(reserved_events) >= 1

    event = CoordinationEvent.model_validate_json(reserved_events[0])
    assert event.event_name == "coord.path.reserved"
    assert event.payload["reservation_mode"] == "write"
    assert event.payload["reservation_status"] == "active"
    assert event.payload["path_count"] == 2
    assert len(event.payload["path_hashes"]) == 2
    for h in event.payload["path_hashes"]:
        assert h.startswith("sha256:")
    # No raw paths in event payload
    assert "foo.py" not in json.dumps(event.payload)


def test_reservation_refused_store_event_includes_refusal_reason(
    tmp_path: Path,
) -> None:
    _reset()
    from rig_relay.coordination import CoordinationEvent, CoordinationStore

    store = CoordinationStore(tmp_path)
    store.reserve_paths(
        session_id="sess-1",
        task_id="task-1",
        mode="write",
        paths=["vibe/core/shared.py"],
        ttl_seconds=120,
    )
    result = store.reserve_paths(
        session_id="sess-2",
        task_id="task-2",
        mode="write",
        paths=["vibe/core/shared.py"],
        ttl_seconds=120,
    )

    assert result.allowed is False

    events_path = tmp_path / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    refused_events = [l for l in lines if "coord.path.reservation_refused" in l]
    assert len(refused_events) >= 1

    event = CoordinationEvent.model_validate_json(refused_events[0])
    assert event.event_name == "coord.path.reservation_refused"
    assert event.payload["conflict_kind"] == "path_write_overlap"
    assert event.payload["other_session_id"] == "sess-1"
    assert event.payload["resolution_kind"] == "serialize_or_split_scope"


def test_artifact_published_store_event_includes_artifact_kind_and_hash(
    tmp_path: Path,
) -> None:
    _reset()
    from rig_relay.coordination import CoordinationEvent, CoordinationStore

    store = CoordinationStore(tmp_path)
    store.publish_artifact(
        session_id="sess-1",
        task_id="task-1",
        artifact_kind="search_results",
        artifact_uri=".build/rig-relay/artifacts/search.json",
        artifact_sha256="sha256:abc123",
        schema_id="rig.relay.artifact.search_results.v1",
    )

    events_path = tmp_path / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    pub_events = [l for l in lines if "coord.artifact.published" in l]
    assert len(pub_events) >= 1

    event = CoordinationEvent.model_validate_json(pub_events[0])
    assert event.event_name == "coord.artifact.published"
    assert event.payload["artifact_kind"] == "search_results"
    assert event.payload["artifact_sha256"] == "sha256:abc123"
    # No raw body
    assert "contents" not in event.payload


def test_no_raw_prompt_or_model_output_in_normalized_payloads() -> None:
    """Verify that normalized payloads never contain raw prompts or model output fields."""
    _reset()
    from rig_relay.coordination import (
        build_artifact_published_payload,
        build_heartbeat_payload,
        build_path_reserved_payload,
        build_session_registered_payload,
        build_task_claim_payload,
    )

    forbidden_keys = {
        "prompt",
        "model_output",
        "raw_output",
        "stdout",
        "stderr",
        "file_contents",
    }

    session = CoordinationSession(session_id="s-1", status="running")
    hb = CoordinationHeartbeat(session_id="s-1", status="running")
    claim = CoordinationTaskClaim(
        session_id="s-1", task_id="t-1", claim_kind="test", ttl_seconds=60
    )
    res = CoordinationPathReservation(
        session_id="s-1", task_id="t-1", mode="read", paths=[], ttl_seconds=60
    )
    art = CoordinationArtifactRef(
        session_id="s-1",
        artifact_kind="test",
        artifact_uri="u",
        artifact_sha256="sha256:x",
    )

    for payload in [
        build_session_registered_payload(session),
        build_heartbeat_payload(hb),
        build_task_claim_payload(claim),
        build_path_reserved_payload(res),
        build_artifact_published_payload(art),
    ]:
        for key in forbidden_keys:
            assert key not in payload, (
                f"Forbidden key '{key}' found in {payload.get('event_kind', 'unknown')}"
            )
