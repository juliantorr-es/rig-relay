from __future__ import annotations

from pathlib import Path
import time

from rig_relay.evidence.session_lifecycle import (
    SessionRetentionPolicy,
    SessionStorageCategory,
    audit_sessions_storage,
    classify_session_file,
    finalize_session_storage,
    find_session_compaction_candidates,
    find_session_prune_candidates,
)
from rig_relay.governance.mission_envelope import MissionEnvelope


def _make_file(path: Path, text: str = "x", days_ago: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if days_ago:
        past = time.time() - (days_ago * 86400)
        path.touch()
        import os

        os.utime(path, (past, past))
    return path


def _build_tree(tmp_path: Path) -> Path:
    root = tmp_path / ".rig" / "sessions"
    _make_file(root / "active" / "session.lock", "active")
    _make_file(root / "pinned" / "pin.lock", "pinned")
    _make_file(root / "s1" / "receipts.jsonl", "{}\n")
    _make_file(root / "s1" / "receipt.json", "{}\n")
    _make_file(root / "s1" / "telemetry_consent.json", "{}\n")
    _make_file(root / "s1" / "upload_receipt.json", "{}\n")
    _make_file(root / "s1" / "signed_local_action_envelope.json", "{}\n")
    _make_file(root / "s1" / "active_session.marker", "active")
    _make_file(root / "s1" / "pinned_session.marker", "pinned")
    _make_file(root / "s1" / "progress_events.jsonl", "{}\n")
    _make_file(root / "s1" / "intent_events.jsonl", "{}\n")
    _make_file(root / "s1" / "validation_report.json", "{}\n")
    _make_file(root / "s1" / "model_observation.json", "{}\n")
    _make_file(root / "s1" / "transcript.jsonl", "{}\n")
    _make_file(root / "s1" / "transcript.txt", "raw text", days_ago=40)
    _make_file(root / "s1" / "stdout.log", "stderr", days_ago=40)
    _make_file(root / "s1" / "debug_dump.json", "{}", days_ago=40)
    _make_file(root / "s1" / "tmp.cache", "cache", days_ago=40)
    _make_file(root / "s1" / "unknown.bin", "mystery", days_ago=40)
    return root


def test_classify_session_file_covers_known_categories(tmp_path: Path) -> None:
    assert (
        classify_session_file(tmp_path / "receipts.jsonl")
        is SessionStorageCategory.RECEIPTS
    )
    assert (
        classify_session_file(tmp_path / "telemetry_consent.json")
        is SessionStorageCategory.CONSENT
    )
    assert (
        classify_session_file(tmp_path / "upload_receipt.json")
        is SessionStorageCategory.UPLOAD_RECEIPTS
    )
    assert (
        classify_session_file(tmp_path / "signed_local_action_envelope.json")
        is SessionStorageCategory.SIGNED_ENVELOPES
    )
    assert (
        classify_session_file(tmp_path / "progress_events.jsonl")
        is SessionStorageCategory.PROGRESS_EVENTS
    )
    assert (
        classify_session_file(tmp_path / "intent_events.jsonl")
        is SessionStorageCategory.INTENT_EVENTS
    )
    assert (
        classify_session_file(tmp_path / "validation_report.json")
        is SessionStorageCategory.VALIDATION_ARTIFACTS
    )
    assert (
        classify_session_file(tmp_path / "model_observation.json")
        is SessionStorageCategory.MODEL_OBSERVATIONS
    )
    assert (
        classify_session_file(tmp_path / "transcript.txt")
        is SessionStorageCategory.RAW_TRANSCRIPTS
    )
    assert (
        classify_session_file(tmp_path / "transcript.jsonl")
        is SessionStorageCategory.RAW_TRANSCRIPTS
    )
    assert (
        classify_session_file(tmp_path / "stdout.log")
        is SessionStorageCategory.STDOUT_STDERR
    )
    assert (
        classify_session_file(tmp_path / "debug_dump.json")
        is SessionStorageCategory.DEBUG_DUMPS
    )
    assert (
        classify_session_file(tmp_path / "tmp.cache")
        is SessionStorageCategory.TEMP_FILES
    )
    assert (
        classify_session_file(tmp_path / "unknown.bin")
        is SessionStorageCategory.UNKNOWN
    )


def test_audit_and_candidates(tmp_path: Path) -> None:
    root = _build_tree(tmp_path)
    summary = audit_sessions_storage(root, top_n=5)

    assert summary.sessions_root == root
    assert summary.file_count > 0
    assert summary.total_bytes > 0
    assert summary.category_bytes[SessionStorageCategory.RECEIPTS] > 0
    assert summary.category_bytes[SessionStorageCategory.CONSENT] > 0
    assert summary.category_bytes[SessionStorageCategory.UPLOAD_RECEIPTS] > 0
    assert summary.category_bytes[SessionStorageCategory.SIGNED_ENVELOPES] > 0

    prune = find_session_prune_candidates(root, older_than_days=30)
    assert prune
    assert all(
        item.category
        not in {
            SessionStorageCategory.RECEIPTS,
            SessionStorageCategory.CONSENT,
            SessionStorageCategory.UPLOAD_RECEIPTS,
            SessionStorageCategory.SIGNED_ENVELOPES,
        }
        for item in prune
    )
    assert any(item.category is SessionStorageCategory.STDOUT_STDERR for item in prune)
    assert all(
        item.category
        not in {
            SessionStorageCategory.RECEIPTS,
            SessionStorageCategory.CONSENT,
            SessionStorageCategory.UPLOAD_RECEIPTS,
            SessionStorageCategory.SIGNED_ENVELOPES,
        }
        for item in find_session_compaction_candidates(root)
    )

    compact = find_session_compaction_candidates(root)
    assert compact
    assert all(
        item.category
        in {
            SessionStorageCategory.INTENT_EVENTS,
            SessionStorageCategory.PROGRESS_EVENTS,
            SessionStorageCategory.VALIDATION_ARTIFACTS,
            SessionStorageCategory.MODEL_OBSERVATIONS,
        }
        for item in compact
    )


def test_finalize_session_storage_current_session_only(tmp_path: Path) -> None:
    sessions_root = tmp_path / ".rig" / "sessions"
    current = sessions_root / "current"
    other = sessions_root / "other"
    _make_file(current / "intent_events.jsonl", '{"ok": true}\n')
    _make_file(current / "stdout.log", "some output", days_ago=40)
    _make_file(current / "receipt.json", "{}")
    _make_file(current / "telemetry_consent.json", "{}")
    _make_file(other / "stdout.log", "do not scan")

    result = finalize_session_storage(
        session_id="session-current",
        sessions_root=current,
        policy=SessionRetentionPolicy(),
    )

    assert result.session_id == "session-current"
    assert result.scanned_files == 4
    assert result.protected_files
    assert result.refused_files == ()
    assert result.prune_candidates
    assert result.deleted_files == ()
    assert result.receipt_path is not None
    assert result.manifest_path is not None
    assert result.receipt_path.is_file()
    assert result.manifest_path.is_file()
    assert not (other / "session_lifecycle_receipt.json").exists()


def test_finalize_session_storage_emits_content_light_receipt(tmp_path: Path) -> None:
    current = tmp_path / ".rig" / "sessions" / "session-a"
    _make_file(current / "intent_events.jsonl", '{"raw_prompt":"secret"}\n')
    _make_file(current / "stdout.log", "secret stdout", days_ago=40)
    result = finalize_session_storage(
        session_id="session-a", sessions_root=current, policy=SessionRetentionPolicy()
    )

    assert result.status in {"ok", "partial", "refused"}
    assert result.receipt_path is not None
    receipt_text = result.receipt_path.read_text(encoding="utf-8")
    assert "secret stdout" not in receipt_text
    assert "raw_prompt" not in receipt_text


def test_finalize_session_storage_optional_mission_linkage(tmp_path: Path) -> None:
    current = tmp_path / ".rig" / "sessions" / "session-b"
    _make_file(current / "intent_events.jsonl", '{"ok": true}\n')
    envelope = MissionEnvelope.model_validate({
        "schema_version": "rig.mission_envelope.v1",
        "mission_id": "mission-2026-05-14-session-finalize",
        "title": "Finalize session with mission linkage",
        "created_at": "2026-05-14T12:00:00+00:00",
        "repo_root": "/Users/user/Developer/GitHub/rig-relay",
        "branch": "main",
        "head": "61b46b8",
        "dirty_summary": {
            "tracked_modified_count": 0,
            "untracked_count": 0,
            "protected_dirty_count": 0,
        },
        "allowed_paths": [],
        "protected_paths": [],
        "instruction_paths": [],
        "acceptance_checks": [],
        "handoff_required": True,
    })
    result = finalize_session_storage(
        session_id="session-b",
        sessions_root=current,
        policy=SessionRetentionPolicy(),
        mission_envelope=envelope,
    )

    assert result.receipt_path is not None
    receipt = result.receipt_path.read_text(encoding="utf-8")
    assert envelope.mission_id in receipt
    assert envelope.fingerprint in receipt
    assert '"adr_id": null' in receipt or '"adr_id":' in receipt
    assert '"sprint_id": null' in receipt or '"sprint_id":' in receipt
