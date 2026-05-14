"""Tests for rig_relay.evidence.session_lifecycle_tool — Pydantic models and tool class."""

from __future__ import annotations

import json
from pathlib import Path
import time

import jsonschema

from rig_relay.evidence.session_lifecycle_tool import (
    CompactionDetail,
    ProtectedDetail,
    RefusalDetail,
    SessionLifecycleFinalizeRequest,
    SessionLifecycleFinalizeResult,
    SessionLifecycleFinalizeTool,
)

REQUEST_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.session_lifecycle_finalize_request.v1.schema.json"
)

RESULT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.session_lifecycle_finalize_result.v1.schema.json"
)


def _make_file(path: Path, text: str = "x", days_ago: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if days_ago:
        past = time.time() - (days_ago * 86400)
        import os

        os.utime(path, (past, past))
    return path


# ── Model tests ───────────────────────────────────────────────────────


class TestSessionLifecycleFinalizeRequest:
    def test_minimal_request(self) -> None:
        req = SessionLifecycleFinalizeRequest(session_id="test-session")
        assert req.session_id == "test-session"
        assert req.dry_run is True
        assert req.allow_compaction is False
        assert req.allow_prune is False

    def test_request_rejects_unknown_fields_via_schema(self) -> None:
        with open(REQUEST_SCHEMA_PATH) as f:
            schema = json.load(f)
        bad = {"session_id": "test", "unknown_field": "x"}
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(bad))
        assert errors

    def test_request_schema_validates(self) -> None:
        with open(REQUEST_SCHEMA_PATH) as f:
            schema = json.load(f)
        req = SessionLifecycleFinalizeRequest(session_id="test-session")
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(req.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_request_dry_run_default_is_true(self) -> None:
        req = SessionLifecycleFinalizeRequest(session_id="s1")
        assert req.dry_run is True

    def test_request_mutation_flags_default_false(self) -> None:
        req = SessionLifecycleFinalizeRequest(session_id="s1")
        assert req.allow_compaction is False
        assert req.allow_prune is False


class TestSessionLifecycleFinalizeResult:
    def test_minimal_result(self) -> None:
        result = SessionLifecycleFinalizeResult(status="ok", session_id="test-session")
        assert result.status == "ok"
        assert result.scanned_files == 0

    def test_result_rejects_unknown_fields_via_schema(self) -> None:
        with open(RESULT_SCHEMA_PATH) as f:
            schema = json.load(f)
        bad = {"status": "ok", "session_id": "test", "unknown_field": "x"}
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(bad))
        assert errors

    def test_result_schema_validates(self) -> None:
        with open(RESULT_SCHEMA_PATH) as f:
            schema = json.load(f)
        result = SessionLifecycleFinalizeResult(
            status="ok",
            session_id="test-session",
            scanned_files=5,
            total_bytes_before=1000,
            total_bytes_after=800,
            compacted_count=2,
            refused_count=1,
            prune_candidate_count=3,
            deleted_count=0,
            compacted_details=[
                CompactionDetail(
                    source_path="/tmp/test.jsonl",
                    size_bytes_before=500,
                    size_bytes_after=200,
                    category="intent_events",
                    status="compacted",
                )
            ],
            protected_details=[
                ProtectedDetail(
                    path="/tmp/receipt.json", size_bytes=100, category="receipts"
                )
            ],
            refused_details=[
                RefusalDetail(
                    path="/tmp/tmp.cache", category="temp_files", reason="protected"
                )
            ],
            manifest_path="/tmp/manifest.json",
            receipt_path="/tmp/receipt.json",
        )
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_result_rejects_forbidden_raw_fields(self) -> None:
        with open(RESULT_SCHEMA_PATH) as f:
            schema = json.load(f)
        forbidden = ["stdout", "stderr", "content", "raw_prompt", "secret"]
        base = SessionLifecycleFinalizeResult(
            status="ok", session_id="test"
        ).model_dump(mode="json")
        validator = jsonschema.Draft7Validator(schema)
        for field in forbidden:
            bad = dict(base)
            bad[field] = "some value"
            errors = list(validator.iter_errors(bad))
            assert errors, f"Schema should reject forbidden field '{field}'"


class TestCompactionDetail:
    def test_minimal(self) -> None:
        detail = CompactionDetail(
            source_path="/tmp/test.jsonl", category="intent_events", status="compacted"
        )
        assert detail.source_path == "/tmp/test.jsonl"
        assert detail.size_bytes_before == 0


class TestProtectedDetail:
    def test_minimal(self) -> None:
        detail = ProtectedDetail(
            path="/tmp/receipt.json", category="receipts", size_bytes=100
        )
        assert detail.path == "/tmp/receipt.json"


class TestRefusalDetail:
    def test_minimal(self) -> None:
        detail = RefusalDetail(
            path="/tmp/tmp.cache", category="temp_files", reason="protected"
        )
        assert detail.reason == "protected"


# ── Tool tests ────────────────────────────────────────────────────────


class TestSessionLifecycleFinalizeTool:
    def test_refused_when_session_dir_missing(self, tmp_path: Path) -> None:
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="missing", sessions_root=str(tmp_path / "nonexistent")
        )
        result = tool.run(req)
        assert result.status == "refused"
        assert result.warnings

    def test_dry_run_default_does_not_create_files(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "s1"
        file_content = '{"ok": true}\n'
        _make_file(session_dir / "intent_events.jsonl", file_content)
        original_bytes = (session_dir / "intent_events.jsonl").read_bytes()
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="s1", sessions_root=str(session_dir)
        )
        result = tool.run(req)
        assert result.status == "ok"
        assert result.scanned_files > 0
        # Dry-run identifies candidates but does not modify files
        assert result.compacted_count > 0
        assert result.total_bytes_before == result.total_bytes_after
        assert not (session_dir / "lifecycle").exists()
        # Verify file content unchanged (no actual compaction occurred)
        assert (session_dir / "intent_events.jsonl").read_bytes() == original_bytes

    def test_dry_run_with_explicit_flag_does_not_modify(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "s2"
        file_content = '{"ok": true}\n'
        _make_file(session_dir / "intent_events.jsonl", file_content)
        original_bytes = (session_dir / "intent_events.jsonl").read_bytes()
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="s2",
            sessions_root=str(session_dir),
            allow_compaction=True,
            allow_prune=True,
            dry_run=True,
        )
        result = tool.run(req)
        assert result.status == "ok"
        # Dry-run identifies candidates even when flags are set; no modifications occur
        assert result.compacted_count > 0
        assert result.total_bytes_before == result.total_bytes_after
        assert not (session_dir / "lifecycle").exists()
        # Verify file content unchanged (no actual compaction occurred)
        assert (session_dir / "intent_events.jsonl").read_bytes() == original_bytes

    def test_result_is_content_light(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "s3"
        _make_file(session_dir / "intent_events.jsonl", '{"raw_prompt":"secret"}\n')
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="s3", sessions_root=str(session_dir)
        )
        result = tool.run(req)
        dumped = json.dumps(result.model_dump(mode="json"))
        assert "secret" not in dumped
        assert "raw_prompt" not in dumped

    def test_explicit_sessions_root_used(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "custom-path"
        _make_file(session_dir / "intent_events.jsonl", '{"ok": true}\n')
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="custom", sessions_root=str(session_dir)
        )
        result = tool.run(req)
        assert result.status == "ok"

    def test_result_dumps_with_schema_validation(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "s4"
        _make_file(session_dir / "intent_events.jsonl", '{"ok": true}\n')
        tool = SessionLifecycleFinalizeTool()
        req = SessionLifecycleFinalizeRequest(
            session_id="s4", sessions_root=str(session_dir)
        )
        result = tool.run(req)
        with open(RESULT_SCHEMA_PATH) as f:
            schema = json.load(f)
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(result.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"
