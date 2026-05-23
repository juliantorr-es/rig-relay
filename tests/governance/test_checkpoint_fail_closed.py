from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.coordination.store import CoordinationStore
from rig_relay.core.guard import get_guard, reset_guard
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointArgs,
    CheckpointToolConfig,
)
from rig_relay.governance.auth_receipts import (
    generate_dev_receipt,
    mint_dev_receipt,
    resolve_authorization,
    validate_receipt,
)


def _build_valid_receipt(action: str = "checkpoint.commit") -> dict[str, Any]:
    return generate_dev_receipt(action)


def _receipt_json(action: str = "checkpoint.commit") -> str:
    return json.dumps(_build_valid_receipt(action))


class TestResolveAuthorization:
    def test_valid_receipt_returns_authorized(self) -> None:
        result = resolve_authorization(
            action="checkpoint.commit",
            receipt_json=_receipt_json("checkpoint.commit"),
        )
        assert result.authorized is True
        assert result.receipt is not None
        assert result.receipt["action"] == "checkpoint.commit"

    def test_invalid_receipt_json_returns_refusal(self) -> None:
        result = resolve_authorization(
            action="checkpoint.commit",
            receipt_json="not valid json",
        )
        assert result.authorized is False
        assert result.reason == "Invalid receipt JSON"

    def test_expired_receipt_returns_refusal(self) -> None:
        receipt = generate_dev_receipt("checkpoint.commit", ttl_seconds=0)
        result = resolve_authorization(
            action="checkpoint.commit",
            receipt_json=json.dumps(receipt),
        )
        assert result.authorized is False
        assert result.reason is not None and "expired" in result.reason.lower()

    def test_wrong_action_receipt_returns_refusal(self) -> None:
        receipt = generate_dev_receipt("spawn.execute")
        result = resolve_authorization(
            action="checkpoint.commit",
            receipt_json=json.dumps(receipt),
        )
        assert result.authorized is False
        assert result.reason is not None and "Action mismatch" in result.reason

    def test_no_receipt_returns_missing_receipt(self) -> None:
        result = resolve_authorization(
            action="checkpoint.commit",
            receipt_json=None,
        )
        assert result.authorized is False
        assert result.reason == "missing_receipt"


class TestMintDevReceipt:
    def test_mint_dev_receipt_returns_valid_receipt(self) -> None:
        receipt = mint_dev_receipt("checkpoint.commit", ttl_seconds=300)
        assert receipt is not None
        valid, _ = validate_receipt(receipt, "checkpoint.commit")
        assert valid is True


class TestCheckpointAuthorizationGate:
    @pytest.fixture(autouse=True)
    def _reset_guard(self) -> Any:
        reset_guard()
        yield
        reset_guard()

    @staticmethod
    def _make_checkpoint(store_root: Path | None = None) -> Checkpoint:
        cfg = CheckpointToolConfig(
            store_root=store_root
            or Path.cwd() / ".build" / "rig-relay" / "test-coordination"
        )
        return Checkpoint(config_getter=lambda: cfg, state=BaseToolState())

    @staticmethod
    def _make_args(
        message: str = "test checkpoint",
        include_paths: list[str] | None = None,
        authorization_receipt: str | None = None,
        session_id: str = "test-session",
    ) -> CheckpointArgs:
        return CheckpointArgs(
            message=message,
            include_paths=include_paths or [],
            authorization_receipt=authorization_receipt,
            session_id=session_id,
        )

    def test_checkpoint_refuses_when_no_receipt(self) -> None:
        guard = get_guard()
        checkpoint = self._make_checkpoint()
        args = self._make_args(authorization_receipt=None)

        result = checkpoint._validate_preconditions(
            args,
            set(),
            {},
            CoordinationStore(checkpoint.config.store_root),
            guard,
            Path.cwd(),
        )
        assert result is not None
        assert result.ok is False
        assert "requires authorization receipt" in result.message

    def test_checkpoint_valid_receipt_works(self) -> None:
        guard = get_guard()
        guard.capture()
        checkpoint = self._make_checkpoint()
        receipt_json = _receipt_json("checkpoint.commit")
        args = self._make_args(authorization_receipt=receipt_json)

        result = checkpoint._validate_preconditions(
            args,
            set(),
            {},
            CoordinationStore(checkpoint.config.store_root),
            guard,
            Path.cwd(),
        )
        if result is not None:
            msg = result.message.lower()
            assert "authorization" not in msg
            refusal = result.refusal_reason or ""
            assert "receipt" not in refusal.lower()

    def test_emits_authorization_refused_event_on_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events_captured: list[dict[str, Any]] = []

        def _capture_event(
            session_id: str,
            event_name: str,
            payload: dict[str, Any],
            parent_session_id: str | None = None,
            receipt_candidate: bool = False,
        ) -> None:
            events_captured.append({
                "session_id": session_id,
                "event_name": event_name,
                "payload": payload,
                "receipt_candidate": receipt_candidate,
            })

        monkeypatch.setattr(
            "rig_relay.core.telemetry.local.log_local_event", _capture_event
        )

        guard = get_guard()
        checkpoint = self._make_checkpoint()
        args = self._make_args(
            authorization_receipt=None, session_id="auth-test-session"
        )

        _ = checkpoint._validate_preconditions(
            args,
            set(),
            {},
            CoordinationStore(checkpoint.config.store_root),
            guard,
            Path.cwd(),
        )

        auth_events = [
            e
            for e in events_captured
            if e["event_name"] == "governance.checkpoint_authorization_refused"
        ]
        assert len(auth_events) == 1
        event = auth_events[0]
        assert event["payload"]["session_id"] == "auth-test-session"
        assert event["payload"]["reason"] == "missing_receipt"
        assert "baseline_id" in event["payload"]
