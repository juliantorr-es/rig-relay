from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

import json
from pathlib import Path
from typing import Any

from rig_relay.desktop.authorization_receipts import (
    inspect_receipt,
    mint_dev_receipt,
    mint_local_auth_receipt,
)
from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.desktop.local_system_auth import (
    LocalAuthResult,
    authenticate_local_user,
    local_system_auth_available,
)


def _request(
    intent_name: str, parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": "test_intent_002",
        "created_at": "2026-05-13T00:00:00Z",
        "intent_name": intent_name,
        "parameters": parameters or {},
        "dry_run": True,
    }


def test_mint_dev_receipt_for_checkpoint_commit(tmp_path: Path) -> None:
    result = mint_dev_receipt("checkpoint.commit", receipts_dir=tmp_path)
    assert result["valid"] is True
    assert result["action"] == "checkpoint.commit"
    assert result["receipt_sha256"].startswith("sha256:")
    assert Path(result["receipt_ref"]).is_file()


def test_mint_dev_receipt_for_archive(tmp_path: Path) -> None:
    result = mint_dev_receipt("lease_cleanup.archive", receipts_dir=tmp_path)
    assert result["valid"] is True
    assert result["action"] == "lease_cleanup.archive"


def test_mint_dev_receipt_refuses_bash(tmp_path: Path) -> None:
    result = mint_dev_receipt("bash", receipts_dir=tmp_path)
    assert result["valid"] is False
    assert result["status"] == "refused"


def test_local_system_auth_available_returns_bool() -> None:
    assert isinstance(local_system_auth_available(), bool)


def test_authenticate_local_user_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.platform.system", lambda: "Linux"
    )
    result = authenticate_local_user("Reason")
    assert result.status == "unavailable"
    assert result.available is False


def test_inspect_receipt_returns_metadata(tmp_path: Path) -> None:
    receipt_path = mint_dev_receipt("checkpoint.commit", receipts_dir=tmp_path)[
        "receipt_ref"
    ]
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    result = inspect_receipt(receipt)
    assert result["valid"] is True
    assert result["status"] == "valid"
    assert result["receipt_sha256"] == receipt["receipt_sha256"]


def test_inspect_expired_receipt_is_invalid() -> None:
    result = inspect_receipt({
        "schema_version": "rig.relay.step_up_authorization_receipt.v1",
        "authorization_id": "authz_test",
        "created_at": "2026-05-13T00:00:00Z",
        "action": "checkpoint.commit",
        "method": "none_dev_only",
        "user_verified": True,
        "expires_at": "2000-01-01T00:00:00Z",
        "challenge_sha256": "sha256:" + "0" * 64,
        "receipt_sha256": "sha256:" + "1" * 64,
    })
    assert result["valid"] is False
    assert result["status"] == "expired"


def test_execute_intent_mint_dev_receipt_is_content_light(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = execute_desktop_intent(
        _request(
            "mint_authorization_receipt_dev",
            {"action": "checkpoint.commit", "ttl_seconds": 300, "reason": "dev"},
        )
    )
    assert result["status"] == "completed"
    assert result["output_refs"]
    audit_path = (
        Path(__file__).resolve().parent.parent.parent
        / ".build"
        / "rig-relay"
        / "desktop"
        / "intents"
        / "intent_results"
        / f"{result['intent_id']}.json"
    )
    assert audit_path.is_file()
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "authorization_id" not in audit_text
    assert "challenge_sha256" not in audit_text


def test_execute_intent_inspect_receipt_is_content_light(tmp_path: Path) -> None:
    receipt = mint_dev_receipt("checkpoint.commit", receipts_dir=tmp_path)
    raw = json.loads(Path(receipt["receipt_ref"]).read_text(encoding="utf-8"))
    result = execute_desktop_intent(
        _request("inspect_authorization_receipt", {"authorization_receipt": raw})
    )
    assert result["status"] == "completed"
    assert result["result_kind"] == "authorization_receipt"


def test_execute_intent_mint_local_auth_receipt_succeeds(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.authenticate_local_user",
        lambda reason, timeout_seconds=None: LocalAuthResult(
            status="authorized", available=True, reason="ok", warnings=[]
        ),
    )
    result = execute_desktop_intent(
        _request(
            "mint_authorization_receipt_local",
            {"action": "checkpoint.commit", "reason": "step-up"},
        )
    )
    assert result["status"] == "completed"
    assert result["result_kind"] == "authorization_receipt"
    assert result["output_refs"]


def test_mint_local_auth_receipt_succeeds_with_mocked_auth(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.authenticate_local_user",
        lambda reason, timeout_seconds=None: LocalAuthResult(
            status="authorized", available=True, reason="ok", warnings=[]
        ),
    )
    result = mint_local_auth_receipt("checkpoint.commit", receipts_dir=tmp_path)
    assert result["valid"] is True
    assert result["action"] == "checkpoint.commit"
    assert result["receipt_sha256"].startswith("sha256:")
    receipt = json.loads(Path(result["receipt_ref"]).read_text(encoding="utf-8"))
    assert receipt["method"] == "local_system_auth"


def test_mint_local_auth_receipt_refuses_when_policy_unavailable(
    monkeypatch: Any,
) -> None:
    # Mock PyObjC structures
    class MockError:
        def __str__(self):
            return "Touch ID not enrolled"

    class MockLAContext:
        def canEvaluatePolicy_error_(self, policy, error):
            return False, MockError()

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    mock_la = type(
        "MockLA",
        (),
        {"LAContext": MockLAContext, "LAPolicyDeviceOwnerAuthentication": 1},
    )

    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: mock_la if name == "LocalAuthentication" else None,
    )

    result = mint_local_auth_receipt("checkpoint.commit")
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert "Touch ID not enrolled" in result["warnings"][-1]


def test_authenticate_local_user_timeout(monkeypatch: Any) -> None:
    class MockLAContext:
        def canEvaluatePolicy_error_(self, policy, error):
            return True, None

        def evaluatePolicy_localizedReason_reply_(self, policy, reason, reply):
            # Don't call reply, simulate timeout
            pass

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    mock_la = type(
        "MockLA",
        (),
        {"LAContext": MockLAContext, "LAPolicyDeviceOwnerAuthentication": 1},
    )

    monkeypatch.setattr(
        "rig_relay.desktop.local_system_auth.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: mock_la if name == "LocalAuthentication" else None,
    )

    # Use short timeout for test
    result = authenticate_local_user("Reason", timeout_seconds=1)
    assert result.status == "cancelled"
    assert "timed out" in result.reason
