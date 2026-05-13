from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rig_relay_export_coordination_datasets import (
    _build_artifact_reuse_row,
    _build_checkpoint_row,
    _build_conflict_row,
    _build_coordination_row,
    _check_forbidden,
    _load_json_schema,
    export_datasets,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def schemas_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "schemas"


@pytest.fixture
def empty_events_path(tmp_path: Path) -> Path:
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture
def tiny_events_path(tmp_path: Path) -> Path:
    """A small fixture with one event of each major type."""
    path = tmp_path / "events.jsonl"
    events = [
        # coord.session.registered
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "e1",
            "session_id": "sess-a",
            "sequence": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "event_name": "coord.session.registered",
            "event_hash": "sha256:e1hash",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "agent_profile_name": "explore",
                "event_kind": "session_registered",
                "status": "running",
                "path_hashes": ["sha256:abc"],
                "path_count": 1,
            },
        },
        # coord.path.reserved
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "e2",
            "session_id": "sess-a",
            "sequence": 2,
            "created_at": "2025-01-01T00:00:01Z",
            "event_name": "coord.path.reserved",
            "event_hash": "sha256:e2hash",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "path_reserved",
                "reservation_mode": "write",
                "reservation_status": "active",
                "path_hashes": ["sha256:def", "sha256:ghi"],
                "path_count": 2,
            },
        },
        # coord.path.reservation_refused
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "e3",
            "session_id": "sess-b",
            "sequence": 3,
            "created_at": "2025-01-01T00:00:02Z",
            "event_name": "coord.path.reservation_refused",
            "event_hash": "sha256:e3hash",
            "payload": {
                "session_id": "sess-b",
                "task_id": "task-1",
                "event_kind": "reservation_refused",
                "reservation_status": "refused",
                "conflict_kind": "path_write_overlap",
                "conflict_id": "c-1",
                "other_session_id": "sess-a",
                "resolution_kind": "serialize_or_split_scope",
                "path_hashes": ["sha256:def"],
                "path_count": 1,
            },
        },
        # coord.artifact.published
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "e4",
            "session_id": "sess-a",
            "sequence": 4,
            "created_at": "2025-01-01T00:00:03Z",
            "event_name": "coord.artifact.published",
            "event_hash": "sha256:e4hash",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "artifact_published",
                "artifact_kind": "search_results",
                "artifact_sha256": "sha256:art1",
            },
        },
        # coord.conflict.reported
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "e5",
            "session_id": "sess-b",
            "sequence": 5,
            "created_at": "2025-01-01T00:00:04Z",
            "event_name": "coord.conflict.reported",
            "event_hash": "sha256:e5hash",
            "payload": {
                "conflict_id": "c-2",
                "session_id": "sess-b",
                "task_id": "task-1",
                "event_kind": "conflict_reported",
                "conflict_kind": "stale_lease",
                "other_session_id": "sess-a",
                "resolution_kind": "takeover",
                "path_hashes": ["sha256:jkl"],
                "path_count": 1,
            },
        },
    ]
    lines = "\n".join(json.dumps(e, separators=(",", ":")) for e in events)
    path.write_text(lines + "\n", encoding="utf-8")
    return path


@pytest.fixture
def checkpoint_obs_path(tmp_path: Path) -> Path:
    """Checkpoint events in observability format (as emitted by log_local_event)."""
    path = tmp_path / "observability.jsonl"
    events = [
        {
            "schema_version": "rig.relay.observability.v1",
            "event_id": "obs-1",
            "session_id": "sess-a",
            "sequence": 10,
            "created_at": "2025-01-01T00:01:00Z",
            "event_name": "rig.relay.checkpoint.committed",
            "event_hash": "sha256:c1hash",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "checkpoint_committed",
                "branch": "main",
                "pre_commit_head": "abc123",
                "post_commit_head": "def456",
                "commit_sha": "def456",
                "files_committed_count": 2,
                "validation_summary_hash": "sha256:valhash",
                "checkpoint_artifact_sha256": "sha256:ckpt-art",
                "status": "committed",
                "warnings": [],
            },
        },
        {
            "schema_version": "rig.relay.observability.v1",
            "event_id": "obs-2",
            "session_id": "sess-b",
            "sequence": 11,
            "created_at": "2025-01-01T00:02:00Z",
            "event_name": "rig.relay.checkpoint.refused",
            "event_hash": "sha256:c2hash",
            "payload": {
                "session_id": "sess-b",
                "task_id": "task-2",
                "event_kind": "checkpoint_refused",
                "refusal_code": "include_paths is empty and allow_partial is false",
                "status": "refused",
                "warnings": [],
            },
        },
    ]
    lines = "\n".join(json.dumps(e, separators=(",", ":")) for e in events)
    path.write_text(lines + "\n", encoding="utf-8")
    return path


# ── Row builder tests ───────────────────────────────────────────────────


def test_build_coordination_row() -> None:
    event = {
        "event_id": "e1",
        "session_id": "sess-a",
        "sequence": 1,
        "created_at": "2025-01-01T00:00:00Z",
        "event_name": "coord.session.registered",
        "event_hash": "sha256:h",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "event_kind": "session_registered",
            "status": "running",
            "path_hashes": ["sha256:abc"],
            "path_count": 1,
        },
    }
    row = _build_coordination_row(event)
    assert row["event_id"] == "e1"
    assert row["session_id"] == "sess-a"
    assert row["event_name"] == "coord.session.registered"
    assert row["event_kind"] == "session_registered"
    assert row["path_count"] == 1
    assert row["path_hashes"] == ["sha256:abc"]


def test_build_conflict_row_from_refused() -> None:
    event = {
        "event_id": "e3",
        "session_id": "sess-b",
        "created_at": "2025-01-01T00:00:02Z",
        "event_name": "coord.path.reservation_refused",
        "event_hash": "sha256:h3",
        "payload": {
            "conflict_kind": "path_write_overlap",
            "conflict_id": "c-1",
            "session_id": "sess-b",
            "other_session_id": "sess-a",
            "resolution_kind": "serialize_or_split_scope",
            "path_hashes": ["sha256:def"],
            "path_count": 1,
        },
    }
    row = _build_conflict_row(event)
    assert row is not None
    assert row["conflict_id"] == "c-1"
    assert row["conflict_kind"] == "path_write_overlap"
    assert row["other_session_id"] == "sess-a"
    assert row["resolution_kind"] == "serialize_or_split_scope"


def test_build_conflict_row_returns_none_for_non_conflict() -> None:
    event = {
        "event_id": "e1",
        "payload": {"session_id": "s", "event_kind": "session_registered"},
    }
    row = _build_conflict_row(event)
    assert row is None


def test_build_artifact_reuse_row() -> None:
    event = {
        "event_id": "e4",
        "session_id": "sess-a",
        "created_at": "2025-01-01T00:00:03Z",
        "event_name": "coord.artifact.published",
        "event_hash": "sha256:h4",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "artifact_kind": "search_results",
            "artifact_sha256": "sha256:art1",
        },
    }
    row = _build_artifact_reuse_row(event)
    assert row is not None
    assert row["artifact_kind"] == "search_results"
    assert row["artifact_sha256"] == "sha256:art1"


def test_build_artifact_reuse_row_missing_fields() -> None:
    event = {"event_id": "e4", "payload": {"session_id": "s", "artifact_kind": "x"}}
    assert _build_artifact_reuse_row(event) is None  # missing artifact_sha256


def test_build_checkpoint_committed_row() -> None:
    event = {
        "event_id": "obs-1",
        "session_id": "sess-a",
        "created_at": "2025-01-01T00:01:00Z",
        "event_name": "rig.relay.checkpoint.committed",
        "event_hash": "sha256:c1",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "branch": "main",
            "pre_commit_head": "abc",
            "post_commit_head": "def",
            "commit_sha": "def",
            "files_committed_count": 2,
            "validation_summary_hash": "sha256:v",
            "checkpoint_artifact_sha256": "sha256:a",
            "status": "committed",
        },
    }
    row = _build_checkpoint_row(event)
    assert row["status"] == "committed"
    assert row["branch"] == "main"
    assert row["commit_sha"] == "def"
    assert row["files_committed_count"] == 2


def test_build_checkpoint_refused_row() -> None:
    event = {
        "event_id": "obs-2",
        "session_id": "sess-b",
        "created_at": "2025-01-01T00:02:00Z",
        "event_name": "rig.relay.checkpoint.refused",
        "event_hash": "sha256:c2",
        "payload": {
            "session_id": "sess-b",
            "task_id": "task-2",
            "refusal_code": "include_paths is empty",
            "status": "refused",
        },
    }
    row = _build_checkpoint_row(event)
    assert row["status"] == "refused"
    assert row["refusal_code"] == "include_paths is empty"


# ── Content-light enforcement ────────────────────────────────────────────


def test_check_forbidden_rejects_raw_content() -> None:
    row = {"session_id": "x", "prompt": "raw prompt", "model_output": "raw output"}
    violations = _check_forbidden(row)
    assert len(violations) >= 2


def test_check_forbidden_accepts_clean_row() -> None:
    row = {"session_id": "x", "artifact_sha256": "sha256:abc"}
    violations = _check_forbidden(row)
    assert violations == []


# ── Live schema validation ──────────────────────────────────────────────


def test_cross_session_coordination_row_validates(schemas_dir: Path) -> None:
    schema = _load_json_schema(
        schemas_dir, "rig.relay.cross_session_coordination.v1.schema.json"
    )
    row = {
        "schema_version": "rig.relay.cross_session_coordination.v1",
        "event_id": "e1",
        "session_id": "sess-a",
        "sequence": 1,
        "created_at": "2025-01-01T00:00:00Z",
        "event_name": "coord.session.registered",
        "event_hash": "sha256:h",
        "event_kind": "session_registered",
    }
    from scripts.rig_relay_export_coordination_datasets import _validate_row

    warnings: list[str] = []
    assert _validate_row(row, schema, strict=True, warnings=warnings)


def test_coordination_conflict_row_validates(schemas_dir: Path) -> None:
    schema = _load_json_schema(
        schemas_dir, "rig.relay.coordination_conflict.v1.schema.json"
    )
    row = {
        "schema_version": "rig.relay.coordination_conflict.v1",
        "conflict_id": "c-1",
        "session_id": "sess-b",
        "conflict_kind": "path_write_overlap",
        "created_at": "2025-01-01T00:00:00Z",
    }
    from scripts.rig_relay_export_coordination_datasets import _validate_row

    warnings: list[str] = []
    assert _validate_row(row, schema, strict=True, warnings=warnings)


def test_artifact_reuse_row_validates(schemas_dir: Path) -> None:
    schema = _load_json_schema(schemas_dir, "rig.relay.artifact_reuse.v1.schema.json")
    row = {
        "schema_version": "rig.relay.artifact_reuse.v1",
        "session_id": "sess-a",
        "artifact_kind": "search_results",
        "artifact_sha256": "sha256:art1",
        "created_at": "2025-01-01T00:00:00Z",
    }
    from scripts.rig_relay_export_coordination_datasets import _validate_row

    warnings: list[str] = []
    assert _validate_row(row, schema, strict=True, warnings=warnings)


def test_checkpoint_eval_row_validates(schemas_dir: Path) -> None:
    schema = _load_json_schema(schemas_dir, "rig.relay.checkpoint_eval.v1.schema.json")
    row = {
        "schema_version": "rig.relay.checkpoint_eval.v1",
        "session_id": "sess-a",
        "event_name": "rig.relay.checkpoint.committed",
        "status": "committed",
        "created_at": "2025-01-01T00:00:00Z",
    }
    from scripts.rig_relay_export_coordination_datasets import _validate_row

    warnings: list[str] = []
    assert _validate_row(row, schema, strict=True, warnings=warnings)


# ── End-to-end export ────────────────────────────────────────────────────


def test_empty_events_file_produces_warning(
    empty_events_path: Path, tmp_path: Path
) -> None:
    manifest = export_datasets(
        events_path=empty_events_path,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=False,
    )
    assert manifest["input_event_count"] == 0
    total = sum(manifest["row_counts"].values())
    assert total == 0


def test_missing_events_file_produces_warning(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.jsonl"
    manifest = export_datasets(
        events_path=missing,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=False,
    )
    assert len(manifest["warnings"]) >= 1
    assert any("not found" in w for w in manifest["warnings"])


def test_tiny_events_export_all_datasets(
    tiny_events_path: Path, tmp_path: Path
) -> None:
    manifest = export_datasets(
        events_path=tiny_events_path,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=True,
        observability_path=None,
    )
    assert manifest["input_event_count"] == 5
    assert manifest["row_counts"]["cross_session_coordination_dataset"] == 5
    assert (
        manifest["row_counts"]["coordination_conflict_dataset"] == 2
    )  # refused + conflict
    assert manifest["row_counts"]["artifact_reuse_dataset"] == 1
    assert manifest["row_counts"]["checkpoint_eval_dataset"] == 0  # no obs

    # Verify files exist with correct content
    for name in [
        "cross_session_coordination_dataset",
        "coordination_conflict_dataset",
        "artifact_reuse_dataset",
    ]:
        path = tmp_path / "out" / f"{name}.jsonl"
        assert path.is_file(), f"Missing {path}"
        assert path.stat().st_size > 0


def test_checkpoint_export_from_observability(
    tiny_events_path: Path, checkpoint_obs_path: Path, tmp_path: Path
) -> None:
    manifest = export_datasets(
        events_path=tiny_events_path,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=True,
        observability_path=checkpoint_obs_path,
    )
    assert manifest["row_counts"]["checkpoint_eval_dataset"] == 2
    path = tmp_path / "out" / "checkpoint_eval_dataset.jsonl"
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    import json

    row = json.loads(lines[0])
    assert row["status"] == "committed"
    row2 = json.loads(lines[1])
    assert row2["status"] == "refused"


def test_manifest_row_counts_match(tiny_events_path: Path, tmp_path: Path) -> None:
    manifest = export_datasets(
        events_path=tiny_events_path,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=True,
    )
    for name, expected_count in manifest["row_counts"].items():
        path = tmp_path / "out" / f"{name}.jsonl"
        if expected_count > 0:
            actual = sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _)
            assert actual == expected_count, (
                f"{name}: expected {expected_count}, got {actual}"
            )


def test_export_strips_forbidden_content(tmp_path: Path) -> None:
    """Verify that rows with forbidden fields get caught by content-light check."""
    events_path = tmp_path / "bad.jsonl"
    events = [
        {
            "schema_version": "rig.relay.coordination.event.v1",
            "event_id": "bad-1",
            "session_id": "sess-a",
            "sequence": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "event_name": "coord.session.registered",
            "event_hash": "sha256:bad",
            "payload": {"session_id": "sess-a", "prompt": "this should be caught"},
        }
    ]
    events_path.write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\n",
        encoding="utf-8",
    )

    manifest = export_datasets(
        events_path=events_path,
        output_dir=tmp_path / "out",
        schemas_dir=Path("docs/schemas"),
        strict=False,
    )
    # Should have a warning about forbidden content
    assert len(manifest["warnings"]) >= 1
    assert any("forbidden" in w.lower() for w in manifest["warnings"])


def test_strict_mode_fails_on_missing_input(tmp_path: Path) -> None:
    missing = tmp_path / "nope.jsonl"
    with pytest.raises(SystemExit):
        export_datasets(
            events_path=missing,
            output_dir=tmp_path / "out",
            schemas_dir=Path("docs/schemas"),
            strict=True,
        )
