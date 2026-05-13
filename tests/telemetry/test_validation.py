from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from vibe.core.telemetry import validate_evidence_session
from vibe.core.telemetry.artifacts import ToolOutputArtifactWriter
from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import dump_canonical_json
import vibe.core.telemetry.manifest as manifest_mod
from vibe.core.telemetry.manifest import write_session_manifest


def _write_event(log_file: Path, event: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(dump_canonical_json(event))
        handle.write("\n")


def _event(
    session_id: str, event_name: str, payload: dict, *, sequence: int = 0
) -> dict:
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": f"{session_id}-{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "created_at": "2024-01-01T00:00:00Z",
        "event_name": event_name,
        "payload": payload,
        "producer": {"name": "rig-relay", "version": "2.9.6"},
        "receipt_candidate": False,
        "event_hash": "sha256:abc",
    }
    body = dict(event)
    body.pop("event_hash")
    event["event_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )
    return event


def _sha256_prefix(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_valid_repo_local_evidence_session_passes(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    session_id = "session-1"
    session_root = repo_root / ".rig" / "relay" / "sessions" / session_id
    artifact_dir = session_root / "artifacts" / "tool-results"
    context_dir = session_root / "context"
    artifact_dir.mkdir(parents=True)
    context_dir.mkdir(parents=True)
    monkeypatch.chdir(repo_root)
    monkeypatch.setenv("RIG_RELAY_HOME", str(repo_root / ".rig" / "relay"))
    monkeypatch.setenv("RIG_RELAY_DISABLE_LEGACY_CONFIG", "1")

    artifact = ToolOutputArtifactWriter(session_id).write_artifact(
        tool_name="read_file", raw_output="abc"
    )
    artifact_path = Path(artifact.path)
    assembly_path = context_dir / "assembly_1.json"
    layout_path = context_dir / "layout_1.json"
    shadow_path = context_dir / "shadow_request_1.json"
    for path in [assembly_path, layout_path, shadow_path]:
        path.write_text(dump_canonical_json({"schema_version": "x"}), encoding="utf-8")

    log_file = session_root / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.ARTIFACT_WRITTEN,
            {
                "session_id": session_id,
                "evidence_kind": "tool_output_artifact",
                "evidence_relative_path": artifact_path.relative_to(
                    session_root
                ).as_posix(),
                "evidence_sha256": artifact.artifact_record_sha256,
                "artifact_id": artifact.artifact_id,
                "artifact_path": artifact_path.relative_to(session_root).as_posix(),
                "tool_name": "read_file",
                "raw_byte_size": artifact.byte_size,
                "prompt_visible_byte_size": len(
                    artifact.prompt_excerpt.encode("utf-8")
                ),
                "payload_sha256": artifact.payload_sha256,
                "truncated": True,
                "schema_version": "rig.relay.tool_output_artifact.v1",
            },
            sequence=1,
        ),
    )
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.CONTEXT_ASSEMBLY_REPORTED,
            {
                "session_id": session_id,
                "evidence_kind": "context_assembly_report",
                "evidence_relative_path": assembly_path.relative_to(
                    session_root
                ).as_posix(),
                "evidence_sha256": _sha256_prefix(assembly_path),
                "report_id": "report-1",
                "total_bytes": 1,
                "total_estimated_tokens": 1,
                "stable_prefix_bytes": 1,
                "dynamic_suffix_bytes": 0,
                "cache_candidate_bytes": 1,
                "stable_prefix_fingerprint": "sha256:1",
                "dynamic_suffix_fingerprint": "sha256:2",
                "largest_blocks": [],
                "optimization_hints": [],
            },
            sequence=2,
        ),
    )
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.CONTEXT_LAYOUT_PLANNED,
            {
                "session_id": session_id,
                "evidence_kind": "context_layout_plan",
                "evidence_relative_path": layout_path.relative_to(
                    session_root
                ).as_posix(),
                "evidence_sha256": _sha256_prefix(layout_path),
                "layout_id": "layout-1",
                "stable_prefix_fingerprint": "sha256:1",
                "dynamic_suffix_fingerprint": "sha256:2",
                "stable_prefix_fingerprint_short": "sha256:1",
                "dynamic_suffix_fingerprint_short": "sha256:2",
                "stable_prefix_bytes": 1,
                "dynamic_suffix_bytes": 0,
                "ephemeral_bytes": 0,
                "cache_candidate_bytes": 1,
                "cacheability_ratio": 1.0,
                "prefix_stability_status": "unknown",
                "prefix_change_reasons": [],
                "optimization_hints": [],
                "layout_path": layout_path.relative_to(session_root).as_posix(),
                "layout_hash": "sha256:abc",
            },
            sequence=3,
        ),
    )
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.SHADOW_REQUEST_ASSEMBLED,
            {
                "session_id": session_id,
                "evidence_kind": "shadow_request_report",
                "evidence_relative_path": shadow_path.relative_to(
                    session_root
                ).as_posix(),
                "evidence_sha256": _sha256_prefix(shadow_path),
                "actual_message_count": 1,
                "shadow_message_count": 1,
                "actual_estimated_tokens": 1,
                "shadow_estimated_tokens": 1,
                "stable_prefix_bytes": 1,
                "dynamic_suffix_bytes": 0,
                "cache_candidate_bytes": 1,
                "estimated_token_delta": 0,
                "byte_delta": 0,
                "unchanged_stable_prefix": True,
                "shadow_diff_summary": "ok",
                "reason_not_applied": "shadow_mode_only",
            },
            sequence=4,
        ),
    )
    write_session_manifest(session_root, session_id)

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "pass"
    assert result.event_count == 5
    assert result.referenced_file_count == 4
    assert result.unreferenced_evidence_file_count == 0


def test_missing_observability_jsonl_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert "observability.jsonl missing" in result.failed_checks


def test_absolute_path_reference_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    log_file = session / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.ARTIFACT_WRITTEN,
            {
                "session_id": "s1",
                "evidence_relative_path": str(tmp_path / "bad.json"),
                "evidence_sha256": "sha256:abc",
            },
            sequence=1,
        ),
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any(
        "unsafe evidence_relative_path" in check for check in result.failed_checks
    )


def test_path_escape_reference_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    log_file = session / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.ARTIFACT_WRITTEN,
            {
                "session_id": "s1",
                "evidence_relative_path": "../escape.json",
                "evidence_sha256": "sha256:abc",
            },
            sequence=1,
        ),
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any(
        "unsafe evidence_relative_path" in check for check in result.failed_checks
    )


def test_mismatched_hash_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    artifact_dir = session / "artifacts" / "tool-results"
    artifact_dir.mkdir(parents=True)
    artifact = artifact_dir / "0000_read_file_abcd.json"
    artifact.write_text("{}", encoding="utf-8")
    log_file = session / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.ARTIFACT_WRITTEN,
            {
                "session_id": "s1",
                "evidence_relative_path": artifact.relative_to(session).as_posix(),
                "evidence_sha256": "sha256:deadbeef",
            },
            sequence=1,
        ),
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any("evidence hash mismatch" in check for check in result.failed_checks)


def test_malformed_jsonl_line_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    (session / "observability.jsonl").write_text(
        '{"ok":1}\nNOT_JSON\n', encoding="utf-8"
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert result.malformed_event_count == 1
    assert any("line 2" in check for check in result.failed_checks)


def test_unreferenced_evidence_file_detected(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    artifact_dir = session / "artifacts" / "tool-results"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "0000_read_file_abcd.json").write_text("{}", encoding="utf-8")
    log_file = session / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    result = validate_evidence_session(root, "s1")
    assert result.unreferenced_evidence_file_count == 1
    assert result.status == "fail"


def test_old_style_session_warns_without_root_metadata(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    log_file = session / "observability.jsonl"
    _write_event(log_file, _event("s1", EventName.SESSION_STARTED, {}))
    result = validate_evidence_session(root, "s1")
    assert result.status == "warn"
    assert any("evidence_root_mode/source" in warning for warning in result.warnings)


def test_manifest_builder_is_stable_for_equivalent_inputs(tmp_path, monkeypatch):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    artifact_dir = session / "artifacts" / "tool-results"
    context_dir = session / "context"
    artifact_dir.mkdir(parents=True)
    context_dir.mkdir(parents=True)
    (session / "observability.jsonl").write_text("{}", encoding="utf-8")
    (artifact_dir / "a.json").write_text("{}", encoding="utf-8")
    (context_dir / "assembly_1.json").write_text("{}", encoding="utf-8")
    (context_dir / "layout_1.json").write_text("{}", encoding="utf-8")
    (context_dir / "shadow_request_1.json").write_text("{}", encoding="utf-8")

    fixed_now = type(
        "FrozenDatetime",
        (),
        {"now": staticmethod(lambda _tz=None: datetime(2024, 1, 1, tzinfo=UTC))},
    )
    monkeypatch.setattr(manifest_mod, "datetime", fixed_now)

    first = manifest_mod.build_manifest_bytes(session, "s1")
    second = manifest_mod.build_manifest_bytes(session, "s1")

    assert first == second
    data = json.loads(first)
    assert data["schema_version"] == "rig.relay.evidence_manifest.v1"
    assert {entry["relative_path"] for entry in data["entries"]} == {
        "artifacts/tool-results/a.json",
        "context/assembly_1.json",
        "context/layout_1.json",
        "context/shadow_request_1.json",
        "observability.jsonl",
    }


def test_manifest_sha_mismatch_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    context_dir = session / "context"
    context_dir.mkdir(parents=True)
    _write_event(
        session / "observability.jsonl",
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    (context_dir / "assembly_1.json").write_text("{}", encoding="utf-8")
    (session / "manifest.json").write_text(
        dump_canonical_json({
            "schema_version": "rig.relay.evidence_manifest.v1",
            "session_id": "s1",
            "created_at": "2024-01-01T00:00:00Z",
            "evidence_root_mode": "repo_local",
            "evidence_root_source": "RIG_RELAY_HOME",
            "entries": [
                {
                    "evidence_kind": "observability_log",
                    "relative_path": "observability.jsonl",
                    "sha256": _sha256_prefix(session / "observability.jsonl"),
                    "size_bytes": (session / "observability.jsonl").stat().st_size,
                },
                {
                    "evidence_kind": "context_assembly_report",
                    "relative_path": "context/assembly_1.json",
                    "sha256": "sha256:deadbeef",
                    "size_bytes": (context_dir / "assembly_1.json").stat().st_size,
                },
            ],
        })
        + "\n",
        encoding="utf-8",
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any(
        "manifest entry hash mismatch" in check for check in result.failed_checks
    )


def test_manifest_path_escape_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    (session / "observability.jsonl").write_text("{}", encoding="utf-8")
    (session / "manifest.json").write_text(
        dump_canonical_json({
            "schema_version": "rig.relay.evidence_manifest.v1",
            "session_id": "s1",
            "created_at": "2024-01-01T00:00:00Z",
            "evidence_root_mode": "repo_local",
            "evidence_root_source": "RIG_RELAY_HOME",
            "entries": [
                {
                    "evidence_kind": "observability_log",
                    "relative_path": "../escape.json",
                    "sha256": "sha256:deadbeef",
                    "size_bytes": 2,
                }
            ],
        })
        + "\n",
        encoding="utf-8",
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any("unsafe relative_path" in check for check in result.failed_checks)


def test_manifest_missing_file_fails(tmp_path):
    root = tmp_path / "root"
    session = root / "sessions" / "s1"
    session.mkdir(parents=True)
    log_file = session / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            "s1",
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    (session / "manifest.json").write_text(
        dump_canonical_json({
            "schema_version": "rig.relay.evidence_manifest.v1",
            "session_id": "s1",
            "created_at": "2024-01-01T00:00:00Z",
            "evidence_root_mode": "repo_local",
            "evidence_root_source": "RIG_RELAY_HOME",
            "entries": [
                {
                    "evidence_kind": "observability_log",
                    "relative_path": "observability.jsonl",
                    "sha256": _sha256_prefix(log_file),
                    "size_bytes": log_file.stat().st_size,
                },
                {
                    "evidence_kind": "context_assembly_report",
                    "relative_path": "context/assembly_1.json",
                    "sha256": "sha256:deadbeef",
                    "size_bytes": 2,
                },
            ],
        })
        + "\n",
        encoding="utf-8",
    )
    result = validate_evidence_session(root, "s1")
    assert result.status == "fail"
    assert any(
        "manifest entry missing evidence file" in check
        for check in result.failed_checks
    )
