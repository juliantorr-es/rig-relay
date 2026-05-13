from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import uuid

from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.governance.auth_receipts import generate_dev_receipt


def _valid_request(
    intent_name: str, parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": f"test_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(UTC).isoformat(),
        "intent_name": intent_name,
        "parameters": parameters or {},
        "dry_run": True,
    }


class TestProtectedIntentsPhase1:
    def test_checkpoint_commit_refused_without_receipt(self):
        request = _valid_request("checkpoint.commit", {"include_paths": ["README.md"]})
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"
        assert "Authorization receipt required" in result["summary"]

    def test_checkpoint_commit_refused_with_invalid_receipt(self):
        request = _valid_request("checkpoint.commit", {"include_paths": ["README.md"]})
        request["authorization_receipt"] = {
            "schema_version": "rig.relay.step_up_authorization_receipt.v1",
            "action": "wrong_action",
            "user_verified": True,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"
        assert "Action mismatch" in result["summary"]

    def test_checkpoint_commit_succeeds_with_valid_receipt(self, monkeypatch: Any):
        # We need a real repo for checkpoint to work, or we mock the tool.
        # For this test, we just want to verify it passes the intent gate.

        receipt = generate_dev_receipt("checkpoint.commit")
        request = _valid_request(
            "checkpoint.commit",
            {"include_paths": ["README.md"], "message": "Test commit"},
        )
        request["authorization_receipt"] = receipt

        # Mock _execute_checkpoint_commit to avoid git dependencies
        from rig_relay.desktop import intents

        def mock_execute(
            intent_id: str,
            params: dict[str, Any],
            receipt_data: dict[str, Any] | None = None,
        ):
            return intents._build_result(
                "checkpoint.commit", intent_id, "completed", summary="Mock success"
            )

        monkeypatch.setattr(intents, "_execute_checkpoint_commit", mock_execute)

        result = execute_desktop_intent(request)
        assert result["status"] == "completed"
        assert result["summary"] == "Mock success"

    def test_lease_cleanup_archive_refused_without_receipt(self):
        request = _valid_request("lease_cleanup.archive")
        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "authorization_failed"
        assert "Authorization receipt required" in result["summary"]

    def test_lease_cleanup_archive_succeeds_with_valid_receipt(self, monkeypatch: Any):
        receipt = generate_dev_receipt("lease_cleanup.archive")
        request = _valid_request("lease_cleanup.archive")
        request["authorization_receipt"] = receipt

        from rig_relay.desktop import intents

        def mock_execute(intent_id: str, params: dict[str, Any]):
            return intents._build_result(
                "lease_cleanup.archive",
                intent_id,
                "completed",
                summary="Mock cleanup success",
            )

        monkeypatch.setattr(intents, "_execute_lease_cleanup_archive", mock_execute)

        result = execute_desktop_intent(request)
        assert result["status"] == "completed"
        assert result["summary"] == "Mock cleanup success"

    def test_bash_still_refused_even_with_receipt(self):
        # Even if we provide a receipt, bash is in PROTECTED_INTENTS but not PHASE_1_ENABLED
        receipt = generate_dev_receipt("bash")
        request = _valid_request("bash", {"command": "ls"})
        request["authorization_receipt"] = receipt

        result = execute_desktop_intent(request)
        assert result["status"] == "refused"
        assert result["authorization_required"] is True
        assert result["error_code"] == "protected_intent_not_enabled"
        assert "Not enabled for receipt-gated execution" in result["summary"]

    def test_audit_event_includes_receipt_metadata(self, monkeypatch: Any):
        # Verify that audit events record receipt metadata but not raw receipt
        receipt = generate_dev_receipt("checkpoint.commit")
        request = _valid_request("checkpoint.commit", {"include_paths": ["README.md"]})
        request["authorization_receipt"] = receipt

        # Capture events
        captured_events = []
        from rig_relay.desktop import intent_audit

        def mock_write_event(event: dict[str, Any], build_root: Any = None):
            captured_events.append(event)

        monkeypatch.setattr(intent_audit, "_write_event", mock_write_event)

        # Mock execution
        from rig_relay.desktop import intents

        def mock_execute(
            intent_id: str,
            params: dict[str, Any],
            receipt_data: dict[str, Any] | None = None,
        ):
            return intents._build_result(
                "checkpoint.commit", intent_id, "completed", summary="Mock success"
            )

        monkeypatch.setattr(intents, "_execute_checkpoint_commit", mock_execute)

        execute_desktop_intent(request)

        # Check result event
        result_event = next(
            e for e in captured_events if e["event_name"] == "desktop.intent.completed"
        )
        assert result_event["authorization_receipt_sha256"] == receipt["receipt_sha256"]
        assert result_event["authorization_action"] == "checkpoint.commit"
        assert result_event["authorization_status"] == "valid"

        # Ensure raw receipt is NOT in the event
        assert "authorization_receipt" not in result_event
        # And not in the result dict either (already checked by TestProtectedIntentsPhase1 if we had more tests)
