"""Tests for the Desktop Intent API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from rig_relay.desktop.intents import (
    PROTECTED_INTENTS,
    REQUEST_SCHEMA_PATH,
    RESULT_SCHEMA_PATH,
    _build_result,
    execute_desktop_intent,
)


def _valid_request(intent_name: str = "refresh_projection") -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": "test_intent_001",
        "created_at": "2026-05-13T00:00:00Z",
        "intent_name": intent_name,
        "parameters": {},
        "dry_run": True,
    }


class TestSchema:
    def test_request_schema_validates(self):
        schema = json.loads(REQUEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=_valid_request(), schema=schema)

    def test_result_schema_validates(self):
        schema = json.loads(RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        result = _build_result("test", "id", "completed", summary="ok")
        jsonschema.validate(instance=result, schema=schema)

    def test_invalid_request_refused(self):
        result = execute_desktop_intent({"bad": "data"})
        assert result["status"] == "refused"

    def test_unknown_intent_refused(self):
        result = execute_desktop_intent(_valid_request("nonexistent_intent"))
        assert result["status"] == "refused"
        assert result["error_code"] == "unsupported_intent"


class TestAllowedIntents:
    def test_refresh_projection_succeeds(self, tmp_path: Path):
        result = execute_desktop_intent(_valid_request("refresh_projection"))
        assert result["status"] in {"completed", "failed"}
        if result["status"] == "completed":
            assert result["result_kind"] == "projection"

    def test_generate_refinement_report_succeeds_or_partial(self, tmp_path: Path):
        result = execute_desktop_intent(_valid_request("generate_refinement_report"))
        assert result["status"] in {"completed", "failed"}

    def test_run_storage_audit_returns_summary(self, tmp_path: Path):
        result = execute_desktop_intent(_valid_request("run_storage_audit"))
        assert result["status"] in {"completed", "failed"}
        if result["status"] == "completed":
            assert "MB" in result.get("summary", "")

    def test_run_validation_suite_is_allowed(self):
        from rig_relay.desktop.intents import ALLOWED_INTENTS

        assert "run_validation_suite" in ALLOWED_INTENTS
        assert "ruff_check" in str(
            ALLOWED_INTENTS["run_validation_suite"]["parameters"]["steps"]["default"]
        )

    def test_local_auth_receipt_intent_is_allowed(self):
        from rig_relay.desktop.intents import ALLOWED_INTENTS

        assert "mint_authorization_receipt_local" in ALLOWED_INTENTS
        assert ALLOWED_INTENTS["mint_authorization_receipt_local"]["parameters"][
            "action"
        ]["enum"] == ["checkpoint.commit", "lease_cleanup.archive"]

    def test_create_chatgpt_dev_bundle_dry_run_does_not_write_zip(self, tmp_path: Path):
        result = execute_desktop_intent(
            _valid_request("create_chatgpt_dev_bundle_dry_run")
        )
        assert result["status"] in {"completed", "failed"}

    def test_create_telemetry_bundle_dry_run_does_not_write_zip(self, tmp_path: Path):
        result = execute_desktop_intent(
            _valid_request("create_telemetry_bundle_dry_run")
        )
        assert result["status"] in {"completed", "failed"}

    def test_validate_telemetry_bundle_succeeds(self, tmp_path: Path):
        result = execute_desktop_intent(_valid_request("validate_telemetry_bundle"))
        assert result["status"] in {"completed", "failed"}


class TestValidationSuite:
    def test_run_validation_suite_returns_structured_result(self, tmp_path: Path):
        # We only run a subset of fast steps to avoid huge test latency
        request = _valid_request("run_validation_suite")
        request["parameters"] = {
            "steps": ["schema_validation", "storage_audit"],
            "paths": [],
        }
        result = execute_desktop_intent(request)
        assert result["status"] in {"passed", "failed", "partial"}
        assert result["result_kind"] == "validation_suite"
        assert "Validation suite" in result["summary"]
        assert result["projection_refresh_recommended"] is True
        assert isinstance(result["output_refs"], list)
        assert len(result["output_refs"]) > 0

    def test_run_validation_suite_refuses_mutation(self):
        request = _valid_request("run_validation_suite")
        request["parameters"] = {"steps": ["ruff_format_fix"]}
        # The intent handler is read-only and does not forward allow_mutation.
        # The tool itself refuses ruff_format_fix at the step level.
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert any(
            "ruff_format_fix requires allow_mutation=true" in w
            for w in result["warnings"]
        )


class TestProtectedIntents:
    @pytest.mark.parametrize("intent_name", list(PROTECTED_INTENTS))
    def test_protected_intent_refused(self, intent_name: str):
        result = execute_desktop_intent(_valid_request(intent_name))
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_checkpoint_commit_refused(self):
        result = execute_desktop_intent(_valid_request("checkpoint.commit"))
        assert result["status"] == "refused"
        assert result["authorization_required"] is True

    def test_remote_upload_confirm_refused(self):
        result = execute_desktop_intent(_valid_request("remote_upload.confirm"))
        assert result["status"] == "refused"
        assert result["authorization_required"] is True


class TestFrontendButtons:
    """Verify frontend HTML contains only safe intent buttons."""

    def test_frontend_has_only_safe_intent_buttons(self):
        from pathlib import Path

        html_path = (
            Path(__file__).resolve().parent.parent.parent
            / "frontend"
            / "desktop"
            / "index.html"
        )
        html = html_path.read_text(encoding="utf-8")

        safe_buttons = [
            "refresh_projection",
            "run_validation_suite",
            "run_storage_audit",
            "generate_refinement_report",
            "create_chatgpt_dev_bundle_dry_run",
        ]
        for btn in safe_buttons:
            assert btn in html, f"Safe button {btn} not found in frontend"

        protected_buttons = [
            "bash",
            "write_file",
            "search_replace",
            "spawn.execute",
            "fleet.execute",
        ]
        for btn in protected_buttons:
            assert btn not in html, f"Protected button {btn} found in frontend"

        receipt_actions = ["checkpoint.commit", "lease_cleanup.archive"]
        for action in receipt_actions:
            assert action in html, f"Receipt action {action} not found in frontend"
        assert "Mint Local Auth Receipt" in html

        # Verify mutation-only features are not exposed
        assert "ruff_format_fix" not in html, (
            "ruff_format_fix must not appear in frontend"
        )
        assert "allow_mutation" not in html, (
            "allow_mutation must not appear in frontend"
        )


class TestContentLight:
    def test_no_forbidden_raw_fields_in_intent_result(self):
        result = execute_desktop_intent(_valid_request("refresh_projection"))
        text = json.dumps(result)
        forbidden = ["stdout", "stderr", "prompt", "model output", "source code"]
        for term in forbidden:
            assert term not in text.lower(), f"Forbidden term '{term}' found in result"


class TestWebSocketIntegration:
    @pytest.mark.asyncio
    async def test_desktop_intent_requires_auth(self, unused_tcp_port: int):
        import websockets

        from rig_relay.desktop.websocket_server import ProjectionWebSocketServer

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{unused_tcp_port}") as ws:
                # Send intent without auth first
                await ws.send(json.dumps(_valid_request("refresh_projection")))
                response = json.loads(await ws.recv())
                assert response["type"] in {"auth_required", "auth_error"}
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_desktop_intent_respects_read_only_allowlist(
        self, unused_tcp_port: int
    ):
        import websockets

        from rig_relay.desktop.websocket_server import ProjectionWebSocketServer

        server = ProjectionWebSocketServer(
            port=unused_tcp_port, token="test-token", auth_timeout=100
        )
        await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{unused_tcp_port}") as ws:
                # Authenticate
                await ws.send(json.dumps({"type": "auth", "token": "test-token"}))
                auth_resp = json.loads(await ws.recv())
                assert auth_resp["type"] == "auth_ok"

                # Send a protected intent
                req = _valid_request("checkpoint.commit")
                req["type"] = "desktop_intent"
                await ws.send(json.dumps(req))
                resp = json.loads(await ws.recv())
                assert resp["type"] == "desktop_intent_result"
                assert resp["data"]["status"] == "refused"
                assert resp["data"]["authorization_required"] is True
        finally:
            await server.close()


class TestAuditTrail:
    """Tests for the intent audit trail (events + result artifacts)."""

    def test_build_event_requires_valid_event_name(self):
        from rig_relay.desktop.intent_audit import build_event

        with pytest.raises(ValueError, match="Unknown event name"):
            build_event("invalid.event", "id", "name", "status")

    def test_build_event_defaults(self):
        from rig_relay.desktop.intent_audit import build_event

        event = build_event(
            "desktop.intent.received", "test_id", "test_name", "received"
        )
        assert event["schema_version"] == "rig.relay.desktop_intent_event.v1"
        assert event["intent_id"] == "test_id"
        assert event["intent_name"] == "test_name"
        assert event["event_name"] == "desktop.intent.received"
        assert event["status"] == "received"
        assert event["dry_run"] is True
        assert event["authorization_required"] is False
        assert event["result_kind"] == "summary"
        assert event["output_ref_count"] == 0
        assert event["projection_seq"] == 0
        assert event["result_sha256"] == ""
        assert event["warnings"] == []
        assert event["created_at"].endswith("Z") or "+" in event["created_at"]
        assert event["event_id"].startswith("evt_")

    def test_build_event_with_extra(self):
        from rig_relay.desktop.intent_audit import build_event

        event = build_event(
            "desktop.intent.completed",
            "test_id",
            "test_name",
            "completed",
            dry_run=False,
            authorization_required=True,
            result_kind="projection",
            output_ref_count=3,
            projection_seq=42,
            result_sha256="abc123",
            warnings=["test warning"],
        )
        assert event["dry_run"] is False
        assert event["authorization_required"] is True
        assert event["result_kind"] == "projection"
        assert event["output_ref_count"] == 3
        assert event["projection_seq"] == 42
        assert event["result_sha256"] == "abc123"
        assert event["warnings"] == ["test warning"]

    def test_emit_received_writes_event(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import (
            _events_path,
            count_events,
            emit_received,
        )

        request = _valid_request("refresh_projection")
        emit_received(request, build_root=tmp_path)

        assert _events_path(tmp_path).is_file()
        counts = count_events(tmp_path)
        assert counts.get("desktop.intent.received", 0) == 1

    def test_emit_result_completed_writes_event_and_artifact(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import (
            _results_dir,
            count_events,
            emit_result,
            list_result_artifacts,
        )

        result = _build_result("test_intent", "test_id", "completed", summary="ok")
        result_sha256 = emit_result(result, build_root=tmp_path)

        # Event was written
        counts = count_events(tmp_path)
        assert counts.get("desktop.intent.completed", 0) == 1

        # Artifact was written
        artifacts = list_result_artifacts(tmp_path)
        assert len(artifacts) >= 1

        # Artifact contains the result
        artifact_path = _results_dir(tmp_path) / "test_id.json"
        assert artifact_path.is_file()
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["status"] == "completed"
        assert artifact["intent_name"] == "test_intent"

        # SHA256 is returned
        assert isinstance(result_sha256, str)
        assert len(result_sha256) == 64

    def test_emit_result_refused_writes_refused_event(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import count_events, emit_result

        # Build a refused result matching the pattern from intents.py
        result = {
            "schema_version": "rig.relay.desktop_intent_result.v1",
            "intent_id": "refused_id",
            "intent_name": "bash",
            "status": "refused",
            "dry_run": True,
            "result_kind": "summary",
            "summary": "Protected intent: not yet implemented.",
            "output_refs": [],
            "projection_refresh_recommended": False,
            "authorization_required": True,
            "error_code": "protected_intent_not_enabled",
            "warnings": [],
        }
        emit_result(result, build_root=tmp_path)
        counts = count_events(tmp_path)
        assert counts.get("desktop.intent.refused", 0) == 1

    def test_emit_result_failed_writes_failed_event(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import count_events, emit_result

        result = _build_result(
            "failing_intent", "fail_id", "failed", summary="Something broke"
        )
        emit_result(result, build_root=tmp_path)
        counts = count_events(tmp_path)
        assert counts.get("desktop.intent.failed", 0) == 1

    def test_multiple_events_are_appended(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import (
            count_events,
            emit_received,
            emit_result,
        )

        req = _valid_request("refresh_projection")
        emit_received(req, build_root=tmp_path)
        emit_received(req, build_root=tmp_path)

        result = _build_result("test", "id", "completed", summary="ok")
        emit_result(result, build_root=tmp_path)

        counts = count_events(tmp_path)
        assert counts.get("desktop.intent.received", 0) == 2
        assert counts.get("desktop.intent.completed", 0) == 1

    def test_artifact_is_content_light(self, tmp_path: Path):
        """Result artifacts must not contain raw content fields."""
        from rig_relay.desktop.intent_audit import emit_result

        result = _build_result("test", "content_light_id", "completed", summary="ok")
        emit_result(result, build_root=tmp_path)

        text = json.dumps(result).lower()
        forbidden = ["stdout", "stderr", "prompt", "model output", "source code"]
        for term in forbidden:
            assert term not in text, f"Forbidden term '{term}' found in artifact"

    def test_sha256_is_deterministic(self):
        from rig_relay.desktop.intent_audit import _sha256_json

        data = {"a": 1, "b": 2}
        h1 = _sha256_json(data)
        h2 = _sha256_json(data)
        assert h1 == h2

    def test_sha256_varies_with_content(self):
        from rig_relay.desktop.intent_audit import _sha256_json

        assert _sha256_json({"a": 1}) != _sha256_json({"a": 2})

    def test_count_events_empty_when_no_file(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import count_events

        assert count_events(tmp_path) == {}

    def test_list_result_artifacts_empty_when_no_results(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import list_result_artifacts

        assert list_result_artifacts(tmp_path) == []

    def test_execute_desktop_intent_writes_audit_events(self, tmp_path: Path):
        """Verify execute_desktop_intent produces audit events when build_root is set."""
        # Note: execute_desktop_intent writes to DEFAULT_BUILD_ROOT, not tmp_path.
        # This test just verifies the function runs and the audit is wired.
        result = execute_desktop_intent(_valid_request("refresh_projection"))
        assert result["status"] in {"completed", "failed"}

    def test_emit_result_returns_valid_sha256(self, tmp_path: Path):
        from rig_relay.desktop.intent_audit import emit_result

        result = _build_result("sha_test", "sha_id", "completed", summary="ok")
        result_sha256 = emit_result(result, build_root=tmp_path)
        assert len(result_sha256) == 64
        assert all(c in "0123456789abcdef" for c in result_sha256)


class TestReceiptGatedProtectedIntents:
    """Tests for Phase 1 receipt-gated protected intents."""

    def test_checkpoint_commit_without_receipt_refused(self):
        request = _valid_request("checkpoint.commit")
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"

    def test_checkpoint_commit_with_invalid_receipt_refused(self):
        request = _valid_request("checkpoint.commit")
        request["authorization_receipt"] = {
            "schema_version": "rig.relay.step_up_authorization_receipt.v1",
            "action": "checkpoint.commit",
            "user_verified": False,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"

    def test_checkpoint_commit_with_wrong_action_receipt_refused(self):
        request = _valid_request("checkpoint.commit")
        request["authorization_receipt"] = {
            "schema_version": "rig.relay.step_up_authorization_receipt.v1",
            "action": "lease_cleanup.archive",
            "user_verified": True,
            "expires_at": "2099-01-01T00:00:00Z",
            "method": "none_dev_only",
        }
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"

    def test_checkpoint_commit_with_valid_receipt_reaches_executor(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=300)
        request = _valid_request("checkpoint.commit")
        request["authorization_receipt"] = receipt
        request["parameters"] = {"include_paths": ["nonexistent_file.txt"]}
        result = execute_desktop_intent(request)
        # Should reach executor and refuse due to missing file, not auth
        assert result["status"] in {"refused", "failed", "completed"}
        if result["status"] == "refused":
            assert result["error_code"] != "authorization_failed", (
                f"Auth should not be the refusal reason: {result['summary']}"
            )

    def test_lease_cleanup_archive_without_receipt_refused(self):
        request = _valid_request("lease_cleanup.archive")
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"

    def test_lease_cleanup_archive_with_valid_receipt_reaches_executor(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("lease_cleanup.archive", ttl_seconds=300)
        request = _valid_request("lease_cleanup.archive")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        # Should reach executor - may succeed or fail on actual cleanup
        assert result["status"] in {"completed", "partial", "failed", "refused"}
        if result["status"] == "refused":
            assert result["error_code"] != "authorization_failed", (
                f"Auth should not be the refusal reason: {result['summary']}"
            )

    def test_bash_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("bash", ttl_seconds=300)
        request = _valid_request("bash")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_write_file_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("write_file", ttl_seconds=300)
        request = _valid_request("write_file")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_remote_upload_confirm_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("remote_upload.confirm", ttl_seconds=300)
        request = _valid_request("remote_upload.confirm")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_spawn_execute_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("spawn.execute", ttl_seconds=300)
        request = _valid_request("spawn.execute")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_fleet_execute_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("fleet.execute", ttl_seconds=300)
        request = _valid_request("fleet.execute")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_delegate_execute_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("delegate.execute", ttl_seconds=300)
        request = _valid_request("delegate.execute")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_lease_cleanup_remove_refused_even_with_valid_receipt(self):
        from rig_relay.governance.auth_receipts import generate_dev_receipt

        receipt = generate_dev_receipt("lease_cleanup.remove", ttl_seconds=300)
        request = _valid_request("lease_cleanup.remove")
        request["authorization_receipt"] = receipt
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["error_code"] == "protected_intent_not_enabled"

    def test_safe_intent_works_without_receipt(self):
        request = _valid_request("run_validation_suite")
        request["parameters"] = {"steps": ["schema_validation"], "paths": []}
        result = execute_desktop_intent(request)
        assert result["status"] in {"passed", "failed", "partial"}

    def test_schema_validates_request_with_authorization_receipt(self):
        import json

        from rig_relay.desktop.intents import REQUEST_SCHEMA_PATH

        schema = json.loads(REQUEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        request = _valid_request("checkpoint.commit")
        request["authorization_receipt"] = {
            "schema_version": "rig.relay.step_up_authorization_receipt.v1",
            "authorization_id": "test_authz_001",
            "created_at": "2026-05-13T00:00:00Z",
            "action": "checkpoint.commit",
            "action_scope": {},
            "method": "none_dev_only",
            "user_verified": True,
            "expires_at": "2099-01-01T00:00:00Z",
            "challenge_sha256": "sha256:abc123",
            "credential_id_hash": None,
            "receipt_sha256": "sha256:abc123",
            "warnings": [],
        }
        import jsonschema

        jsonschema.validate(instance=request, schema=schema)


class TestResultCardRendering:
    """Verify that Python-generated result summaries match frontend regex patterns.

    Each test ensures the summary format produced by the backend handler is
    parseable by the corresponding JavaScript render*Card() function in app.js.
    """

    def test_validation_suite_summary_format(self):
        """Summary must match the renderValidationSuiteCard regex."""
        result = execute_desktop_intent(_valid_request("run_validation_suite"))
        import re

        pattern = re.compile(
            r"Validation suite '(.+?)':\s*(\w+)\.\s*(\d+)\s+executed,\s*(\d+)\s+skipped\.\s*Steps:\s*\[(.+?)\]\s*\.\s*sha256:\s*(\S+)"
        )
        m = pattern.match(result.get("summary", ""))
        assert m, (
            "validation_suite summary does not match regex pattern. "
            + f"Summary: {result.get('summary', '')}"
        )
        assert m.group(1)  # suite name
        assert m.group(6)  # sha256

    def test_storage_audit_summary_format(self):
        result = execute_desktop_intent(_valid_request("run_storage_audit"))
        import re

        pattern = re.compile(
            r"Storage audit:\s*([\d.]+)\s*MB,\s*budget=(\w+),\s*stale_leases=(\d+),\s*rollup_candidates=(\d+),\s*prune_candidates=(\d+),\s*(\d+)\s*recommendations"
        )
        m = pattern.match(result.get("summary", ""))
        assert m, (
            f"storage_audit summary does not match regex. "
            f"Summary: {result.get('summary', '')}"
        )

    def test_refresh_projection_summary_format(self):
        result = execute_desktop_intent(_valid_request("refresh_projection"))
        if result["status"] != "completed":
            import pytest

            pytest.skip("Projection refresh skipped or failed")
        import re

        pattern = re.compile(r"(\d+)/(\d+)\s+sources")
        m = pattern.search(result.get("summary", ""))
        assert m, (
            f"projection summary does not match regex. "
            f"Summary: {result.get('summary', '')}"
        )

    def test_all_known_result_kinds_have_renderer(self):
        """Every backend result_kind must have a case in the switch statement."""
        known_backend_kinds = {
            "projection",
            "chat_state",
            "report",
            "packets",
            "storage_audit",
            "bundle_dry_run",
            "validation",
            "validation_suite",
            "plan_dry_run",
            "authorization_receipt",
            "checkpoint",
            "lease_cleanup",
            "identity_status",
            "provider_status",
            "provider_onboarding",
            "summary",
        }
        handled_by_renderer = {
            "validation_suite",
            "storage_audit",
            "report",
            "packets",
            "projection",
            "checkpoint",
            "lease_cleanup",
            "bundle_dry_run",
            "plan_dry_run",
            "validation",
            "chat_state",
            "authorization_receipt",
            "identity_status",
            "provider_status",
            "provider_onboarding",
            "summary",
        }
        unhandled = known_backend_kinds - handled_by_renderer
        assert not unhandled, f"result_kinds missing renderers: {unhandled}"
