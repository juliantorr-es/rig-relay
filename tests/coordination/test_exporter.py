from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

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
            "event_hash": "sha256:45b700b28dcfdffea9233809e0cb232bd5e0d22f7149660d21f1776dd13c6334",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "agent_profile_name": "explore",
                "event_kind": "session_registered",
                "status": "running",
                "path_hashes": ["sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
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
            "event_hash": "sha256:d414ea28c481a3d48919de8f7126692a9e28cf71c39fa8a3d5efc6d23dba4676",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "path_reserved",
                "reservation_mode": "write",
                "reservation_status": "active",
                "path_hashes": ["sha256:cb8379ac2098aa165029e3938a51da0bcecfc008fd6795f401178647f96c5b34", "sha256:50ae61e841fac4e8f9e40baf2ad36ec868922ea48368c18f9535e47db56dd7fb"],
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
            "event_hash": "sha256:fc5577180df3c139c1851d4c67dc1be135c36ed62965ef5cd8b9f8a1ac6a7ebd",
            "payload": {
                "session_id": "sess-b",
                "task_id": "task-1",
                "event_kind": "reservation_refused",
                "reservation_status": "refused",
                "conflict_kind": "path_write_overlap",
                "conflict_id": "c-1",
                "other_session_id": "sess-a",
                "resolution_kind": "serialize_or_split_scope",
                "path_hashes": ["sha256:cb8379ac2098aa165029e3938a51da0bcecfc008fd6795f401178647f96c5b34"],
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
            "event_hash": "sha256:67e262b43a1d38709fdb08f4f77c3eda6618713585e656e9147a3b423c60f4ef",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "artifact_published",
                "artifact_kind": "search_results",
                "artifact_sha256": "sha256:2fdceec5cd7cf785f9caedb75f09d901ed20eabb93dab14eac23ac579214372c",
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
            "event_hash": "sha256:240b10c4dc63480f8168a6f36806e0032ca7e17442727cf7b5c93777756eaf51",
            "payload": {
                "conflict_id": "c-2",
                "session_id": "sess-b",
                "task_id": "task-1",
                "event_kind": "conflict_reported",
                "conflict_kind": "stale_lease",
                "other_session_id": "sess-a",
                "resolution_kind": "takeover",
                "path_hashes": ["sha256:268f277c6d766d31334fda0f7a5533a185598d269e61c76a805870244828a5f1"],
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
            "event_hash": "sha256:b6bfce3490009720269ef76d468c38254b11afb3d396f30e34827ae475655d5e",
            "payload": {
                "session_id": "sess-a",
                "task_id": "task-1",
                "event_kind": "checkpoint_committed",
                "branch": "main",
                "pre_commit_head": "abc123",
                "post_commit_head": "def456",
                "commit_sha": "def456",
                "files_committed_count": 2,
                "validation_summary_hash": "sha256:054c366f38d687d1a49c853f381ec4f2b027502eb3938671ff108e0b24a251a3",
                "checkpoint_artifact_sha256": "sha256:5c18e5457bfeb4466a37bb408ebc5ac7ab04e473d3f44447970a21fc37692b92",
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
            "event_hash": "sha256:a0016334dd1092ef308d350713909bd0c92834efbacf6b357533d89eae9a14eb",
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
        "event_hash": "sha256:aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "event_kind": "session_registered",
            "status": "running",
            "path_hashes": ["sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
            "path_count": 1,
        },
    }
    row = _build_coordination_row(event)
    assert row["event_id"] == "e1"
    assert row["session_id"] == "sess-a"
    assert row["event_name"] == "coord.session.registered"
    assert row["event_kind"] == "session_registered"
    assert row["path_count"] == 1
    assert row["path_hashes"] == ["sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"]


def test_build_conflict_row_from_refused() -> None:
    event = {
        "event_id": "e3",
        "session_id": "sess-b",
        "created_at": "2025-01-01T00:00:02Z",
        "event_name": "coord.path.reservation_refused",
        "event_hash": "sha256:97fb5f8538b89f6c1accfd19836b65a73b61fbc2e0cbf84bb858a0fffa3f1592",
        "payload": {
            "conflict_kind": "path_write_overlap",
            "conflict_id": "c-1",
            "session_id": "sess-b",
            "other_session_id": "sess-a",
            "resolution_kind": "serialize_or_split_scope",
            "path_hashes": ["sha256:cb8379ac2098aa165029e3938a51da0bcecfc008fd6795f401178647f96c5b34"],
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
        "event_hash": "sha256:e9590c04cea54beb769a96148583176605389b3a3809162f2fd6392b43fb8382",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "artifact_kind": "search_results",
            "artifact_sha256": "sha256:2fdceec5cd7cf785f9caedb75f09d901ed20eabb93dab14eac23ac579214372c",
        },
    }
    row = _build_artifact_reuse_row(event)
    assert row is not None
    assert row["artifact_kind"] == "search_results"
    assert row["artifact_sha256"] == "sha256:2fdceec5cd7cf785f9caedb75f09d901ed20eabb93dab14eac23ac579214372c"


def test_build_artifact_reuse_row_missing_fields() -> None:
    event = {"event_id": "e4", "payload": {"session_id": "s", "artifact_kind": "x"}}
    assert _build_artifact_reuse_row(event) is None  # missing artifact_sha256


def test_build_checkpoint_committed_row() -> None:
    event = {
        "event_id": "obs-1",
        "session_id": "sess-a",
        "created_at": "2025-01-01T00:01:00Z",
        "event_name": "rig.relay.checkpoint.committed",
        "event_hash": "sha256:d0f631ca1ddba8db3bcfcb9e057cdc98d0379f1bee00e75a545147a27dadd982",
        "payload": {
            "session_id": "sess-a",
            "task_id": "task-1",
            "branch": "main",
            "pre_commit_head": "abc",
            "post_commit_head": "def",
            "commit_sha": "def",
            "files_committed_count": 2,
            "validation_summary_hash": "sha256:4c94485e0c21ae6c41ce1dfe7b6bfaceea5ab68e40a2476f50208e526f506080",
            "checkpoint_artifact_sha256": "sha256:ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
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
        "event_hash": "sha256:9c0abe51c6e6655d81de2d044d4fb194931f058c0426c67c7285d8f5657ed64a",
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
    row = {"session_id": "x", "artifact_sha256": "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
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
        "event_hash": "sha256:aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123",
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
        "artifact_sha256": "sha256:2fdceec5cd7cf785f9caedb75f09d901ed20eabb93dab14eac23ac579214372c",
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
            "event_hash": "sha256:2f05d4b689d270cafb02285f35f44866f7dc8a2d368a3f9d1124373eeab31fb1",
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
