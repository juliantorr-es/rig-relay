"""Tests for tool receipt evidence index.

Tests cover:
- building an index from receipt captured events
- ignoring unrelated observability events
- handling malformed unrelated events safely
- detecting or rejecting malformed receipt events
- preserving bash receipt hashes and byte counts
- preserving mutation receipt before/after hashes when present
- summary counts by tool
- summary counts by status
- forbidden raw fields are absent from index records
- script emits valid JSON
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.evidence.receipt_index import (
    FORBIDDEN_RAW_FIELD_NAMES,
    ReceiptIndexBuildError,
    ReceiptIndexSummary,
    ToolReceiptIndexRecord,
    build_receipt_index,
    summarize_receipt_index,
    validate_index_content_light,
)
from vibe.core.telemetry.constants import EventName

# ── Helpers ───────────────────────────────────────────────────────────


def _make_bash_receipt_event(
    session_id: str = "test_session",
    tool_name: str = "bash",
    command: str = "echo hi",
    status: str = "success",
    exit_code: int = 0,
    stdout_bytes: int = 3,
    stderr_bytes: int = 0,
    duration_ms: float = 10.0,
    stdout_sha256: str | None = None,
    stderr_sha256: str | None = None,
    error_kind: str | None = None,
    refusal_reason: str | None = None,
) -> dict:
    if stdout_sha256 is None:
        stdout_sha256 = hashlib.sha256(b"hi\n").hexdigest()
    if stderr_sha256 is None:
        stderr_sha256 = hashlib.sha256(b"").hexdigest()
    return {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "evt-001",
        "session_id": session_id,
        "sequence": 0,
        "created_at": "2026-05-13T00:00:00",
        "event_name": EventName.TOOL_RECEIPT_CAPTURED,
        "payload": {
            "tool_name": tool_name,
            "receipt": {
                "command": command,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
                "stdout_sha256": stdout_sha256,
                "stderr_sha256": stderr_sha256,
                "error_kind": error_kind,
                "refusal_reason": refusal_reason,
            },
        },
        "producer": {"name": "rig-relay", "version": "0.1.0"},
        "receipt_candidate": True,
        "event_hash": "sha256:abc",
    }


def _make_search_replace_receipt_event(
    session_id: str = "test_session",
    status: str = "success",
    file: str = "test.py",
    blocks_applied: int = 1,
    lines_changed: int = 2,
    changed_files: list[str] | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    error_kind: str | None = None,
    refusal_reason: str | None = None,
    duration_ms: float = 5.0,
) -> dict:
    if changed_files is None:
        changed_files = ["test.py"]
    if before_hash is None:
        before_hash = hashlib.sha256(b"old content").hexdigest()
    if after_hash is None:
        after_hash = hashlib.sha256(b"new content").hexdigest()
    return {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "evt-002",
        "session_id": session_id,
        "sequence": 1,
        "created_at": "2026-05-13T00:00:01",
        "event_name": EventName.TOOL_RECEIPT_CAPTURED,
        "payload": {
            "tool_name": "search_replace",
            "receipt": {
                "file": file,
                "status": status,
                "blocks_applied": blocks_applied,
                "lines_changed": lines_changed,
                "replacements": blocks_applied,
                "warnings": [],
                "before_file_sha256": {file: before_hash} if before_hash else {},
                "after_file_sha256": {file: after_hash} if after_hash else {},
                "changed_files": changed_files,
                "failed_block_count": 0,
                "total_block_count": blocks_applied,
                "before_bytes": 11,
                "after_bytes": 11,
                "error_kind": error_kind,
                "refusal_reason": refusal_reason,
                "duration_ms": duration_ms,
            },
        },
        "producer": {"name": "rig-relay", "version": "0.1.0"},
        "receipt_candidate": True,
        "event_hash": "sha256:def",
    }


def _make_validate_receipt_event(
    session_id: str = "test_session",
    tool_name: str = "validate",
    profile: str = "quick",
    status: str = "passed",
    command_count: int = 1,
    passed_count: int = 1,
    failed_count: int = 0,
    skipped_count: int = 0,
    duration_ms: float = 20.0,
    blocker_summary: dict | None = None,
    error_kind: str | None = None,
    refusal_reason: str | None = None,
    check_receipts: list[dict] | None = None,
) -> dict:
    if blocker_summary is None:
        blocker_summary = {}
    if check_receipts is None:
        check_receipts = [
            {
                "check_id": "git_status",
                "command_kind": "git",
                "status": "passed",
                "exit_code": 0,
                "duration_ms": 10.0,
                "stdout_sha256": "abc",
                "stderr_sha256": "def",
                "stdout_bytes": 100,
                "stderr_bytes": 0,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        ]
    receipt: dict[str, object] = {
        "schema_version": "rig.relay.validate_receipt.v1",
        "profile": profile,
        "status": status,
        "command_count": command_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "duration_ms": duration_ms,
        "blocker_summary": blocker_summary,
        "check_receipts": check_receipts,
    }
    if error_kind is not None:
        receipt["error_kind"] = error_kind
    if refusal_reason is not None:
        receipt["refusal_reason"] = refusal_reason
    return {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "evt-003",
        "session_id": session_id,
        "sequence": 3,
        "created_at": "2026-05-13T00:00:03",
        "event_name": EventName.TOOL_RECEIPT_CAPTURED,
        "payload": {"tool_name": tool_name, "receipt": receipt},
        "producer": {"name": "rig-relay", "version": "0.1.0"},
        "receipt_candidate": True,
        "event_hash": "sha256:ghi",
    }


def _make_unrelated_event(session_id: str = "test_session") -> dict:
    return {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "evt-999",
        "session_id": session_id,
        "sequence": 99,
        "created_at": "2026-05-13T00:00:02",
        "event_name": "rig.relay.session.started",
        "payload": {},
        "producer": {"name": "rig-relay", "version": "0.1.0"},
        "receipt_candidate": False,
        "event_hash": "sha256:xyz",
    }


def _write_observability(path: Path, events: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, sort_keys=True) + "\n")
    return path


# ── Model tests ───────────────────────────────────────────────────────


def test_tool_receipt_index_record_requires_session_id() -> None:
    """Record requires session_id and tool_name (minimal fields)."""
    record = ToolReceiptIndexRecord(session_id="s1", tool_name="bash")
    assert record.session_id == "s1"
    assert record.tool_name == "bash"
    assert record.event_name == EventName.TOOL_RECEIPT_CAPTURED
    assert record.status is None


def test_tool_receipt_index_record_extra_forbidden() -> None:
    """Record rejects extra fields via ConfigDict(extra='forbid')."""
    with pytest.raises(ValidationError):
        ToolReceiptIndexRecord.model_validate({
            "session_id": "s1",
            "tool_name": "bash",
            "unknown_field": "x",
        })


def test_tool_receipt_index_record_content_light_by_default() -> None:
    """Record has no raw output fields in its model fields."""
    record = ToolReceiptIndexRecord(session_id="s1", tool_name="bash")
    dumped = record.model_dump(mode="json")
    for key in dumped:
        lower = key.lower()
        if lower.endswith("_sha256") or lower.endswith("_hash"):
            continue
        assert lower not in (
            "stdout",
            "stderr",
            "output",
            "content",
            "diff",
            "snippet",
            "old",
            "new",
            "replacement_text",
            "file_contents",
            "old_text",
            "new_text",
        ), key


# ── Index builder: basic ──────────────────────────────────────────────


def test_build_receipt_index_empty(tmp_path: Path) -> None:
    """Empty observability file returns empty index."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text("")
    records, errors = build_receipt_index(obs)
    assert records == []
    assert errors == []


def test_build_receipt_index_no_receipt_events(tmp_path: Path) -> None:
    """Only unrelated events returns empty index."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_unrelated_event(), _make_unrelated_event(session_id="other")],
    )
    records, errors = build_receipt_index(path)
    assert records == []
    assert errors == []


def test_build_receipt_index_single_bash(tmp_path: Path) -> None:
    """Single bash receipt event is indexed."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_bash_receipt_event(session_id="bash_test")],
    )
    records, errors = build_receipt_index(path)
    assert len(records) == 1
    assert len(errors) == 0
    rec = records[0]
    assert rec.session_id == "bash_test"
    assert rec.tool_name == "bash"
    assert rec.status == "success"
    assert rec.stdout_bytes == 3
    assert rec.stderr_bytes == 0
    assert rec.stdout_sha256 is not None
    assert rec.stderr_sha256 is not None
    assert rec.changed is None
    assert rec.path is None


def test_build_receipt_index_single_search_replace(tmp_path: Path) -> None:
    """Single search_replace receipt event is indexed with hashes."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_search_replace_receipt_event(session_id="sr_test")],
    )
    records, errors = build_receipt_index(path)
    assert len(records) == 1
    assert len(errors) == 0
    rec = records[0]
    assert rec.session_id == "sr_test"
    assert rec.tool_name == "search_replace"
    assert rec.status == "success"
    assert rec.changed is True
    assert rec.path is not None
    assert rec.path.endswith("test.py")
    assert rec.before_sha256 is not None
    assert rec.after_sha256 is not None


def test_build_receipt_index_mixed_events(tmp_path: Path) -> None:
    """Bash, search_replace, and unrelated events are handled correctly."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="mixed"),
            _make_search_replace_receipt_event(session_id="mixed"),
            _make_unrelated_event(session_id="mixed"),
            _make_bash_receipt_event(session_id="mixed", command="ls", stdout_bytes=5),
        ],
    )
    records, errors = build_receipt_index(path)
    assert len(records) == 3
    assert len(errors) == 0
    tools = {r.tool_name for r in records}
    assert tools == {"bash", "search_replace"}


# ── Validate receipt indexing ───────────────────────────────────────


def test_build_receipt_index_validate(tmp_path: Path) -> None:
    """Validate receipt events are indexed correctly."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text(
        json.dumps(_make_validate_receipt_event(session_id="validate_test")) + "\n"
    )
    records, errors = build_receipt_index(obs)
    assert errors == []
    assert len(records) == 1
    r = records[0]
    assert r.tool_name == "validate"
    assert r.status == "passed"
    assert r.duration_ms == 20.0
    assert r.error_kind is None
    assert r.refusal_reason is None
    # Validate receipts have no top-level stdout/stderr fields
    assert r.stdout_sha256 is None
    assert r.stderr_sha256 is None
    assert r.stdout_bytes is None
    assert r.stderr_bytes is None
    # Validate does not mutate files
    assert r.changed is None
    assert r.path is None
    assert r.before_sha256 is None
    assert r.after_sha256 is None


def test_build_receipt_index_validate_refused(tmp_path: Path) -> None:
    """Refused validate receipts preserve error_kind and refusal_reason."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text(
        json.dumps(
            _make_validate_receipt_event(
                session_id="refused_test",
                status="refused",
                error_kind="tool_refusal",
                refusal_reason="Unknown profile 'nonexistent'",
                check_receipts=[],
            )
        )
        + "\n"
    )
    records, errors = build_receipt_index(obs)
    assert errors == []
    assert len(records) == 1
    r = records[0]
    assert r.status == "refused"
    assert r.error_kind == "tool_refusal"
    assert r.refusal_reason == "Unknown profile 'nonexistent'"


def test_build_receipt_index_validate_timed_out(tmp_path: Path) -> None:
    """Timed-out validate receipts are indexed with correct status."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text(
        json.dumps(
            _make_validate_receipt_event(
                session_id="timeout_test",
                status="timed_out",
                error_kind="timeout",
                check_receipts=[
                    {
                        "check_id": "some_check",
                        "command_kind": "pytest",
                        "status": "timed_out",
                        "failure_kind": "timeout",
                    }
                ],
            )
        )
        + "\n"
    )
    records, errors = build_receipt_index(obs)
    assert errors == []
    assert len(records) == 1
    r = records[0]
    assert r.status == "timed_out"
    assert r.error_kind == "timeout"


def test_build_receipt_index_validate_mixed(tmp_path: Path) -> None:
    """Validate receipts coexist with bash and search_replace receipts."""
    obs = tmp_path / "observability.jsonl"
    lines = [
        json.dumps(_make_bash_receipt_event(session_id="mixed")),
        json.dumps(_make_validate_receipt_event(session_id="mixed")),
        json.dumps(_make_search_replace_receipt_event(session_id="mixed")),
    ]
    obs.write_text("\n".join(lines) + "\n")
    records, errors = build_receipt_index(obs)
    assert errors == []
    assert len(records) == 3
    tools = {r.tool_name for r in records}
    assert tools == {"bash", "search_replace", "validate"}


def test_summarize_validate_receipt(tmp_path: Path) -> None:
    """Summarize includes validate tool and counts correctly."""
    obs = tmp_path / "observability.jsonl"
    lines = [
        json.dumps(_make_validate_receipt_event(session_id="summary_test")),
        json.dumps(
            _make_validate_receipt_event(
                session_id="summary_test",
                status="refused",
                error_kind="tool_refusal",
                check_receipts=[],
            )
        ),
    ]
    obs.write_text("\n".join(lines) + "\n")
    records, errors = build_receipt_index(obs)
    assert errors == []
    summary = summarize_receipt_index(records)
    assert summary.total_events == 2
    assert "validate" in summary.by_tool
    assert summary.by_tool["validate"] == 2
    assert "passed" in summary.by_status
    assert "refused" in summary.by_status
    assert summary.refusal_count == 1
    # Validate receipts don't count as mutations
    assert summary.mutation_count == 0


# ── Index builder: error handling ─────────────────────────────────────


def test_build_receipt_index_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON lines produce errors but don't crash."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text("{invalid json\n")
    records, errors = build_receipt_index(obs)
    assert records == []
    assert len(errors) == 1
    assert "JSON decode error" in errors[0]


def test_build_receipt_index_malformed_event_missing_session(tmp_path: Path) -> None:
    """Receipt event missing session_id produces error."""
    event = _make_bash_receipt_event(session_id="test")
    del event["session_id"]
    path = _write_observability(tmp_path / "observability.jsonl", [event])
    records, errors = build_receipt_index(path)
    assert len(records) == 0
    assert len(errors) >= 1
    assert any("Missing session_id" in e for e in errors)


def test_build_receipt_index_malformed_event_missing_receipt(tmp_path: Path) -> None:
    """Receipt event missing receipt in payload produces error."""
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": "evt-bad",
        "session_id": "test",
        "sequence": 1,
        "created_at": "2026-05-13T00:00:00",
        "event_name": EventName.TOOL_RECEIPT_CAPTURED,
        "payload": {"tool_name": "bash"},  # no receipt
    }
    path = _write_observability(tmp_path / "observability.jsonl", [event])
    records, errors = build_receipt_index(path)
    assert len(records) == 0
    assert any("Missing or non-dict receipt" in e for e in errors)


def test_build_receipt_index_malformed_unrelated_safe(tmp_path: Path) -> None:
    """Malformed unrelated events do not crash the builder."""
    obs = tmp_path / "observability.jsonl"
    obs.write_text(
        '{"event_name": "rig.relay.session.started", "payload": {}}\n'
        "not json at all\n"
        '{"event_name": "rig.relay.tool_receipt.captured",'
        ' "session_id": "s1", "payload": {"tool_name": "bash",'
        ' "receipt": {"status": "ok"}}}\n'
    )
    records, errors = build_receipt_index(obs)
    assert len(records) == 1
    assert len(errors) == 1
    assert "JSON decode error" in errors[0]
    assert records[0].tool_name == "bash"


def test_build_receipt_index_file_not_found(tmp_path: Path) -> None:
    """Non-existent path returns error, not crash."""
    records, errors = build_receipt_index(tmp_path / "nonexistent.jsonl")
    assert records == []
    assert len(errors) == 1
    assert "not found" in errors[0]


# ── Index builder: path resolution ────────────────────────────────────


def test_build_receipt_index_with_session_directory(tmp_path: Path) -> None:
    """A session directory with observability.jsonl is resolved."""
    session_dir = tmp_path / "mysession"
    obs = session_dir / "observability.jsonl"
    _write_observability(obs, [_make_bash_receipt_event(session_id="dir_test")])
    records, errors = build_receipt_index(session_dir)
    assert len(records) == 1
    assert records[0].session_id == "dir_test"


# ── Summary tests ─────────────────────────────────────────────────────


def test_summarize_empty() -> None:
    """Empty records produce empty summary."""
    summary = summarize_receipt_index([])
    assert summary.total_events == 0
    assert summary.by_tool == {}
    assert summary.by_status == {}
    assert summary.mutation_count == 0


def test_summarize_by_tool(tmp_path: Path) -> None:
    """Summary counts by tool correctly."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="s1"),
            _make_bash_receipt_event(session_id="s1", command="ls"),
            _make_search_replace_receipt_event(session_id="s1"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.total_events == 3
    assert summary.by_tool["bash"] == 2
    assert summary.by_tool["search_replace"] == 1


def test_summarize_by_status(tmp_path: Path) -> None:
    """Summary counts by status correctly."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="s1", status="success"),
            _make_bash_receipt_event(
                session_id="s1", status="refused", refusal_reason="blocked"
            ),
            _make_search_replace_receipt_event(session_id="s1", status="no_match"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.by_status["success"] == 1
    assert summary.by_status["refused"] == 1
    assert summary.by_status["no_match"] == 1


def test_summarize_mutations(tmp_path: Path) -> None:
    """Summary tracks mutated paths with before/after hashes."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_search_replace_receipt_event(
                session_id="s1",
                file="src/main.py",
                changed_files=["src/main.py"],
                before_hash="aaa",
                after_hash="bbb",
            ),
            _make_search_replace_receipt_event(
                session_id="s1",
                file="src/utils.py",
                changed_files=["src/utils.py"],
                before_hash="ccc",
                after_hash="ddd",
            ),
            _make_bash_receipt_event(session_id="s1"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.mutation_count == 2
    # Paths should be resolved absolute, so check keys contain the filenames
    path_keys = list(summary.mutated_paths.keys())
    assert any("src/main.py" in k for k in path_keys)
    assert any("src/utils.py" in k for k in path_keys)


def test_summarize_refusals(tmp_path: Path) -> None:
    """Summary counts refusals."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(
                session_id="s1", status="refused", refusal_reason="blocked"
            ),
            _make_search_replace_receipt_event(
                session_id="s1", status="refused", refusal_reason="no write"
            ),
            _make_bash_receipt_event(session_id="s1", status="success"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.refusal_count == 2


def test_summarize_timeouts(tmp_path: Path) -> None:
    """Summary counts timeouts."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(
                session_id="s1", status="timed_out", error_kind="timeout"
            ),
            _make_bash_receipt_event(session_id="s1", status="success"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.timeout_count == 1


def test_summarize_to_dict(tmp_path: Path) -> None:
    """Summary to_dict() produces a serializable dict."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="s1"),
            _make_search_replace_receipt_event(session_id="s1"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    d = summary.to_dict()
    assert d["total_events"] == 2
    assert isinstance(d["by_tool"], dict)
    assert isinstance(d["by_status"], dict)
    assert isinstance(d["mutated_paths"], dict)
    # Verify JSON serializable
    json.dumps(d)


# ── Content-light validation ──────────────────────────────────────────


def test_validate_content_light_empty() -> None:
    """Empty records pass content-light validation."""
    warnings = validate_index_content_light([])
    assert warnings == []


def test_validate_content_light_clean_bash(tmp_path: Path) -> None:
    """Bash receipt index records pass content-light validation."""
    path = _write_observability(
        tmp_path / "observability.jsonl", [_make_bash_receipt_event(session_id="s1")]
    )
    records, _ = build_receipt_index(path)
    warnings = validate_index_content_light(records)
    assert warnings == []


def test_validate_content_light_clean_search_replace(tmp_path: Path) -> None:
    """Search_replace receipt index records pass content-light validation."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_search_replace_receipt_event(session_id="s1")],
    )
    records, _ = build_receipt_index(path)
    warnings = validate_index_content_light(records)
    assert warnings == []


def test_forbidden_field_names_defined() -> None:
    """FORBIDDEN_RAW_FIELD_NAMES contains expected entries."""
    assert "stdout" in FORBIDDEN_RAW_FIELD_NAMES
    assert "stderr" in FORBIDDEN_RAW_FIELD_NAMES
    assert "content" in FORBIDDEN_RAW_FIELD_NAMES
    assert "diff" in FORBIDDEN_RAW_FIELD_NAMES
    assert "old" in FORBIDDEN_RAW_FIELD_NAMES
    assert "new" in FORBIDDEN_RAW_FIELD_NAMES
    assert "replacement_text" in FORBIDDEN_RAW_FIELD_NAMES
    assert "file_contents" in FORBIDDEN_RAW_FIELD_NAMES
    # Note: "output" is currently in the forbidden list but "old_text" and "new_text"
    # are also forbidden keys NOT in the model (good — they can't appear)


# ── Script tests ──────────────────────────────────────────────────────


def test_script_emits_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Script emits valid JSON by default."""
    from scripts.rig_relay_receipt_index import main

    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_bash_receipt_event(session_id="script_test")],
    )
    exit_code = main([str(path)])
    assert exit_code == 0


def test_script_summary_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Script --summary produces human-readable output."""
    from scripts.rig_relay_receipt_index import main

    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="summary_test"),
            _make_search_replace_receipt_event(session_id="summary_test"),
        ],
    )
    exit_code = main([str(path), "--summary"])
    assert exit_code == 0


def test_script_validate_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Script --validate returns 0 for clean index."""
    from scripts.rig_relay_receipt_index import main

    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_bash_receipt_event(session_id="validate_test")],
    )
    exit_code = main([str(path), "--validate"])
    assert exit_code == 0


def test_script_errors_without_session(tmp_path: Path) -> None:
    """Script exits 1 when no session or path provided."""
    from scripts.rig_relay_receipt_index import main

    exit_code = main([])
    assert exit_code == 1


# ── ReceiptIndexBuildError ────────────────────────────────────────────


def test_receipt_index_build_error() -> None:
    """ReceiptIndexBuildError carries message and optional line."""
    err = ReceiptIndexBuildError("test error", line=5)
    assert err.message == "test error"
    assert err.line == 5
    assert "test error" in str(err)


def test_receipt_index_build_error_no_line() -> None:
    """ReceiptIndexBuildError works without line number."""
    err = ReceiptIndexBuildError("test error")
    assert err.line is None


# ── ReceiptIndexSummary dataclass ─────────────────────────────────────


def test_receipt_index_summary_default() -> None:
    """ReceiptIndexSummary has sensible defaults."""
    s = ReceiptIndexSummary()
    assert s.total_events == 0
    assert s.by_tool == {}
    assert s.by_status == {}
    assert s.mutation_count == 0
    assert s.refusal_count == 0


# ── Validate receipt index tests ──────────────────────────────────────


def test_build_receipt_index_single_validate(tmp_path: Path) -> None:
    """A single validate receipt event is indexed correctly."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_validate_receipt_event(session_id="s1")],
    )
    records, errors = build_receipt_index(path)
    assert len(errors) == 0
    assert len(records) == 1
    assert records[0].tool_name == "validate"
    assert records[0].session_id == "s1"
    assert records[0].status == "passed"
    assert records[0].duration_ms == 20.0
    assert records[0].refusal_reason is None
    assert records[0].path is None  # no file path for validate


def test_build_receipt_index_validate_content_light(tmp_path: Path) -> None:
    """Validate receipt index record remains content-light."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [_make_validate_receipt_event(session_id="s1")],
    )
    records, _ = build_receipt_index(path)
    dumped = records[0].model_dump(mode="json")
    # Check no forbidden raw field names in dict keys
    forbidden = {"stdout", "stderr", "output", "content", "diff"}
    allowed_suffixes = ("_sha256", "_bytes", "_truncated")
    raw_violations = {
        k
        for k in dumped
        if k in forbidden
        or (
            any(raw in k for raw in ("stdout", "stderr", "output", "content"))
            and not k.endswith(allowed_suffixes)
        )
    }
    assert not raw_violations, f"Raw content fields present: {raw_violations}"


def test_summarize_validate_counts(tmp_path: Path) -> None:
    """Summary correctly counts validate events by tool and status."""
    path = _write_observability(
        tmp_path / "observability.jsonl",
        [
            _make_bash_receipt_event(session_id="s1"),
            _make_validate_receipt_event(session_id="s1", status="passed"),
            _make_validate_receipt_event(session_id="s1", status="failed"),
        ],
    )
    records, _ = build_receipt_index(path)
    summary = summarize_receipt_index(records)
    assert summary.total_events == 3
    assert summary.by_tool.get("bash") == 1
    assert summary.by_tool.get("validate") == 2
    # bash receipt has status "success", validate has "passed" and "failed"
    assert summary.by_status.get("success") == 1
    assert summary.by_status.get("passed") == 1
    assert summary.by_status.get("failed") == 1
