"""Tests for tool receipt content-light policy validator."""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.evidence.tool_receipt_policy import (
    validate_event,
    validate_file,
    validate_receipt_payload,
)


def _receipt_event(receipt: dict) -> dict:
    return {
        "event_name": "rig.relay.tool_receipt.captured",
        "session_id": "test",
        "payload": {"tool_name": "bash", "receipt": receipt},
    }


def _unrelated_event() -> dict:
    return {
        "event_name": "rig.relay.model_observation.captured",
        "session_id": "test",
        "payload": {},
    }


# ── Valid BashReceipt passes ──


def test_valid_bash_receipt_passes() -> None:
    """A legitimate BashReceipt payload produces zero findings."""
    event = _receipt_event({
        "command": "echo hi",
        "status": "success",
        "exit_code": 0,
        "duration_ms": 10.0,
        "stdout_bytes": 3,
        "stderr_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_sha256": "abc123",
        "stderr_sha256": None,
    })
    findings = validate_event(event)
    assert len(findings) == 0, f"Expected no findings, got: {findings}"


def test_allowed_metadata_fields_not_rejected() -> None:
    """stdout_sha256, stderr_sha256, stdout_bytes etc. are allowed."""
    receipt = {
        "command": "ls",
        "stdout_sha256": "deadbeef",
        "stderr_sha256": "cafebabe",
        "stdout_bytes": 100,
        "stderr_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "before_sha256": "111",
        "after_sha256": "222",
    }
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) == 0, f"Metadata fields flagged: {findings}"


# ── Forbidden fields are rejected ──


def test_raw_stdout_rejected() -> None:
    """stdout field is forbidden."""
    event = _receipt_event({"stdout": "hello world"})
    findings = validate_event(event)
    assert len(findings) == 1
    assert "stdout" in findings[0].field_path
    assert findings[0].severity == "error"


def test_raw_stderr_rejected() -> None:
    """stderr field is forbidden."""
    findings = validate_receipt_payload({"receipt": {"stderr": "error!"}})
    assert len(findings) == 1
    assert "stderr" in findings[0].field_path


def test_old_new_diff_snippet_rejected() -> None:
    """old, new, diff, and snippet fields are all forbidden."""
    receipt = {
        "old": "original",
        "new": "replacement",
        "diff": "diff",
        "snippet": "snippet",
    }
    findings = validate_receipt_payload({"receipt": receipt})
    paths = {f.field_path for f in findings}
    assert "receipt.old" in paths
    assert "receipt.new" in paths
    assert "receipt.diff" in paths
    assert "receipt.snippet" in paths


def test_replacement_text_rejected() -> None:
    """replacement and replacement_text are forbidden."""
    receipt = {"replacement": "x", "replacement_text": "y"}
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) == 2


def test_command_output_rejected() -> None:
    """command_output is forbidden."""
    findings = validate_receipt_payload({"receipt": {"command_output": "data"}})
    assert len(findings) == 1


def test_patch_and_context_rejected() -> None:
    """patch and context are forbidden."""
    receipt = {"patch": "--- a/file", "context": "some lines"}
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) == 2


# ── Nested forbidden fields ──


def test_nested_forbidden_fields_rejected() -> None:
    """Forbidden fields inside nested dicts are caught."""
    receipt = {"meta": {"stdout": "leaked", "stderr": "leaked_too"}}
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) == 2
    paths = {f.field_path for f in findings}
    assert "receipt.meta.stdout" in paths
    assert "receipt.meta.stderr" in paths


# ── Unrelated events ──


def test_unrelated_events_ignored() -> None:
    """Non-receipt events produce no findings."""
    event = _unrelated_event()
    findings = validate_event(event)
    assert len(findings) == 0


def test_malformed_unrelated_events_tolerated() -> None:
    """Malformed unrelated events do not cause failures."""
    event = _unrelated_event()
    event["payload"] = None  # malformed but unrelated
    findings = validate_event(event)
    assert len(findings) == 0


# ── Malformed receipt events ──


def test_malformed_tool_receipt_produces_finding() -> None:
    """Malformed tool receipt events (missing payload) produce findings."""
    event = {"event_name": "rig.relay.tool_receipt.captured", "payload": None}
    findings = validate_event(event)
    assert len(findings) >= 1


def test_missing_receipt_dict_produces_finding() -> None:
    """Missing receipt dict produces a finding."""
    event = {
        "event_name": "rig.relay.tool_receipt.captured",
        "payload": {"tool_name": "bash", "receipt": None},
    }
    findings = validate_event(event)
    assert len(findings) == 1
    assert "Missing" in findings[0].message


# ── Value-shape heuristics ──


def test_large_multiline_string_flagged(tmp_path: Path) -> None:
    """Strings > 256 bytes with many newlines produce warnings."""
    large = "\n".join(f"line_{i}" for i in range(20)) + "x" * 300
    receipt = {"command": large}
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) >= 1
    assert any(f.severity == "warn" for f in findings)


def test_diff_marker_detected() -> None:
    """String with unified diff markers is flagged."""
    receipt = {"command": "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new"}
    findings = validate_receipt_payload({"receipt": receipt})
    assert len(findings) >= 1
    assert any("diff marker" in f.message for f in findings)


# ── File-level validation ──


def test_validate_file_clean(tmp_path: Path) -> None:
    """File with only valid receipt events passes."""
    lines = [
        json.dumps(
            _receipt_event({"command": "ls", "status": "success", "exit_code": 0})
        )
    ]
    log = tmp_path / "obs.jsonl"
    log.write_text("\n".join(lines) + "\n")
    findings = validate_file(log)
    assert len(findings) == 0


def test_validate_file_with_violation(tmp_path: Path) -> None:
    """File with violating receipt events produces findings."""
    lines = [
        json.dumps(_receipt_event({"stdout": "raw data"})),
        json.dumps(_unrelated_event()),
    ]
    log = tmp_path / "obs.jsonl"
    log.write_text("\n".join(lines) + "\n")
    findings = validate_file(log)
    assert len(findings) == 1


def test_validate_file_ignores_malformed_unrelated(tmp_path: Path) -> None:
    """Malformed unrelated lines do not break file validation."""
    lines = [
        json.dumps(_receipt_event({"command": "ok", "status": "pass", "exit_code": 0})),
        "not valid json",
        json.dumps(_unrelated_event()).replace("{", "["),  # malformed
    ]
    log = tmp_path / "obs.jsonl"
    log.write_text("\n".join(lines) + "\n")
    findings = validate_file(log)
    # No violation findings from receipt content
    receipt_findings = [f for f in findings if "receipt" in f.field_path]
    assert len(receipt_findings) == 0
    # Both line 2 (not valid json) and line 3 (broken JSON) are malformed
    malformed = [f for f in findings if "Malformed JSON" in f.message]
    assert len(malformed) == 2


def test_validate_file_multiple_violations(tmp_path: Path) -> None:
    """File with multiple violating events produces multiple findings."""
    lines = [
        json.dumps(_receipt_event({"diff": "--- a"})),
        json.dumps(_receipt_event({"stdout": "raw"})),
        json.dumps(_receipt_event({"snippet": "code"})),
    ]
    log = tmp_path / "obs.jsonl"
    log.write_text("\n".join(lines) + "\n")
    findings = validate_file(log)
    assert len(findings) == 3


# ── Edge cases ──


def test_empty_receipt_passes() -> None:
    """Empty receipt dict produces no findings."""
    findings = validate_receipt_payload({"receipt": {}})
    assert len(findings) == 0


def test_non_dict_receipt_value_produces_finding() -> None:
    """Non-dict receipt value produces a finding."""
    findings = validate_receipt_payload({"receipt": "not_a_dict"})
    assert len(findings) == 1


# ── Validate receipt policy tests ─────────────────────────────────────


def test_validate_receipt_passes_policy() -> None:
    """A well-formed ValidateReceipt passes the content-light policy."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import (
        Validate,
        ValidateCheckResult,
        ValidateResult,
        ValidateToolConfig,
    )

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    result = ValidateResult(
        profile="quick",
        status="passed",
        command_count=1,
        passed_count=1,
        checks=[
            ValidateCheckResult(
                check_id="test",
                command_kind="pytest",
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=100,
                stderr_bytes=0,
            )
        ],
    )
    receipt = tool.build_receipt(result)
    payload = {"tool_name": "validate", "receipt": receipt.model_dump(mode="json")}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Expected clean, got: {findings}"


def test_validate_receipt_rejects_stdout_injection() -> None:
    """Validate receipt with raw stdout field is caught by policy."""
    receipt = {
        "schema_version": "rig.relay.validate_receipt.v1",
        "profile": "test",
        "status": "passed",
        "command_count": 1,
        "stdout": "raw output leaked",
    }
    payload = {"tool_name": "validate", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("stdout" in f.field_path for f in findings)
    assert all(f.severity == "error" for f in findings)


def test_validate_receipt_rejects_stderr_injection() -> None:
    """Validate receipt with raw stderr field is caught by policy."""
    receipt = {
        "schema_version": "rig.relay.validate_receipt.v1",
        "profile": "test",
        "status": "passed",
        "stderr": "raw stderr leaked",
    }
    payload = {"tool_name": "validate", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("stderr" in f.field_path for f in findings)


def test_validate_receipt_allows_metadata_fields() -> None:
    """Allowed metadata fields like stdout_sha256 pass through."""
    receipt = {
        "schema_version": "rig.relay.validate_receipt.v1",
        "profile": "test",
        "status": "passed",
        "command_count": 1,
        "check_receipts": [
            {
                "check_id": "c1",
                "command_kind": "ruff",
                "stdout_sha256": "abc",
                "stderr_sha256": "def",
                "stdout_bytes": 100,
                "stderr_bytes": 0,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        ],
    }
    payload = {"tool_name": "validate", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Expected clean, got: {findings}"


# ── SearchReplaceReceipt policy tests ────────────────────────────────


def test_search_replace_receipt_passes_policy() -> None:
    """A well-formed SearchReplaceReceipt passes the content-light policy."""
    receipt = {
        "schema_version": "rig.relay.search_replace_receipt.v1",
        "file": "src/main.py",
        "status": "success",
        "blocks_applied": 2,
        "lines_changed": 5,
        "replacements": 2,
        "before_file_sha256": {"src/main.py": "abc"},
        "after_file_sha256": {"src/main.py": "def"},
        "changed_files": ["src/main.py"],
        "failed_block_count": 0,
        "total_block_count": 2,
        "before_bytes": 100,
        "after_bytes": 105,
    }
    payload = {"tool_name": "search_replace", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Expected clean, got: {findings}"


def test_search_replace_receipt_rejects_content_injection() -> None:
    """SearchReplaceReceipt with raw 'content' field is caught by policy."""
    receipt = {
        "schema_version": "rig.relay.search_replace_receipt.v1",
        "file": "src/main.py",
        "status": "success",
        "content": "raw file content leaked",
    }
    payload = {"tool_name": "search_replace", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("content" in f.field_path for f in findings)


def test_search_replace_receipt_rejects_old_new_diff() -> None:
    """SearchReplaceReceipt with old/new/diff fields is caught."""
    receipt = {
        "schema_version": "rig.relay.search_replace_receipt.v1",
        "file": "src/main.py",
        "status": "failed",
        "old": "original text",
        "new": "replacement text",
        "diff": "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-old\n+new",
    }
    payload = {"tool_name": "search_replace", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    paths = {f.field_path for f in findings}
    assert "receipt.old" in paths
    assert "receipt.new" in paths
    assert "receipt.diff" in paths


def test_search_replace_receipt_rejects_snippet() -> None:
    """SearchReplaceReceipt with 'snippet' field is caught."""
    receipt = {
        "schema_version": "rig.relay.search_replace_receipt.v1",
        "file": "src/main.py",
        "status": "failed",
        "snippet": "some code snippet leaked",
    }
    payload = {"tool_name": "search_replace", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("snippet" in f.field_path for f in findings)


def test_search_replace_receipt_rejects_patch() -> None:
    """SearchReplaceReceipt with 'patch' field is caught."""
    receipt = {
        "schema_version": "rig.relay.search_replace_receipt.v1",
        "file": "src/main.py",
        "status": "failed",
        "patch": "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new",
    }
    payload = {"tool_name": "search_replace", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("patch" in f.field_path for f in findings)


# ── WriteFileReceipt policy tests ────────────────────────────────────


def test_write_file_receipt_passes_policy() -> None:
    """A well-formed WriteFileReceipt passes the content-light policy."""
    receipt = {
        "schema_version": "rig.relay.write_file_receipt.v1",
        "path": "src/output.txt",
        "status": "success",
        "bytes_written": 42,
        "before_sha256": "abc",
        "after_sha256": "def",
        "before_bytes": 0,
        "after_bytes": 42,
        "file_existed": False,
        "created_file": True,
        "overwrote_existing_file": False,
        "parent_dirs_created": True,
    }
    payload = {"tool_name": "write_file", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Expected clean, got: {findings}"


def test_write_file_receipt_rejects_content_injection() -> None:
    """WriteFileReceipt with raw 'content' field is caught by policy."""
    receipt = {
        "schema_version": "rig.relay.write_file_receipt.v1",
        "path": "src/output.txt",
        "status": "success",
        "content": "raw file content leaked",
    }
    payload = {"tool_name": "write_file", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("content" in f.field_path for f in findings)


def test_write_file_receipt_rejects_file_contents() -> None:
    """WriteFileReceipt with 'file_contents' field is caught."""
    receipt = {
        "schema_version": "rig.relay.write_file_receipt.v1",
        "path": "src/output.txt",
        "status": "success",
        "file_contents": "raw content",
    }
    payload = {"tool_name": "write_file", "receipt": receipt}
    findings = validate_receipt_payload(payload)
    assert len(findings) >= 1
    assert any("file_contents" in f.field_path for f in findings)
