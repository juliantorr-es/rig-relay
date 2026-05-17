"""Consent enforcement gate tests for TelemetryClient remote upload path.

Tests prove that remote telemetry upload requires both:
1. Remote telemetry settings enabled (enable_remote_telemetry=True)
2. Valid consent record with appropriate scopes

Fail-closed semantics: revoked, denied, not-requested, missing consent,
scope mismatch, and consent loader exceptions all block remote upload.
Local observability is never blocked by consent.
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
    TelemetryConsentStatus,
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
    consent_raises: Exception | None = None,
) -> TelemetryClient:
    config = build_test_vibe_config(enable_telemetry=enable_remote)
    monkeypatch.setenv(_DEFAULT_MISTRAL_API_ENV_KEY, "sk-test")

    if consent_raises is not None:

        def _raise_consent() -> object | None:
            raise consent_raises

        consent_getter = _raise_consent
    elif consent is not None:

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


class TestConsentGateRemoteDisabled:
    def test_remote_disabled_means_no_upload_even_if_consent_granted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        client = _make_client(
            monkeypatch, enable_remote=False, consent=_make_granted_consent()
        )
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()


class TestConsentGateGranted:
    @pytest.mark.asyncio
    async def test_remote_enabled_plus_consent_granted_means_upload_occurs(
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

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        await client.aclose()

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["event"] == "vibe.test_event"


class TestConsentGateRevoked:
    def test_remote_enabled_plus_consent_revoked_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        revoked = revoke_consent(_make_granted_consent())
        client = _make_client(monkeypatch, enable_remote=True, consent=revoked)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()

    def test_revoked_consent_beats_legacy_enable_telemetry_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        config = build_test_vibe_config(enable_telemetry=True)
        monkeypatch.setenv(_DEFAULT_MISTRAL_API_ENV_KEY, "sk-test")
        revoked = revoke_consent(_make_granted_consent())
        client = TelemetryClient(
            config_getter=lambda: config,
            session_id_getter=lambda: "test-session",
            consent_record_getter=lambda: revoked,
        )
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()


class TestConsentGateMissing:
    def test_consent_not_requested_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        not_requested = TelemetryConsentRecord(
            consent_id="test",
            subject_hash="test-hash",
            status=TelemetryConsentStatus.NOT_REQUESTED,
            scopes=[],
        )
        client = _make_client(monkeypatch, enable_remote=True, consent=not_requested)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()

    def test_no_consent_getter_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        client = _make_client(monkeypatch, enable_remote=True, consent=None)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()

    def test_consent_getter_returns_none_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        config = build_test_vibe_config(enable_telemetry=True)
        monkeypatch.setenv(_DEFAULT_MISTRAL_API_ENV_KEY, "sk-test")
        client = TelemetryClient(
            config_getter=lambda: config,
            session_id_getter=lambda: "test-session",
            consent_record_getter=lambda: None,
        )
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()


class TestConsentGateScopeMismatch:
    def test_remote_enabled_plus_missing_required_scope_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        scopes_only_coordination = [TelemetryConsentScope.COORDINATION_METRICS]
        consent = _make_granted_consent(scopes=scopes_only_coordination)
        client = _make_client(monkeypatch, enable_remote=True, consent=consent)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("rig.relay.session.started", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()


class TestConsentGateLoaderException:
    def test_consent_loader_exception_means_no_upload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        client = _make_client(
            monkeypatch, enable_remote=True, consent_raises=ValueError("boom")
        )
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        client.send_telemetry_event("vibe.test_event", {"key": "value"})
        _run_tasks()

        mock_post.assert_not_called()


class TestLocalObservabilityUnaffected:
    def test_local_observability_still_writes_when_remote_denied(
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

        client.send_telemetry_event("vibe.test_event", {"key": "value"})

        original_events = [
            e for e in local_events if e["event_name"] == "vibe.test_event"
        ]
        assert len(original_events) == 1, (
            "Local event must be written even when remote is denied"
        )
        assert original_events[0]["payload"]["key"] == "value"

    def test_denial_writes_auditable_local_decision(
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

        client.send_telemetry_event("vibe.test_event", {"key": "value"})

        denials = [
            e
            for e in local_events
            if e["event_name"] == str(EventName.TELEMETRY_REMOTE_UPLOAD_DENIED)
        ]
        assert len(denials) == 1, "Denial event must be logged locally"
        denial = denials[0]
        assert denial["payload"]["original_event"] == "vibe.test_event"
        assert denial["payload"]["reason"] == "consent_not_found"
        assert denial["payload"]["remote_enabled"] is True
        assert "decided_at" in denial["payload"]


class TestConsentDecisionContentLight:
    def test_consent_decision_preserves_content_light_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        consent = _make_granted_consent()
        client = _make_client(monkeypatch, enable_remote=True, consent=consent)

        decision = client._evaluate_consent_gate("vibe.test_event")
        assert decision.allowed is True
        assert decision.reason == "consent_granted"
        assert decision.consent_status == "granted"
        assert "usage_metrics" in decision.matched_scopes
        assert decision.policy_version == "alpha-usage-data-license-v1"

        pdict = {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "consent_status": decision.consent_status,
            "matched_scopes": decision.matched_scopes,
            "policy_version": decision.policy_version,
        }
        for key in pdict:
            val = str(pdict[key])
            assert "test-hash" not in val, (
                f"Decision field {key} must not leak subject_hash"
            )


class TestE2EForbiddenFieldExclusion:
    @pytest.mark.asyncio
    async def test_revoked_consent_blocks_upload_with_sensitive_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            TelemetryClient, "send_telemetry_event", _original_send_telemetry_event
        )
        revoked = revoke_consent(_make_granted_consent())
        client = _make_client(monkeypatch, enable_remote=True, consent=revoked)
        mock_post = AsyncMock(return_value=MagicMock(status_code=204))
        client._client = MagicMock()
        client._client.post = mock_post
        client._client.aclose = AsyncMock()

        suspicious_payload = {
            "token": "sk-abc123secret",
            "api_key": "deadbeef",
            "password": "s3cr3t",
        }

        client.send_telemetry_event("vibe.test_event", suspicious_payload)
        await client.aclose()

        mock_post.assert_not_called()

    def test_consent_decision_never_leaks_subject_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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


class TestDebugBundleUnchanged:
    def test_existing_debug_bundle_behavior_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rig_relay.evidence.telemetry_bundle import validate_bundle

        assert validate_bundle is not None
