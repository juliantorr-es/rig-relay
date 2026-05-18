"""Tests for AuthSessionManager — backend-owned OAuth loopback sessions.

Tests cover:
- start_session starts loopback listener before returning auth_url
- callback reaches listener from external browser
- state mismatch rejected
- callback received updates session status
- poll/check does not start second listener
- cancel cleans up listener
- timeout expires session
- exchange does not expose raw tokens in result
- manual code exchange path
- no backend main-thread blocking
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import httpx
import pytest

from rig_relay.desktop.intents import execute_desktop_intent
from rig_relay.identity.auth_session_manager import (
    AuthSessionManager,
    AuthSessionStatus,
    get_auth_session_manager,
)
from rig_relay.identity.github import GitHubIdentityProvider
from rig_relay.identity.google import GoogleIdentityProvider
from rig_relay.identity.models import IdentityProviderKind

pytestmark = [pytest.mark.integration]


def _valid_request(
    intent_name: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.desktop_intent_request.v1",
        "intent_id": f"test_auth_{secrets.token_hex(4)}",
        "created_at": "2026-05-14T00:00:00Z",
        "intent_name": intent_name,
        "parameters": params or {},
        "dry_run": True,
    }


class TestAuthSessionManager:
    def test_start_session_returns_auth_url_with_session_id(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)
        assert session.session_id
        assert auth_url.startswith("https://github.com/login/oauth/authorize")
        assert "client_id=test_id" in auth_url
        assert "redirect_uri" in auth_url
        assert session.status == AuthSessionStatus.PENDING
        session_id = session.session_id
        mgr.cancel_session(session_id)

    def test_start_session_starts_loopback_listener(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        # Give the background loop a moment to start the server
        time.sleep(0.2)
        assert session_obj.started.is_set()
        mgr.cancel_session(session_id)

    def test_callback_reaches_listener_real_http(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        # Wait for server to start
        assert session_obj.started.wait(timeout=5.0)
        time.sleep(0.1)  # give the event loop a tick to start accepting

        # Simulate browser callback with valid code and state
        callback_url = (
            f"{session.redirect_uri}?code=test_auth_code_123&state={session.state}"
        )

        # HTTP GET to the loopback server with extended timeout
        resp = httpx.get(callback_url, timeout=10.0)

        assert resp.status_code == 200
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        assert session_obj.status == AuthSessionStatus.CALLBACK_RECEIVED
        assert session_obj.code == "test_auth_code_123"

        mgr.cancel_session(session_id)

    def test_state_mismatch_rejected(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        session_obj.started.wait(timeout=5.0)

        # Callback with wrong state
        callback_url = (
            f"{session.redirect_uri}?code=test_auth_code_123&state=attacker_wrong_state"
        )

        resp = httpx.get(callback_url, timeout=5.0)
        assert resp.status_code == 400

        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        assert session_obj.status == AuthSessionStatus.FAILED
        assert session_obj.error_code == "state_mismatch"

    def test_callback_updates_session_status(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        assert session_obj.status == AuthSessionStatus.PENDING

        session_obj.started.wait(timeout=5.0)
        callback_url = f"{session.redirect_uri}?code=test_code&state={session.state}"
        httpx.get(callback_url, timeout=5.0)

        session_obj = mgr.get_session(session_id)
        assert session_obj.status == AuthSessionStatus.CALLBACK_RECEIVED

        mgr.cancel_session(session_id)

    def test_poll_does_not_start_second_listener(self):
        """sign_in_*_poll checks status without starting a listener."""
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )

        # Record initial port count... actually just verify poll doesn't create new
        # sessions or listeners
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)
        session_id = session.session_id

        # Poll the session — should not create new listeners
        check_result = mgr.check_session(session_id)
        assert check_result.get("status") == "pending"
        assert check_result.get("error") is None

        # Verify only one session exists
        assert len(mgr._sessions) == 1

        mgr.cancel_session(session_id)

    def test_pending_session_can_be_polled(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        result = mgr.check_session(session_id)
        assert result.get("status") == "pending"
        assert result.get("session_id") == session_id
        assert result.get("provider") == "github"

        mgr.cancel_session(session_id)

    def test_cancel_session_cleans_up_listener(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        session_obj = mgr.get_session(session_id)
        assert session_obj is not None
        session_obj.started.wait(timeout=5.0)

        # Cancel should clean up
        result = mgr.cancel_session(session_id)
        assert result.get("status") == "cancelled"
        assert mgr.get_session(session_id) is None

        # Verify listener is stopped
        assert session_obj._stop.is_set()
        assert session_obj._server is None or not session_obj._server.is_serving()

    def test_session_expires_after_timeout(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(
            IdentityProviderKind.GITHUB, provider, timeout=0.5
        )

        session_id = session.session_id
        # Poll after timeout
        time.sleep(1.0)
        result = mgr.check_session(session_id)
        assert result.get("status") == "expired"

    def test_no_raw_tokens_in_exchange_result(self):
        """Exchange result must not contain raw access_token, refresh_token, etc."""
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        mgr.get_session(session_id).started.wait(timeout=5.0)

        # Simulate callback
        callback_url = f"{session.redirect_uri}?code=test_code&state={session.state}"
        httpx.get(callback_url, timeout=5.0)

        # Exchange — will fail because no real GitHub credentials, but check result shape
        result = mgr.exchange_session(session_id)
        # Exchange should fail for fake credentials but NOT expose tokens
        assert "access_token" not in result
        assert "refresh_token" not in result
        assert "id_token" not in result
        # Content-light fields only
        assert "session_id" in result or "error" in result

    def test_no_main_thread_blocking(self):
        """start_session must not block main thread for 120s."""
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )

        start = time.time()
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)
        elapsed = time.time() - start

        # Should return in milliseconds, not seconds
        assert elapsed < 1.0, f"start_session blocked for {elapsed:.1f}s"
        assert session.session_id

        mgr.cancel_session(session.session_id)

    def test_exchange_manual_code(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(
            client_id="test_id", client_secret="test_secret"
        )
        session, auth_url = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        session_id = session.session_id
        result = mgr.exchange_manual_code(session_id, "manual_test_code")
        # Will fail exchange (fake credentials), but shouldn't expose tokens
        assert "access_token" not in result

    def test_shutdown_cleans_all_sessions(self):
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        session1, _ = mgr.start_session(IdentityProviderKind.GITHUB, provider)
        session2, _ = mgr.start_session(
            IdentityProviderKind.GOOGLE,
            GoogleIdentityProvider(client_id="test", client_secret="test"),
        )

        assert len(mgr._sessions) == 2
        mgr.shutdown()
        assert len(mgr._sessions) == 0

    def test_identity_summary_no_raw_state(self):
        """identity_summary must not expose raw state value."""
        mgr = AuthSessionManager()
        provider = GitHubIdentityProvider(client_id="test", client_secret="test")
        session, _ = mgr.start_session(IdentityProviderKind.GITHUB, provider)

        summary = session.identity_summary
        assert "state" not in summary
        assert session.state not in str(summary)
        # only state_hash is allowed
        assert session.state_hash not in str(summary.get("error_code", ""))

        mgr.cancel_session(session.session_id)


class TestDesktopIntentAuthFlow:
    def test_sign_in_start_returns_auth_url_and_session_id(self):
        """sign_in_*_start must return auth_url and auth_session_id."""
        import os

        os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = "test_id"
        os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = "test_secret"

        result = execute_desktop_intent(_valid_request("sign_in_github_start"))

        assert result.get("status") == "completed"
        extra = result.get("extra_fields", {})
        assert extra.get("auth_url", "").startswith("https://github.com")
        assert extra.get("auth_session_id")
        assert extra.get("status") == "pending"

        # Clean up sessions
        mgr = get_auth_session_manager()
        for s in list(mgr._sessions):
            mgr.cancel_session(s)

    def test_sign_in_start_not_configured_returns_warning(self):
        """Unconfigured provider returns warning, not error."""
        old_id = os.environ.pop("RIG_RELAY_GITHUB_CLIENT_ID", "")
        old_secret = os.environ.pop("RIG_RELAY_GITHUB_CLIENT_SECRET", "")
        try:
            result = execute_desktop_intent(_valid_request("sign_in_github_start"))
            assert result.get("status") == "completed"
            extra = result.get("extra_fields", {})
            assert extra.get("configured") is False
        finally:
            if old_id:
                os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = old_id
            if old_secret:
                os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = old_secret

    def test_sign_in_poll_without_session_id_fails(self):
        result = execute_desktop_intent(
            _valid_request("sign_in_github_poll", {"auth_session_id": ""})
        )
        assert result.get("status") == "failed"
        assert result.get("error_code") == "missing_parameters"

    def test_sign_in_poll_nonexistent_session_fails(self):
        result = execute_desktop_intent(
            _valid_request("sign_in_github_poll", {"auth_session_id": "nonexistent"})
        )
        assert result.get("status") == "failed"
        assert result.get("error_code") == "session_not_found"

    def test_sign_in_start_then_poll_then_cancel(self):
        """Full lifecycle: start -> poll -> cancel."""
        import os

        os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = "test_id"
        os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = "test_secret"

        # Start
        start_result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        assert start_result.get("status") == "completed"
        session_id = start_result.get("extra_fields", {}).get("auth_session_id")
        assert session_id

        # Poll while pending
        poll_result = execute_desktop_intent(
            _valid_request("sign_in_github_poll", {"auth_session_id": session_id})
        )
        assert poll_result.get("status") == "completed"
        assert poll_result.get("extra_fields", {}).get("status") == "pending"

        # Cancel
        cancel_result = execute_desktop_intent(
            _valid_request("sign_in_github_cancel", {"auth_session_id": session_id})
        )
        assert cancel_result.get("status") == "completed"

        # Clean up
        mgr = get_auth_session_manager()
        for s in list(mgr._sessions):
            mgr.cancel_session(s)

    def test_poll_does_not_block(self):
        """sign_in_*_poll must not block for callback timeout."""
        import os

        os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = "test_id"
        os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = "test_secret"

        start_result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        session_id = start_result.get("extra_fields", {}).get("auth_session_id")

        start_time = time.time()
        poll_result = execute_desktop_intent(
            _valid_request("sign_in_github_poll", {"auth_session_id": session_id})
        )
        elapsed = time.time() - start_time

        assert elapsed < 2.0, f"poll blocked for {elapsed:.1f}s"
        assert poll_result.get("status") == "completed"

        mgr = get_auth_session_manager()
        for s in list(mgr._sessions):
            mgr.cancel_session(s)

    def test_poll_does_not_start_second_listener(self):
        """sign_in_*_poll must not start a new loopback listener."""
        import os

        os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = "test_id"
        os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = "test_secret"

        mgr = get_auth_session_manager()
        initial_count = len(mgr._sessions)

        start_result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        session_id = start_result.get("extra_fields", {}).get("auth_session_id")
        assert len(mgr._sessions) == initial_count + 1

        # Poll multiple times — should NOT create new sessions/listeners
        for _ in range(3):
            execute_desktop_intent(
                _valid_request("sign_in_github_poll", {"auth_session_id": session_id})
            )

        assert len(mgr._sessions) == initial_count + 1

        mgr.cancel_session(session_id)

    def test_start_returns_auth_url_before_frontend_opens(self):
        """Backend MUST start listener BEFORE returning auth_url.
        Frontend opens auth_url after receiving the start result.
        """
        import os

        os.environ["RIG_RELAY_GITHUB_CLIENT_ID"] = "test_id"
        os.environ["RIG_RELAY_GITHUB_CLIENT_SECRET"] = "test_secret"

        mgr = get_auth_session_manager()
        start_result = execute_desktop_intent(_valid_request("sign_in_github_start"))
        session_id = start_result.get("extra_fields", {}).get("auth_session_id")

        # Get the session — listener should already be running
        session = mgr.get_session(session_id)
        assert session is not None
        session.started.wait(timeout=5.0)

        # Simulate callback — reaches listener started during sign_in_start
        callback_url = f"{session.redirect_uri}?code=test_code&state={session.state}"
        resp = httpx.get(callback_url, timeout=5.0)
        assert resp.status_code == 200
        assert session.status == AuthSessionStatus.CALLBACK_RECEIVED

        mgr.cancel_session(session_id)


import os
