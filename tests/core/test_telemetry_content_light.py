"""Content-light redaction and consent expiry enforcement tests.

Probes the telemetry consent gate for:
1. Whether granted remote upload redacts forbidden fields from HTTP POST
2. Whether consent decision fields preserve content-light boundary
3. Whether denial events are auditable and privacy-preserving
4. Whether expired consent blocks upload (expires_at enforcement)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rig_relay.core.telemetry.constants import EventName
from rig_relay.core.telemetry.send import TelemetryClient
from rig_relay.identity.telemetry_consent import (
    TelemetryConsentRecord,
    TelemetryConsentScope,
    grant_consent,
    revoke_consent,
)
from tests.conftest import build_test_vibe_config

_original_send_telemetry_event = TelemetryClient.send_telemetry_event
_DEFAULT_MISTRAL_API_ENV_KEY = "MISTRAL_API_KEY"


def _make_granted_consent(
    scopes: list[TelemetryConsentScope] | None = None,
) -> TelemetryConsentRecord:
    if scopes is None:
        scopes = [
            TelemetryConsentScope.USAGE_METRICS,
            TelemetryConsentScope.CONTENT_LIGHT_BUNDLES,
            TelemetryConsentScope.CRASH_REPORTS,
            TelemetryConsentScope.COORDINATION_METRICS,
            TelemetryConsentScope.TOOL_REFINEMENT_METRICS,
        ]
    return grant_consent(subject_hash="test-hash", provider="test", scopes=scopes)


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enable_remote: bool = True,
    consent: TelemetryConsentRecord | None = None,
) -> TelemetryClient:
    config = build_test_vibe_config(enable_telemetry=enable_remote)
    monkeypatch.setenv(_DEFAULT_MISTRAL_API_ENV_KEY, "sk-test")

    if consent is not None:

        def _get_consent() -> object | None:
            return consent

        consent_getter = _get_consent
    else:
        consent_getter = None

    return TelemetryClient(
        config_getter=lambda: config,
        session_id_getter=lambda: "test-session",
        consent_record_getter=consent_getter,
    )


def _run_tasks() -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()


# ── Redaction: granted upload leaks forbidden fields ─────────────


class TestGrantedUploadRedactionLeak:
    """Prove that when consent IS granted and remote upload proceeds,
    forbidden payload fields are redacted from the HTTP POST body.

    OPEN SEAM: redact_for_remote is never called in send_telemetry_event.
    """

    @pytest.mark.xfail(
        reason=(
            "redact_for_remote is never called in send_telemetry_event "
            "(send.py:216-233). Forbidden scalar values leak into HTTP POST."
        ),
        strict=True,
    )
    @pytest.mark.asyncio
    async def test_granted_upload_redacts_forbidden_payload_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        client = _make_client(
            monkeypatch, enable_remote=True, consent=_make_granted_consent()
        )
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        forbidden_payload = {
            "token": "sk-abc123secret",
            "api_key": "deadbeef",
            "password": "s3cr3t",
            "secret": "my-secret-value",
            "credential": "cred-xyz",
            "authorization": "Bearer token123",
            "cookie": "session=abc123",
            "bearer": "bearer-token-789",
            "raw_prompt": "write malicious code",
            "file_path": "/Users/example/private.txt",
            "count": 42,
            "status": "ok",
        }

        client.send_telemetry_event("vibe.test_event", forbidden_payload)
        await client.aclose()

        mock_post.assert_called_once()
        posted_json = mock_post.call_args.kwargs["json"]
        posted_properties = posted_json["properties"]

        forbidden_keys = [
            "token",
            "api_key",
            "password",
            "secret",
            "credential",
            "authorization",
            "cookie",
            "bearer",
            "raw_prompt",
            "file_path",
        ]

        leaked: list[str] = []
        for key in forbidden_keys:
            val = posted_properties.get(key)
            assert val is not None, f"Forbidden key {key!r} missing from POST body"
            is_redacted = val == "[REDACTED]" or (
                isinstance(val, str) and val.startswith("sha256:")
            )
            if not is_redacted:
                leaked.append(f"{key}={val!r}")

        assert not leaked, f"Forbidden fields leaked in HTTP POST body: {leaked}"
        assert posted_properties["count"] == 42
        assert posted_properties["status"] == "ok"


# ── Content-light: consent decision fields ───────────────────────


class TestConsentDecisionPrivacy:
    def test_denial_event_excludes_subject_hash_and_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        client = _make_client(monkeypatch, enable_remote=True, consent=None)
        local_events: list[dict[str, Any]] = []

        import rig_relay.core.telemetry.local as local_mod

        def _fake_log(
            session_id: str,
            event_name: str,
            payload: dict[str, Any],
            parent_session_id: str | None = None,
            receipt_candidate: bool = False,
        ) -> None:
            local_events.append({
                "session_id": session_id,
                "event_name": event_name,
                "payload": payload,
            })

        monkeypatch.setattr(local_mod, "log_local_event", _fake_log)

        client.send_telemetry_event(
            "vibe.test_event", {"secret_key": "should-not-leak"}
        )
        _run_tasks()

        denials = [
            e
            for e in local_events
            if e["event_name"] == str(EventName.TELEMETRY_REMOTE_UPLOAD_DENIED)
        ]
        assert len(denials) == 1, "Must emit one denial event"
        denial_payload = denials[0]["payload"]
        assert "subject_hash" not in denial_payload
        assert "secret_key" not in denial_payload
        assert "should-not-leak" not in str(denial_payload)
        assert denial_payload["original_event"] == "vibe.test_event"
        assert denial_payload["reason"] == "consent_not_found"

    def test_revoked_consent_denial_excludes_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        revoked = revoke_consent(_make_granted_consent())
        client = _make_client(monkeypatch, enable_remote=True, consent=revoked)
        local_events: list[dict[str, Any]] = []

        import rig_relay.core.telemetry.local as local_mod

        def _fake_log(
            session_id: str,
            event_name: str,
            payload: dict[str, Any],
            parent_session_id: str | None = None,
            receipt_candidate: bool = False,
        ) -> None:
            local_events.append({
                "session_id": session_id,
                "event_name": event_name,
                "payload": payload,
            })

        monkeypatch.setattr(local_mod, "log_local_event", _fake_log)

        suspicious_payload = {
            "token": "sk-abc123secret",
            "api_key": "deadbeef",
            "raw_prompt": "leaked prompt",
        }
        client.send_telemetry_event("vibe.test_event", suspicious_payload)
        _run_tasks()

        denials = [
            e
            for e in local_events
            if e["event_name"] == str(EventName.TELEMETRY_REMOTE_UPLOAD_DENIED)
        ]
        assert len(denials) == 1, "Must emit denial event"
        dp = denials[0]["payload"]
        assert dp["reason"] == "consent_revoked"
        assert dp["original_event"] == "vibe.test_event"
        assert dp["remote_enabled"] is True
        assert "decided_at" in dp
        assert "token" not in dp
        assert "api_key" not in dp
        assert "raw_prompt" not in dp
        assert "sk-abc123secret" not in str(dp)

    def test_granted_decision_excludes_subject_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        consent = _make_granted_consent()
        client = _make_client(monkeypatch, enable_remote=True, consent=consent)

        decision = client._evaluate_consent_gate("vibe.test_event")
        decision_dict = {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "consent_status": decision.consent_status,
            "matched_scopes": decision.matched_scopes,
            "missing_scopes": decision.missing_scopes,
            "policy_version": decision.policy_version,
            "remote_enabled": decision.remote_enabled,
        }
        serialized = str(decision_dict)
        assert "test-hash" not in serialized, "Decision must not leak subject_hash"
        assert consent.subject_hash not in serialized


# ── Consent expiry enforcement ───────────────────────────────────


class TestConsentExpiryEnforcement:
    """The TelemetryConsentRecord model has an expires_at field but
    _evaluate_consent_gate does not check it. Expired consent passes.

    OPEN SEAM: expires_at is never checked by _evaluate_consent_gate.
    """

    @pytest.mark.xfail(
        reason=(
            "expires_at is never checked by _evaluate_consent_gate "
            "(send.py:252-356). Expired consent with granted status passes."
        ),
        strict=True,
    )
    def test_expired_consent_blocks_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        expired_consent = _make_granted_consent()
        expired_consent.expires_at = "2020-01-01T00:00:00+00:00"
        client = _make_client(monkeypatch, enable_remote=True, consent=expired_consent)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()
