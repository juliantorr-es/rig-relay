from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.migration]
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from scripts.rig_relay_dataset_export import (
    export_all,
    load_coordination_events,
    load_findings,
    load_observability_events,
    transform_coord_to_artifact_reuse,
    transform_coord_to_checkpoint,
    transform_coord_to_conflict,
    transform_coord_to_cross_session,
    transform_finding,
    transform_observability_to_provider_perf,
    transform_observability_to_tool_failure,
)

# ── Fixture helpers ──────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


_COORD_EVENT_TASK_CLAIMED = {
    "schema_version": "rig.relay.coordination.event.v1",
    "event_id": "evt-001",
    "event_name": "coord.task.claimed",
    "session_id": "sess-1",
    "task_id": "task-1",
    "sequence": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "event_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    "payload": {
        "event_kind": "task_claimed",
        "claim_kind": "search_replace",
        "session_id": "sess-1",
        "task_id": "task-1",
        "status": "active",
        "ttl_seconds": 300,
    },
}

_COORD_EVENT_PATH_RESERVED = {
    "schema_version": "rig.relay.coordination.event.v1",
    "event_id": "evt-002",
    "event_name": "coord.path.reserved",
    "session_id": "sess-1",
    "task_id": "task-1",
    "sequence": 2,
    "created_at": "2026-01-01T00:00:01Z",
    "event_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "payload": {
        "event_kind": "path_reserved",
        "reservation_mode": "write",
        "reservation_status": "active",
        "session_id": "sess-1",
        "task_id": "task-1",
        "path_hashes": [
            "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        ],
        "path_count": 1,
    },
}

_COORD_EVENT_RESERVATION_REFUSED = {
    "schema_version": "rig.relay.coordination.event.v1",
    "event_id": "evt-003",
    "event_name": "coord.path.reservation_refused",
    "session_id": "sess-2",
    "task_id": "task-2",
    "sequence": 3,
    "created_at": "2026-01-01T00:00:02Z",
    "event_hash": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "payload": {
        "event_kind": "reservation_refused",
        "reservation_status": "refused",
        "session_id": "sess-2",
        "task_id": "task-2",
        "conflict_id": "conflict-1",
        "conflict_kind": "path_write_overlap",
        "other_session_id": "sess-1",
        "resolution_kind": "serialize_or_split_scope",
        "path_hashes": [
            "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        ],
        "path_count": 1,
    },
}

_COORD_EVENT_ARTIFACT_PUBLISHED = {
    "schema_version": "rig.relay.coordination.event.v1",
    "event_id": "evt-004",
    "event_name": "coord.artifact.published",
    "session_id": "sess-1",
    "task_id": "task-1",
    "sequence": 4,
    "created_at": "2026-01-01T00:00:03Z",
    "event_hash": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "payload": {
        "event_kind": "artifact_published",
        "artifact_kind": "search_results",
        "artifact_sha256": "sha256:9999999999999999999999999999999999999999999999999999999999999999",
        "schema_id": "rig.relay.artifact.envelope.v1",
    },
}

_COORD_EVENT_CONFLICT_REPORTED = {
    "schema_version": "rig.relay.coordination.event.v1",
    "event_id": "evt-005",
    "event_name": "coord.conflict.reported",
    "session_id": "sess-2",
    "task_id": "task-2",
    "sequence": 5,
    "created_at": "2026-01-01T00:00:04Z",
    "event_hash": "sha256:5555555555555555555555555555555555555555555555555555555555555555",
    "payload": {
        "event_kind": "conflict_reported",
        "conflict_kind": "path_write_overlap",
        "conflict_id": "conflict-2",
        "other_session_id": "sess-1",
        "path_hashes": [
            "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        ],
        "path_count": 1,
    },
}

_OBS_CHECKPOINT_COMMITTED = {
    "event_name": "rig.relay.checkpoint.committed",
    "session_id": "sess-1",
    "task_id": "task-1",
    "created_at": "2026-01-01T00:00:10Z",
    "event_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "payload": {
        "branch": "main",
        "pre_commit_head": "abc123",
        "post_commit_head": "def456",
        "commit_sha": "def456",
        "files_committed_count": 3,
        "status": "committed",
    },
}

_OBS_CHECKPOINT_REFUSED = {
    "event_name": "rig.relay.checkpoint.refused",
    "session_id": "sess-2",
    "task_id": "task-2",
    "created_at": "2026-01-01T00:00:11Z",
    "event_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "payload": {
        "refusal_code": "dirty_file_overlap",
        "status": "refused",
        "warnings": ["path is dirty"],
    },
}

_OBS_TOOL_FAILURE = {
    "event_name": "rig.relay.tool.call_completed",
    "session_id": "sess-1",
    "task_id": "task-1",
    "created_at": "2026-01-01T00:00:20Z",
    "event_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "payload": {
        "tool_name": "write_file",
        "status": "refused",
        "warnings": ["dirty file guard"],
        "determinism_class": "deterministic_repo_state",
        "mutation_class": "writes_workspace",
        "model": "deepseek-v4-flash",
    },
}

_OBS_TOOL_SUCCESS = {
    "event_name": "rig.relay.tool.call_completed",
    "session_id": "sess-1",
    "task_id": "task-1",
    "created_at": "2026-01-01T00:00:21Z",
    "event_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "payload": {"tool_name": "read_file", "status": "success"},
}

_OBS_REQUEST_ACCOUNTED = {
    "event_name": "rig.relay.context.request_accounted",
    "session_id": "sess-1",
    "task_id": "task-1",
    "created_at": "2026-01-01T00:00:30Z",
    "event_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "payload": {
        "model": "deepseek-v4-flash",
        "context_accounting": {
            "model": "deepseek-v4-flash",
            "estimated_tokens": 2853,
            "total_chars": 11412,
            "total_messages": 2,
        },
    },
}

_FINDING_FIXTURE = {
    "schema_version": "rig.relay.out_of_scope_finding.v1",
    "finding_id": "finding_test_001",
    "finding_kind": "architecture_debt",
    "severity": "medium",
    "status": "open",
    "repo_area": "vibe/core/test",
    "language": "python",
    "title": "Test finding",
    "suggested_slice": "Fix test finding",
    "created_at": "2026-01-01T00:00:00Z",
}


# ── Tests ────────────────────────────────────────────────────────────────


def test_load_coordination_events_missing(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.jsonl"
    assert load_coordination_events(path) == []


def test_load_coordination_events_with_data(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, [_COORD_EVENT_TASK_CLAIMED])
    events = load_coordination_events(path)
    assert len(events) == 1
    assert events[0]["event_name"] == "coord.task.claimed"


def test_load_observability_events(tmp_path: Path) -> None:
    sess_dir = tmp_path / "sessions" / "sess-1"
    sess_dir.mkdir(parents=True)
    _write_jsonl(sess_dir / "observability.jsonl", [_OBS_TOOL_FAILURE])
    events = load_observability_events(tmp_path / "sessions")
    assert len(events) == 1


def test_load_findings(tmp_path: Path) -> None:
    path = tmp_path / "findings.jsonl"
    _write_jsonl(path, [_FINDING_FIXTURE])
    findings = load_findings(path)
    assert len(findings) == 1


def test_transform_coord_to_cross_session_task_claim() -> None:
    row = transform_coord_to_cross_session(_COORD_EVENT_TASK_CLAIMED)
    assert row is not None
    assert row["schema_version"] == "rig.relay.cross_session_coordination.v1"
    assert row["event_name"] == "coord.task.claimed"
    assert row["session_id"] == "sess-1"
    assert (
        row["event_hash"]
        == "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert row["claim_kind"] == "search_replace"
    assert row["ttl_seconds"] == 300
    assert "event_kind" in row


def test_transform_coord_to_cross_session_path_reserved() -> None:
    row = transform_coord_to_cross_session(_COORD_EVENT_PATH_RESERVED)
    assert row is not None
    assert row["event_name"] == "coord.path.reserved"
    assert row["reservation_mode"] == "write"
    assert "path_hashes" in row


def test_transform_coord_to_conflict_reservation_refused() -> None:
    row = transform_coord_to_conflict(_COORD_EVENT_RESERVATION_REFUSED)
    assert row is not None
    assert row["schema_version"] == "rig.relay.coordination_conflict.v1"
    assert row["conflict_id"] == "conflict-1"
    assert row["conflict_kind"] == "path_write_overlap"
    assert row["other_session_id"] == "sess-1"
    assert row["resolution_kind"] == "serialize_or_split_scope"


def test_transform_coord_to_conflict_reported() -> None:
    row = transform_coord_to_conflict(_COORD_EVENT_CONFLICT_REPORTED)
    assert row is not None
    assert row["conflict_kind"] == "path_write_overlap"
    assert row["conflict_id"] == "conflict-2"


def test_transform_coord_to_conflict_skips_non_conflict() -> None:
    row = transform_coord_to_conflict(_COORD_EVENT_TASK_CLAIMED)
    assert row is None


def test_transform_coord_to_artifact_reuse() -> None:
    row = transform_coord_to_artifact_reuse(_COORD_EVENT_ARTIFACT_PUBLISHED)
    assert row is not None
    assert row["schema_version"] == "rig.relay.artifact_reuse.v1"
    assert row["artifact_kind"] == "search_results"
    assert (
        row["artifact_sha256"]
        == "sha256:9999999999999999999999999999999999999999999999999999999999999999"
    )


def test_transform_coord_to_checkpoint_committed() -> None:
    row = transform_coord_to_checkpoint(_OBS_CHECKPOINT_COMMITTED)
    assert row is not None
    assert row["schema_version"] == "rig.relay.checkpoint_eval.v1"
    assert row["status"] == "committed"
    assert row["commit_sha"] == "def456"
    assert row["files_committed_count"] == 3


def test_transform_coord_to_checkpoint_refused() -> None:
    row = transform_coord_to_checkpoint(_OBS_CHECKPOINT_REFUSED)
    assert row is not None
    assert row["status"] == "refused"
    assert row["refusal_code"] == "dirty_file_overlap"


def test_transform_observability_to_tool_failure() -> None:
    row = transform_observability_to_tool_failure(_OBS_TOOL_FAILURE)
    assert row is not None
    assert row["tool_name"] == "write_file"
    assert row["status"] == "refused"
    assert row["determinism_class"] == "deterministic_repo_state"


def test_transform_observability_tool_failure_skips_success() -> None:
    row = transform_observability_to_tool_failure(_OBS_TOOL_SUCCESS)
    assert row is None


def test_transform_observability_to_provider_perf() -> None:
    row = transform_observability_to_provider_perf(_OBS_REQUEST_ACCOUNTED)
    assert row is not None
    assert row["model"] == "deepseek-v4-flash"
    assert row["estimated_tokens"] == 2853


def test_transform_finding() -> None:
    row = transform_finding(_FINDING_FIXTURE)
    assert row["finding_id"] == "finding_test_001"
    assert row["finding_kind"] == "architecture_debt"
    assert row["severity"] == "medium"
    assert row["suggested_slice"] == "Fix test finding"


def test_export_all_missing_inputs_non_strict(tmp_path: Path) -> None:
    """Missing inputs produce warnings but don't fail in non-strict mode."""
    manifest = export_all(
        coord_events_path=tmp_path / "no_events.jsonl",
        sessions_root=tmp_path / "no_sessions",
        findings_path=tmp_path / "no_findings.jsonl",
        schemas_dir=tmp_path / "no_schemas",
        output_dir=tmp_path / "output",
        strict=False,
    )
    assert manifest.warnings
    assert len(manifest.warnings) >= 3  # warnings for each missing input


def test_export_all_strict_fails_on_missing(tmp_path: Path) -> None:
    """Strict mode fails when required inputs are missing."""
    import pytest

    with pytest.raises(FileNotFoundError):
        export_all(
            coord_events_path=tmp_path / "no_events.jsonl",
            sessions_root=tmp_path / "no_sessions",
            findings_path=tmp_path / "no_findings.jsonl",
            schemas_dir=tmp_path / "no_schemas",
            output_dir=tmp_path / "output",
            strict=True,
        )


def test_export_all_with_fixtures(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Full pipeline with all data sources."""
    # Setup coordination events
    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(
        coord_path,
        [
            _COORD_EVENT_TASK_CLAIMED,
            _COORD_EVENT_PATH_RESERVED,
            _COORD_EVENT_RESERVATION_REFUSED,
            _COORD_EVENT_ARTIFACT_PUBLISHED,
            _COORD_EVENT_CONFLICT_REPORTED,
        ],
    )

    # Setup observability events
    sess_dir = tmp_path / "sessions" / "sess-1"
    sess_dir.mkdir(parents=True)
    _write_jsonl(
        sess_dir / "observability.jsonl",
        [
            _OBS_CHECKPOINT_COMMITTED,
            _OBS_CHECKPOINT_REFUSED,
            _OBS_TOOL_FAILURE,
            _OBS_TOOL_SUCCESS,
            _OBS_REQUEST_ACCOUNTED,
        ],
    )

    # Setup findings
    findings_path = tmp_path / "findings.jsonl"
    _write_jsonl(findings_path, [_FINDING_FIXTURE])

    # Setup schemas (copy from real schemas dir)
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir(parents=True)
    _copy_schemas(schemas_dir)

    output_dir = tmp_path / "output"
    manifest = export_all(
        coord_events_path=coord_path,
        sessions_root=tmp_path / "sessions",
        findings_path=findings_path,
        schemas_dir=schemas_dir,
        output_dir=output_dir,
        strict=False,
    )

    # Verify row counts
    assert (
        manifest.row_counts["cross_session_coordination_dataset"] == 5
    )  # all 5 coord events
    assert (
        manifest.row_counts["coordination_conflict_dataset"] == 2
    )  # reservation_refused + conflict_reported
    assert manifest.row_counts["artifact_reuse_dataset"] == 1  # artifact_published
    assert manifest.row_counts["checkpoint_eval_dataset"] == 2  # committed + refused
    assert manifest.row_counts["tool_failure_patterns_dataset"] == 1  # 1 failure
    assert (
        manifest.row_counts["provider_task_performance_dataset"] == 1
    )  # 1 request_accounted
    assert manifest.row_counts["findings_dataset"] == 1  # 1 finding

    # Verify output files exist
    assert (output_dir / "cross_session_coordination_dataset.jsonl").is_file()
    assert (output_dir / "coordination_conflict_dataset.jsonl").is_file()
    assert (output_dir / "artifact_reuse_dataset.jsonl").is_file()
    assert (output_dir / "checkpoint_eval_dataset.jsonl").is_file()
    assert (output_dir / "tool_failure_patterns_dataset.jsonl").is_file()
    assert (output_dir / "provider_task_performance_dataset.jsonl").is_file()
    assert (output_dir / "findings_dataset.jsonl").is_file()
    assert (output_dir / "export_manifest.json").is_file()

    # Verify manifest content
    manifest_rows = json.loads(
        (output_dir / "export_manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(manifest_rows, dict)
    assert manifest_rows.get("content_light_guarantee") is True
    assert "row_counts" in manifest_rows

    # Verify schema validation ran
    assert "cross_session_coordination_dataset" in manifest.validation_results


def test_export_all_schema_validation(tmp_path: Path) -> None:
    """Schema validation is run for coordination/checkpoint datasets."""
    coord_path = tmp_path / "events.jsonl"
    _write_jsonl(coord_path, [_COORD_EVENT_TASK_CLAIMED])

    sess_dir = tmp_path / "sessions" / "sess-1"
    sess_dir.mkdir(parents=True)
    _write_jsonl(sess_dir / "observability.jsonl", [_OBS_CHECKPOINT_COMMITTED])

    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir(parents=True)
    _copy_schemas(schemas_dir)

    manifest = export_all(
        coord_events_path=coord_path,
        sessions_root=tmp_path / "sessions",
        findings_path=tmp_path / "no_findings.jsonl",
        schemas_dir=schemas_dir,
        output_dir=tmp_path / "output2",
        strict=False,
    )

    assert (
        manifest.validation_results["cross_session_coordination_dataset"]["total"] == 1
    )
    assert (
        manifest.validation_results["cross_session_coordination_dataset"]["valid"] == 1
    )
    assert manifest.validation_results["checkpoint_eval_dataset"]["total"] == 1
    assert manifest.validation_results["checkpoint_eval_dataset"]["valid"] == 1


def test_export_all_forbidden_fields_not_in_rows(tmp_path: Path) -> None:
    """Privacy safeguard: raw fields don't appear in exported data."""
    coord_path = tmp_path / "events.jsonl"
    # Create an event with raw fields in payload
    bad_event = dict(_COORD_EVENT_TASK_CLAIMED)
    bad_event["payload"]["raw_prompt"] = "secret-prompt"
    bad_event["payload"]["raw_output"] = "secret-output"
    _write_jsonl(coord_path, [bad_event])

    output_dir = tmp_path / "output3"
    _ = export_all(
        coord_events_path=coord_path,
        sessions_root=tmp_path / "no_sessions",
        findings_path=tmp_path / "no_findings.jsonl",
        schemas_dir=tmp_path / "no_schemas",
        output_dir=output_dir,
        strict=False,
    )

    # Load the exported rows and check raw fields are absent
    exported = load_coordination_events(
        output_dir / "cross_session_coordination_dataset.jsonl"
    )
    for row in exported:
        assert "raw_prompt" not in row
        assert "raw_output" not in row
        assert "secret-prompt" not in (json.dumps(row))


def _copy_schemas(schemas_dir: Path) -> None:
    """Copy the four coordination/checkpoint schema files to the test dir."""
    src = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
    for name in [
        "rig.relay.cross_session_coordination.v1.schema.json",
        "rig.relay.coordination_conflict.v1.schema.json",
        "rig.relay.artifact_reuse.v1.schema.json",
        "rig.relay.checkpoint_eval.v1.schema.json",
    ]:
        path = src / name
        if path.is_file():
            (schemas_dir / name).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
