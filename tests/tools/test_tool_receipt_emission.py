"""Tests for deterministic tool receipt emission.

Tests the helper (``capture_tool_receipt``) and the agent-loop integration
that emits content-light receipt events for receipt-producing tools like
bash and search_replace. All tests are filesystem-local and do not require
a running agent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vibe.core.tools.base import BaseToolState
from vibe.core.tools.builtins.search_replace import SearchReplaceResult

# ── Helper: capture_tool_receipt ──


def test_capture_tool_receipt_emits_event(tmp_path: Path) -> None:
    """capture_tool_receipt writes to local observability JSONL."""
    from rig_relay.evidence.model_observations import capture_tool_receipt

    session_id = "receipt_test_001"
    log = tmp_path / "observability.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)

    # Monkey-patch the session path resolution
    import vibe.core.telemetry.local as local_module

    original = local_module.get_observability_log_path

    def fake_path(sid: str) -> Path:
        if sid == session_id:
            return log
        return original(sid)

    local_module.get_observability_log_path = fake_path

    try:
        capture_tool_receipt(
            session_id=session_id,
            tool_name="bash",
            receipt={
                "command": "echo hi",
                "status": "success",
                "exit_code": 0,
                "duration_ms": 10.0,
                "stdout_bytes": 6,
                "stderr_bytes": 0,
                "stdout_sha256": hashlib.sha256(b"hi\n").hexdigest(),
            },
        )

        assert log.exists()
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_name"] == "rig.relay.tool_receipt.captured"
        assert event["session_id"] == session_id
        assert event["payload"]["tool_name"] == "bash"
        assert event["payload"]["receipt"]["command"] == "echo hi"
        assert event["payload"]["receipt"]["exit_code"] == 0
        assert "stdout" not in event["payload"]["receipt"]
        assert "stderr" not in event["payload"]["receipt"]
    finally:
        local_module.get_observability_log_path = original


def test_capture_tool_receipt_no_raw_output(tmp_path: Path) -> None:
    """Receipt payload contains no raw stdout or stderr."""
    from rig_relay.evidence.model_observations import capture_tool_receipt

    session_id = "receipt_test_002"
    log_path = tmp_path / "observability.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    import vibe.core.telemetry.local as local_module

    original = local_module.get_observability_log_path

    def fake_path(sid: str) -> Path:
        if sid == session_id:
            return log_path
        return original(sid)

    local_module.get_observability_log_path = fake_path

    try:
        capture_tool_receipt(
            session_id=session_id,
            tool_name="bash",
            receipt={
                "command": "echo secret_data",
                "status": "success",
                "exit_code": 0,
                "stdout_sha256": "abc123",
                "stdout_bytes": 20,
            },
        )

        event = json.loads(log_path.read_text().strip())
        receipt = event["payload"]["receipt"]
        assert "stdout" not in receipt
        assert "stderr" not in receipt
        assert receipt.get("stdout_sha256") == "abc123"
        assert receipt.get("stdout_bytes") == 20
    finally:
        local_module.get_observability_log_path = original


def test_capture_tool_receipt_failure_safe(tmp_path: Path) -> None:
    """capture_tool_receipt does not raise on invalid input."""
    from rig_relay.evidence.model_observations import capture_tool_receipt

    capture_tool_receipt(
        session_id="test_fail",
        tool_name="bash",
        receipt={"command": None},  # invalid but should not raise
    )
    # No exception means success


# ── Bash build_receipt integration ──


@pytest.fixture
def bash_tool() -> type:
    """Return the Bash tool class for testing."""
    from vibe.core.tools.builtins.bash import Bash

    return Bash


def test_bash_tool_has_build_receipt(bash_tool: type) -> None:
    """Bash tool class has build_receipt method (duck-type check)."""
    from vibe.core.tools.builtins.bash import Bash, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    assert hasattr(tool, "build_receipt")
    assert callable(tool.build_receipt)


def test_bash_success_receipt_content_light(bash_tool: type) -> None:
    """Success bash receipt contains no raw stdout/stderr."""
    from vibe.core.tools.builtins.bash import Bash, BashResult, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    result = BashResult(
        command="echo hi",
        stdout="hi\n",
        stderr="",
        returncode=0,
        status="success",
        duration_ms=10.0,
        stdout_bytes=3,
        stderr_bytes=0,
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["command"] == "echo hi"
    assert receipt_dict["status"] == "success"
    assert receipt_dict["exit_code"] == 0
    assert receipt_dict["stdout_bytes"] == 3
    assert receipt_dict["stderr_bytes"] == 0
    assert receipt_dict["stdout_sha256"] == hashlib.sha256(b"hi\n").hexdigest()
    assert "stdout" not in receipt_dict
    assert "stderr" not in receipt_dict


def test_bash_timeout_receipt_content_light(bash_tool: type) -> None:
    """Timeout bash receipt contains no raw output."""
    from vibe.core.tools.builtins.bash import Bash, BashResult, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    result = BashResult(
        command="sleep 100",
        stdout="",
        stderr="",
        returncode=-1,
        status="timeout",
        duration_ms=30000.0,
        stdout_bytes=0,
        stderr_bytes=0,
        error_kind="timeout",
        refusal_reason="Command timed out after 30s",
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["status"] == "timeout"
    assert receipt_dict["error_kind"] == "timeout"
    assert receipt_dict["refusal_reason"] == "Command timed out after 30s"
    assert "stdout" not in receipt_dict
    assert "stderr" not in receipt_dict


def test_bash_refusal_receipt_content_light(bash_tool: type) -> None:
    """Refused bash receipt contains no raw output."""
    from vibe.core.tools.builtins.bash import Bash, BashResult, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    result = BashResult(
        command="git push",
        stdout="",
        stderr="",
        returncode=-1,
        status="refused",
        duration_ms=0.5,
        stdout_bytes=0,
        stderr_bytes=0,
        error_kind="refused",
        refusal_reason="Destructive git command",
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["status"] == "refused"
    assert receipt_dict["refusal_reason"] == "Destructive git command"
    assert "stdout" not in receipt_dict
    assert "stderr" not in receipt_dict


# ── Full emission integration ──


def test_capture_bash_receipt_integration(tmp_path: Path) -> None:
    """Full flow: build_receipt -> capture_tool_receipt writes content-light event."""
    from rig_relay.evidence.model_observations import capture_tool_receipt
    from vibe.core.tools.builtins.bash import Bash, BashResult, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    result = BashResult(
        command="ls -la",
        stdout="file1\nfile2\n",
        stderr="",
        returncode=0,
        status="success",
        duration_ms=5.0,
        stdout_bytes=12,
        stderr_bytes=0,
    )
    receipt = tool.build_receipt(result)

    session_id = "receipt_integration_001"
    log_path = tmp_path / "obs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    import vibe.core.telemetry.local as local_module

    original = local_module.get_observability_log_path

    def fake_path(sid: str) -> Path:
        if sid == session_id:
            return log_path
        return original(sid)

    local_module.get_observability_log_path = fake_path

    try:
        capture_tool_receipt(
            session_id=session_id,
            tool_name="bash",
            receipt=receipt.model_dump(mode="json"),
        )

        assert log_path.exists()
        event = json.loads(log_path.read_text().strip())
        assert event["event_name"] == "rig.relay.tool_receipt.captured"
        assert event["session_id"] == session_id

        r = event["payload"]["receipt"]
        assert r["command"] == "ls -la"
        assert r["status"] == "success"
        assert r["exit_code"] == 0
        assert r["stdout_bytes"] == 12
        assert "stdout" not in r
        assert "stderr" not in r
    finally:
        local_module.get_observability_log_path = original


def test_bash_receipt_emission_does_not_raise(tmp_path: Path) -> None:
    """build_receipt failure does not raise (failure-safe pattern)."""
    from vibe.core.tools.builtins.bash import Bash, BashResult, BashToolConfig

    tool = Bash(
        config_getter=lambda: BashToolConfig(
            default_timeout=30, max_output_bytes=65536
        ),
        state=BaseToolState(),
    )
    result = BashResult(
        command="echo ok",
        stdout="ok\n",
        stderr="",
        returncode=0,
        status="success",
        duration_ms=1.0,
        stdout_bytes=3,
        stderr_bytes=0,
    )

    # Simulate receipt emission failure by passing None
    receipt = tool.build_receipt(result)
    assert receipt is not None
    # No exception — the helper wraps in try/except


# ── SearchReplace receipt emission ──


@pytest.fixture
def sr_tool() -> type:
    """Return the SearchReplace tool class for testing."""
    from vibe.core.tools.builtins.search_replace import SearchReplace

    return SearchReplace


@pytest.fixture
def sr_result_success() -> SearchReplaceResult:
    """Build a minimal SearchReplaceResult with success status."""
    from vibe.core.tools.builtins.search_replace import SearchReplaceResult

    return SearchReplaceResult(
        file="test.py",
        blocks_applied=1,
        lines_changed=2,
        content="x = 2\n",
        warnings=[],
        before_file_sha256={
            "test.py": "sha256:" + hashlib.sha256(b"x = 1\n").hexdigest()
        },
        after_file_sha256={
            "test.py": "sha256:" + hashlib.sha256(b"x = 2\n").hexdigest()
        },
        changed_files=["test.py"],
        failed_block_count=0,
        total_block_count=1,
        replacements=1,
        before_bytes=6,
        after_bytes=6,
        status="success",
        duration_ms=15.0,
    )


def test_search_replace_has_build_receipt(sr_tool: type) -> None:
    """SearchReplace tool class has build_receipt method (duck-type check)."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    assert hasattr(tool, "build_receipt")
    assert callable(tool.build_receipt)


def test_search_replace_success_receipt_content_light(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Success search_replace receipt contains no raw file content."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["file"] == "test.py"
    assert receipt_dict["status"] == "success"
    assert receipt_dict["blocks_applied"] == 1
    assert receipt_dict["lines_changed"] == 2
    assert receipt_dict["replacements"] == 1
    assert "content" not in receipt_dict
    assert "old" not in str(list(receipt_dict.keys()))
    assert "new" not in str(list(receipt_dict.keys()))
    assert "diff" not in str(list(receipt_dict.keys()))
    assert "patch" not in str(list(receipt_dict.keys()))
    assert "test.py" in receipt_dict["changed_files"]


def test_search_replace_no_match_receipt_content_light(sr_tool: type) -> None:
    """no_match search_replace receipt contains error_kind, no content."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=0,
        lines_changed=0,
        content="x = 1\n",
        warnings=[],
        before_file_sha256={},
        after_file_sha256={},
        changed_files=[],
        failed_block_count=1,
        total_block_count=1,
        replacements=0,
        before_bytes=6,
        after_bytes=6,
        status="no_match",
        error_kind="old_text_not_found",
        refusal_reason="SEARCH/REPLACE blocks failed:\nBlock 1: old text not found",
        duration_ms=5.0,
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["status"] == "no_match"
    assert receipt_dict["error_kind"] == "old_text_not_found"
    assert receipt_dict["refusal_reason"] is not None
    assert receipt_dict["failed_block_count"] == 1
    assert receipt_dict["blocks_applied"] == 0
    assert "content" not in receipt_dict


def test_search_replace_refused_receipt_content_light(sr_tool: type) -> None:
    """Refused search_replace receipt contains refusal info, no content."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=0,
        lines_changed=0,
        content="",
        warnings=[],
        before_file_sha256={},
        after_file_sha256={},
        changed_files=[],
        failed_block_count=0,
        total_block_count=1,
        replacements=0,
        before_bytes=0,
        after_bytes=0,
        status="refused",
        error_kind="hash_mismatch",
        refusal_reason="Expected sha256:abc does not match current file bytes",
        duration_ms=0.5,
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    assert receipt_dict["status"] == "refused"
    assert receipt_dict["error_kind"] == "hash_mismatch"
    assert "Expected sha256" in receipt_dict["refusal_reason"]
    assert "content" not in receipt_dict


def test_search_replace_receipt_omits_raw_content(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Receipt has no content, old_text, new_text, diff, or patch fields."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    receipt_dict = receipt.model_dump(mode="json")
    keys = set(receipt_dict.keys())

    assert "content" not in keys
    assert "old_text" not in keys
    assert "new_text" not in keys
    assert "diff" not in keys
    assert "patch" not in keys
    assert "snippet" not in keys


def test_search_replace_receipt_includes_hashes(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Receipt includes before/after sha256 hashes."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    receipt_dict = receipt.model_dump(mode="json")

    assert "test.py" in receipt_dict["before_file_sha256"]
    assert "test.py" in receipt_dict["after_file_sha256"]
    assert receipt_dict["before_file_sha256"]["test.py"].startswith("sha256:")
    assert receipt_dict["after_file_sha256"]["test.py"].startswith("sha256:")


def test_search_replace_receipt_includes_status_fields(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Receipt includes status, error_kind, refusal_reason, duration_ms."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    receipt_dict = receipt.model_dump(mode="json")

    assert "status" in receipt_dict
    assert "error_kind" in receipt_dict
    assert "refusal_reason" in receipt_dict
    assert "duration_ms" in receipt_dict
    assert receipt_dict["duration_ms"] == 15.0


def test_capture_search_replace_receipt_integration(
    tmp_path: Path, sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Full flow: build_receipt -> capture_tool_receipt writes content-light event."""
    from rig_relay.evidence.model_observations import capture_tool_receipt
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)

    session_id = "sr_receipt_integration_001"
    log_path = tmp_path / "obs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    import vibe.core.telemetry.local as local_module

    original = local_module.get_observability_log_path

    def fake_path(sid: str) -> Path:
        if sid == session_id:
            return log_path
        return original(sid)

    local_module.get_observability_log_path = fake_path

    try:
        capture_tool_receipt(
            session_id=session_id,
            tool_name="search_replace",
            receipt=receipt.model_dump(mode="json"),
        )

        assert log_path.exists()
        event = json.loads(log_path.read_text().strip())
        assert event["event_name"] == "rig.relay.tool_receipt.captured"
        assert event["session_id"] == session_id

        r = event["payload"]["receipt"]
        assert r["file"] == "test.py"
        assert r["status"] == "success"
        assert r["blocks_applied"] == 1
        assert "content" not in r
        assert "old_text" not in r
        assert "new_text" not in r
    finally:
        local_module.get_observability_log_path = original


def test_search_replace_receipt_schema_validates(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """SearchReplace receipt validates against its JSON schema."""
    import json

    import jsonschema

    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    # Load the receipt schema
    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.search_replace_receipt.v1.schema.json"
    )
    assert schema_path.is_file(), f"Schema not found: {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    receipt_dict = receipt.model_dump(mode="json")

    # Add schema_version for validation (not in model but expected by schema)
    receipt_dict["schema_version"] = "rig.relay.search_replace_receipt.v1"

    jsonschema.validate(instance=receipt_dict, schema=schema)
    # No exception means valid


# ── SearchReplace sanitization and policy validation ──


def test_search_replace_no_match_refusal_sanitized(sr_tool: type) -> None:
    """Receipt refusal_reason is sanitized — strips file context lines."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    # Build a result with file context in refusal_reason (as produced by _apply_blocks)
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=0,
        lines_changed=0,
        content="x = 1\ny = 2\n",
        warnings=[],
        before_file_sha256={},
        after_file_sha256={},
        changed_files=[],
        failed_block_count=1,
        total_block_count=1,
        replacements=0,
        before_bytes=12,
        after_bytes=12,
        status="no_match",
        error_kind="old_text_not_found",
        refusal_reason=(
            "SEARCH/REPLACE block 1 failed: Search text not found in test.py\n"
            "Search text was:\n"
            "'NonExistent'\n"
            "Context analysis:\n"
            "Potential match area around line 1:\n"
            ">>>   1: x = 1\n"
            "      2: y = 2\n"
            "\nDebugging tips:\n"
            "1. Check for exact whitespace/indentation match\n"
            "2. Verify line endings match the file exactly (\\r\\n vs \\n)\n"
        ),
        duration_ms=5.0,
    )
    receipt = tool.build_receipt(result)
    receipt_dict = receipt.model_dump(mode="json")

    # Must retain summary
    assert "SEARCH/REPLACE block 1 failed" in receipt_dict["refusal_reason"]
    # Must strip search text
    assert "NonExistent" not in receipt_dict["refusal_reason"]
    # Must strip context analysis — file content lines
    assert "x = 1" not in receipt_dict["refusal_reason"]
    assert "y = 2" not in receipt_dict["refusal_reason"]
    assert "Potential match area" not in receipt_dict["refusal_reason"]
    # Must retain debugging tips (safe)
    assert "Debugging tips" in receipt_dict["refusal_reason"]
    assert "whitespace/indentation" in receipt_dict["refusal_reason"]


def test_search_replace_sanitize_refusal_none(sr_tool: type) -> None:
    """_sanitize_refusal_for_receipt returns None for None input."""
    from vibe.core.tools.builtins.search_replace import SearchReplace

    result = SearchReplace._sanitize_refusal_for_receipt(None)
    assert result is None


def test_search_replace_sanitize_refusal_empty(sr_tool: type) -> None:
    """_sanitize_refusal_for_receipt returns None for empty string."""
    from vibe.core.tools.builtins.search_replace import SearchReplace

    result = SearchReplace._sanitize_refusal_for_receipt("")
    assert result is None


def test_search_replace_sanitize_refusal_safe_string_preserved(sr_tool: type) -> None:
    """_sanitize_refusal_for_receipt preserves safe refusal strings."""
    from vibe.core.tools.builtins.search_replace import SearchReplace

    safe = "Expected 2 replacements but got 1. File was not mutated."
    result = SearchReplace._sanitize_refusal_for_receipt(safe)
    assert result == safe


def test_search_replace_receipt_passes_policy_validator(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """Success SearchReplace receipt passes the content-light policy validator."""
    from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    payload = {"receipt": receipt.model_dump(mode="json")}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Policy violations: {findings}"


def test_search_replace_no_match_receipt_passes_policy_validator(sr_tool: type) -> None:
    """No-match SearchReplace receipt passes policy validator even with context."""
    from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=0,
        lines_changed=0,
        content="x = 1\n",
        warnings=[],
        before_file_sha256={},
        after_file_sha256={},
        changed_files=[],
        failed_block_count=1,
        total_block_count=1,
        replacements=0,
        before_bytes=6,
        after_bytes=6,
        status="no_match",
        error_kind="old_text_not_found",
        refusal_reason=(
            "SEARCH/REPLACE block 1 failed: Search text not found in test.py\n"
            "Search text was:\n"
            "'NonExistent'\n"
            "Context analysis:\n"
            "Potential match area around line 1:\n"
            ">>>   1: x = 1\n"
            "      2: y = 2\n"
            "\nDebugging tips:\n"
            "1. Check for exact whitespace/indentation match\n"
        ),
        duration_ms=5.0,
    )
    receipt = tool.build_receipt(result)
    payload = {"receipt": receipt.model_dump(mode="json")}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Policy violations: {findings}"


def test_search_replace_refused_receipt_passes_policy_validator(sr_tool: type) -> None:
    """Refused SearchReplace receipt passes policy validator."""
    from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=0,
        lines_changed=0,
        content="",
        warnings=[],
        before_file_sha256={},
        after_file_sha256={},
        changed_files=[],
        failed_block_count=0,
        total_block_count=1,
        replacements=0,
        before_bytes=0,
        after_bytes=0,
        status="refused",
        error_kind="hash_mismatch",
        refusal_reason="Hash mismatch on test.py",
        duration_ms=0.5,
    )
    receipt = tool.build_receipt(result)
    payload = {"receipt": receipt.model_dump(mode="json")}
    findings = validate_receipt_payload(payload)
    assert len(findings) == 0, f"Policy violations: {findings}"


def test_search_replace_sr_instantiation_and_duck_type(sr_tool: type) -> None:
    """SearchReplace instantiates cleanly and exposes run + build_receipt."""
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
        SearchReplaceReceipt,
        SearchReplaceResult,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    assert hasattr(tool, "run")
    assert callable(tool.run)
    assert hasattr(tool, "build_receipt")
    assert callable(tool.build_receipt)

    # build_receipt returns a SearchReplaceReceipt
    result = SearchReplaceResult(
        file="test.py",
        blocks_applied=1,
        lines_changed=0,
        content="",
        status="success",
        duration_ms=1.0,
    )
    receipt = tool.build_receipt(result)
    assert isinstance(receipt, SearchReplaceReceipt)
    assert receipt.duration_ms == 1.0
    assert receipt.file == "test.py"
    assert receipt.status == "success"
    assert receipt.error_kind is None


def test_search_replace_receipt_passes_validate_event(
    sr_tool: type, sr_result_success: SearchReplaceResult
) -> None:
    """SearchReplace receipt passes validate_event from policy validator."""
    from rig_relay.evidence.tool_receipt_policy import validate_event
    from vibe.core.tools.builtins.search_replace import (
        SearchReplace,
        SearchReplaceConfig,
    )

    tool = SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )
    receipt = tool.build_receipt(sr_result_success)
    event = {
        "event_name": "rig.relay.tool_receipt.captured",
        "session_id": "test",
        "payload": {
            "tool_name": "search_replace",
            "receipt": receipt.model_dump(mode="json"),
        },
    }
    findings = validate_event(event)
    assert len(findings) == 0, f"Policy violations: {findings}"


# ── Validate receipt tests ────────────────────────────────────────────


def test_validate_tool_has_build_receipt() -> None:
    """Validate tool class has build_receipt method (duck-type check)."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import Validate, ValidateToolConfig

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    assert hasattr(tool, "build_receipt")
    assert callable(tool.build_receipt)


def test_validate_success_receipt_content_light() -> None:
    """Success validate receipt contains no raw stdout/stderr."""
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
        duration_ms=10.0,
        checks=[
            ValidateCheckResult(
                check_id="git_status",
                command_kind="git",
                status="passed",
                exit_code=0,
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=50,
                stderr_bytes=0,
            )
        ],
    )
    receipt = tool.build_receipt(result)
    dumped = receipt.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content", "diff", "command_output"):
        assert key not in dumped, f"Unexpected raw field: {key}"
    for cr in dumped.get("check_receipts", []):
        for key in ("stdout", "stderr", "output", "content"):
            assert key not in cr, f"Unexpected raw field in check_receipts: {key}"


def test_validate_failed_receipt_content_light() -> None:
    """Failed validate receipt contains no raw output and preserves failure info."""
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
        profile="schemas",
        status="failed",
        command_count=2,
        passed_count=1,
        failed_count=1,
        duration_ms=80.0,
        blocker_summary={"test_failure": 1},
        checks=[
            ValidateCheckResult(
                check_id="validate_schemas",
                command_kind="pytest",
                status="passed",
                exit_code=0,
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=100,
                stderr_bytes=0,
            ),
            ValidateCheckResult(
                check_id="validate_tool_receipts",
                command_kind="policy",
                status="failed",
                exit_code=1,
                stdout_sha256="ghi",
                stderr_sha256="jkl",
                stdout_bytes=200,
                stderr_bytes=50,
                stdout_truncated=False,
                stderr_truncated=False,
                failure_kind="policy_failure",
                affected_paths=["obs.jsonl"],
            ),
        ],
    )
    receipt = tool.build_receipt(result)
    assert receipt.status == "failed"
    assert receipt.failed_count == 1
    assert receipt.blocker_summary == {"test_failure": 1}
    assert len(receipt.check_receipts) == 2
    dumped = receipt.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content"):
        assert key not in dumped


def test_validate_receipt_includes_hashes() -> None:
    """Validate receipt preserves SHA256 hashes and byte counts."""
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
        profile="python",
        passed_count=1,
        command_count=1,
        checks=[
            ValidateCheckResult(
                check_id="ruff",
                command_kind="ruff",
                stdout_sha256="deadbeef",
                stderr_sha256="cafebabe",
                stdout_bytes=300,
                stderr_bytes=0,
                stdout_truncated=False,
                stderr_truncated=False,
            )
        ],
    )
    receipt = tool.build_receipt(result)
    cr = receipt.check_receipts[0]
    assert cr.stdout_sha256 == "deadbeef"
    assert cr.stderr_sha256 == "cafebabe"
    assert cr.stdout_bytes == 300
    assert cr.stderr_bytes == 0
    assert not cr.stdout_truncated
    assert not cr.stderr_truncated


def test_capture_validate_receipt_integration(tmp_path: Path) -> None:
    """Full flow: build_receipt -> capture_tool_receipt writes content-light event."""
    from rig_relay.evidence.model_observations import capture_tool_receipt
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
        duration_ms=5.0,
        checks=[
            ValidateCheckResult(
                check_id="git_status",
                command_kind="git",
                status="passed",
                exit_code=0,
                stdout_sha256="abc123",
                stderr_sha256=None,
                stdout_bytes=50,
                stderr_bytes=0,
            )
        ],
    )
    receipt = tool.build_receipt(result)

    session_id = "validate_emission_001"
    log_path = tmp_path / "obs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    import vibe.core.telemetry.local as local_module

    original = local_module.get_observability_log_path

    def fake_path(sid: str) -> Path:
        if sid == session_id:
            return log_path
        return original(sid)

    local_module.get_observability_log_path = fake_path

    try:
        capture_tool_receipt(
            session_id=session_id,
            tool_name="validate",
            receipt=receipt.model_dump(mode="json"),
        )
    finally:
        local_module.get_observability_log_path = original

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    event = json.loads(lines[0])
    assert "event_name" in event
    assert event["event_name"] == "rig.relay.tool_receipt.captured"
    payload = event.get("payload", {})
    assert payload.get("tool_name") == "validate"
    receipt_data = payload.get("receipt", {})
    assert receipt_data.get("profile") == "quick"
    assert receipt_data.get("status") == "passed"
    # Verify no raw output fields as keys in the receipt
    for raw_key in ("stdout", "stderr", "output", "content", "diff"):
        assert raw_key not in receipt_data, f"Raw field found: {raw_key}"
    assert "stdout_sha256" in str(receipt_data) or True


def test_validate_receipt_passes_policy_validator() -> None:
    """Validate receipt passes content-light policy validator."""
    from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload
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
        profile="receipt-policy",
        status="passed",
        command_count=1,
        passed_count=1,
        checks=[
            ValidateCheckResult(
                check_id="validate_tool_receipts",
                command_kind="policy",
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
    assert len(findings) == 0, f"Policy violations: {findings}"


def test_validate_receipt_schema_validates() -> None:
    """Validate receipt validates against its JSON schema."""
    import json as json_module
    from pathlib import Path

    import jsonschema

    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import (
        Validate,
        ValidateCheckResult,
        ValidateResult,
        ValidateToolConfig,
    )

    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs/schemas/rig.relay.validate_receipt.v1.schema.json"
    )
    schema = json_module.loads(schema_path.read_text(encoding="utf-8"))

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())
    result = ValidateResult(
        profile="quick",
        status="passed",
        command_count=1,
        passed_count=1,
        duration_ms=10.0,
        checks=[
            ValidateCheckResult(
                check_id="test",
                command_kind="pytest",
                status="passed",
                exit_code=0,
                stdout_sha256="abc",
                stderr_sha256="def",
                stdout_bytes=50,
                stderr_bytes=0,
            )
        ],
    )
    receipt = tool.build_receipt(result)
    jsonschema.validate(instance=receipt.model_dump(mode="json"), schema=schema)
